package tui

import (
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/ansi"
)

// selectionTickInterval is how often a drag that reached the top or bottom edge
// of the transcript scrolls it.
const selectionTickInterval = 50 * time.Millisecond

// The highlight is reverse video: it composes with whatever the markdown
// renderer already drew, and it needs no colour support to be visible. The
// reset in front of it keeps a style the renderer left open from tinting the
// selection.
const (
	sgrReverse = "\x1b[7m"
	sgrReset   = "\x1b[0m"
)

// selectionTickMsg advances a drag that reached an edge. gen identifies the
// drag that armed the tick, so a tick left over from a finished drag cannot
// scroll the transcript.
type selectionTickMsg struct{ gen int }

// selectionPoint addresses one cell of the viewport content: a content line
// index plus a cell column inside it. Content coordinates do not move with the
// scroll offset, so a selection keeps addressing the same text while the
// viewport scrolls under it.
type selectionPoint struct {
	line int
	col  int
}

// selection is the mouse text selection. It holds coordinates only: the text it
// covers is resolved against the current content when it is copied, so a
// selection whose content was replaced in the meantime can never copy text that
// is no longer there.
type selection struct {
	active     bool // the highlight is on screen
	dragging   bool // the button is still down
	anchor     selectionPoint
	focus      selectionPoint
	autoScroll int // -1 scrolls up, +1 scrolls down, 0 holds still
}

// empty reports whether the drag covers nothing, which is also how a plain
// click is told apart from a selection.
func (s selection) empty() bool { return s.anchor == s.focus }

// ordered returns the endpoints with the earlier one first, so that dragging in
// either direction reads the same way.
func (s selection) ordered() (selectionPoint, selectionPoint) {
	if s.focus.line < s.anchor.line || (s.focus.line == s.anchor.line && s.focus.col < s.anchor.col) {
		return s.focus, s.anchor
	}
	return s.anchor, s.focus
}

// span returns the cell range [from, to) the selection covers on a content
// line, and whether the line is covered at all. The endpoints are snapped to
// grapheme boundaries: a cut through a wide character would make the piece
// before the selection, the selection, and the piece after it cover a
// different number of cells than the line they replace.
func (s selection) span(plain string, line int) (from, to int, ok bool) {
	start, end := s.ordered()
	if line < start.line || line > end.line {
		return 0, 0, false
	}
	width := ansi.StringWidth(plain)
	from, to = 0, width
	if line == start.line {
		from = snapCellStart(plain, start.col)
	}
	if line == end.line {
		// The cell under the pointer is part of the selection, so the endpoint
		// is exclusive one cell past it.
		to = snapCellEnd(plain, end.col+1)
	}
	from = min(max(from, 0), width)
	to = min(max(to, from), width)
	return from, to, true
}

// text returns the text the selection covers. Columns are cell offsets, so wide
// characters are never cut in half, and the padding the layout adds past the
// end of a line is dropped.
func (s selection) text(lines []string) string {
	start, end := s.ordered()
	if len(lines) == 0 || start.line >= len(lines) || end.line < 0 {
		return ""
	}
	first, last := max(0, start.line), min(end.line, len(lines)-1)
	var out strings.Builder
	for line := first; line <= last; line++ {
		if line > first {
			out.WriteByte('\n')
		}
		plain := ansi.Strip(lines[line])
		from, to, _ := s.span(plain, line)
		out.WriteString(strings.TrimRight(cellRange(plain, from, to), " "))
	}
	return out.String()
}

// cellRange returns the cells [from, to) of plain text.
func cellRange(plain string, from, to int) string {
	if to <= from {
		return ""
	}
	return ansi.TruncateLeft(ansi.Truncate(plain, to, ""), from, "")
}

// snapCellStart returns the first cell of the grapheme that contains cell col,
// so a click that lands in the middle of a wide character starts at that
// character rather than inside it.
func snapCellStart(plain string, col int) int {
	col = min(max(col, 0), ansi.StringWidth(plain))
	return min(col, ansi.StringWidth(ansi.Truncate(plain, col, "")))
}

// snapCellEnd returns the first grapheme boundary at or after cell col.
func snapCellEnd(plain string, col int) int {
	total := ansi.StringWidth(plain)
	col = min(max(col, 0), total)
	for end := col; end < total; end++ {
		if ansi.StringWidth(ansi.Truncate(plain, end, "")) == end {
			return end
		}
	}
	return total
}

// highlightRow paints the cells [from, to) of a rendered row, which start at
// cell left, as the selection. The covered run is redrawn from its plain text:
// keeping the original escape codes would let the markdown renderer's own
// backgrounds fight the highlight, and re-arming an attribute across arbitrary
// resets cannot be done reliably.
func highlightRow(row string, left, from, to int) string {
	if to <= from {
		return row
	}
	selected := ansi.Strip(ansi.Cut(row, left+from, left+to))
	selected = ansi.Truncate(selected, to-from, "")
	if padding := to - from - ansi.StringWidth(selected); padding > 0 {
		selected += strings.Repeat(" ", padding)
	}
	head := ansi.Truncate(row, left+from, "")
	tail := ansi.TruncateLeft(row, left+to, "")
	return fitWidth(head+sgrReset+sgrReverse+selected+sgrReset+tail, ansi.StringWidth(row))
}

// fitWidth keeps a rewritten row exactly as wide as the row it replaces. A row
// that changes width makes the layout pad every other row to match it, and the
// renderer then clips the whole screen.
func fitWidth(row string, width int) string {
	switch current := ansi.StringWidth(row); {
	case current > width:
		return ansi.Truncate(row, width, "")
	case current < width:
		return row + strings.Repeat(" ", width-current)
	}
	return row
}

// contentPoint maps a screen cell to the content cell under it. With clamp set,
// a pointer outside the content rows resolves to the nearest covered row, so a
// drag that leaves the viewport goes on extending the selection at its edge.
func (a App) contentPoint(y, x int, clamp bool) (selectionPoint, bool) {
	layout := a.layout()
	if len(a.contentLines) == 0 {
		return selectionPoint{}, false
	}
	line := y - layout.topRow - layout.viewportTop + a.viewport.YOffset
	if clamp {
		line = min(max(line, a.viewport.YOffset), a.viewport.YOffset+max(0, layout.rows-1))
		line = min(line, len(a.contentLines)-1)
	} else if y < layout.topRow+layout.viewportTop || y >= layout.topRow+layout.viewportTop+layout.rows {
		// A click outside the visible transcript selects nothing. Offsetting
		// past its end would otherwise resolve to a line that is not on screen.
		return selectionPoint{}, false
	}
	if line < 0 || line >= len(a.contentLines) {
		return selectionPoint{}, false
	}
	// The column is kept as the pointer reported it. Snapping belongs in span,
	// where the cuts happen: snapping here would collapse a press and a release
	// inside the same wide character into the same cell, which reads as a click.
	col := min(max(x-layout.contentLeft, 0), layout.lineWidth)
	return selectionPoint{line: line, col: col}, true
}

// autoScrollDirection reports whether a pointer at screen row y sits outside
// the visible transcript, and which way the drag should scroll it.
func (a App) autoScrollDirection(y int) int {
	layout := a.layout()
	switch {
	case y < layout.topRow+layout.viewportTop:
		return -1
	case y >= layout.topRow+layout.viewportTop+layout.rows:
		return 1
	}
	return 0
}

// edgePoint is the content cell an edge drag extends to: the first or last line
// the viewport shows, keeping the column the drag reached.
func (a App) edgePoint() selectionPoint {
	layout := a.layout()
	line := a.viewport.YOffset
	if a.selection.autoScroll > 0 {
		line += max(0, layout.rows-1)
	}
	return selectionPoint{line: min(max(line, 0), max(0, len(a.contentLines)-1)), col: a.selection.focus.col}
}

// selectionTickCommand arms the next auto-scroll step for drag gen.
func selectionTickCommand(gen int) tea.Cmd {
	return tea.Tick(selectionTickInterval, func(time.Time) tea.Msg { return selectionTickMsg{gen: gen} })
}

// autoScrollStep scrolls the transcript one line and extends the selection to
// the line that scrolled into view. Exactly one chain of ticks runs per drag:
// a tick whose generation no longer matches is the last one.
func (a App) autoScrollStep(message selectionTickMsg) (tea.Model, tea.Cmd) {
	if !a.selection.dragging || message.gen != a.selectionGen {
		return a, nil
	}
	if a.selection.autoScroll != 0 && a.viewport.TotalLineCount() > 0 {
		a.viewport.Height = a.layout().blockHeight
		if a.selection.autoScroll > 0 {
			a.viewport.ScrollDown(1)
		} else {
			a.viewport.ScrollUp(1)
		}
		a.selection.focus = a.edgePoint()
	}
	return a, selectionTickCommand(message.gen)
}
