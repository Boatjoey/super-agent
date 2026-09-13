package tui_test

import (
	"context"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/x/ansi"

	"super-agent/tui"
)

const (
	selectionWidth  = 80
	selectionHeight = 24
)

// selectionConversation scripts an exact transcript, so a test can name the
// text it drags across instead of guessing at what the model renders.
type selectionConversation struct {
	*notificationOnlyConversation
	transcript []tui.Message
}

func (c *selectionConversation) RunTurn(_ context.Context, _ string, notifications chan<- tui.ConversationNotification, _ <-chan tui.ApprovalDecision) error {
	notifications <- tui.AgentStatusChanged{Status: tui.AgentStatus{Label: "WaitingLLM", Busy: true}}
	for _, message := range c.transcript {
		notifications <- tui.MessageAppended{Message: message}
	}
	notifications <- tui.AgentStatusChanged{Status: tui.AgentStatus{Label: "Idle"}}
	close(notifications)
	return nil
}

// clipboardSpy observes what the TUI copies without touching the real
// clipboard.
type clipboardSpy struct {
	writes []string
}

func (s *clipboardSpy) write(text string) error {
	s.writes = append(s.writes, text)
	return nil
}

func (s *clipboardSpy) copied() string {
	if len(s.writes) == 0 {
		return ""
	}
	return s.writes[len(s.writes)-1]
}

// newSelectionTUI renders a transcript and returns the model with the spy
// wired to its clipboard.
func newSelectionTUI(t *testing.T, transcript ...tui.Message) (tea.Model, *clipboardSpy) {
	t.Helper()
	spy := &clipboardSpy{}
	conversation := &selectionConversation{
		notificationOnlyConversation: &notificationOnlyConversation{rejectSnapshots: true},
		transcript:                   transcript,
	}
	var model tea.Model = tui.New(
		conversation,
		tui.StartupInfo{Provider: "test", ModelName: "test-model"},
		tui.WithClipboardWriter(spy.write),
	)
	model, _ = model.Update(tea.WindowSizeMsg{Width: selectionWidth, Height: selectionHeight})
	return runSelectionTurn(t, model), spy
}

// runSelectionTurn submits a prompt and feeds every scripted notification into
// the model, then the completion message, leaving it in the state a finished
// turn produces.
func runSelectionTurn(t *testing.T, model tea.Model) tea.Model {
	t.Helper()
	model = typeText(model, "hello")
	model, command := model.Update(tea.KeyMsg{Type: tea.KeyEnter})
	if command == nil {
		t.Fatal("submitting produced no command")
	}
	batch, ok := command().(tea.BatchMsg)
	if !ok || len(batch) < 2 {
		t.Fatalf("submitting produced %T, want a batch of a listener and a run", command())
	}
	run := batch[len(batch)-1]
	if run == nil {
		t.Fatal("submitting produced no run command")
	}
	completion := run()
	for events := batch[0]; events != nil; {
		message := events()
		if message == nil {
			break
		}
		model, events = model.Update(message)
	}
	if completion != nil {
		model, _ = model.Update(completion)
	}
	return model
}

// locate returns the screen row and the cell column where marker starts.
func locate(t *testing.T, view, marker string) (int, int) {
	t.Helper()
	for row, line := range strings.Split(view, "\n") {
		plain := ansi.Strip(line)
		if at := strings.Index(plain, marker); at >= 0 {
			return row, ansi.StringWidth(plain[:at])
		}
	}
	t.Fatalf("marker %q is not on screen:\n%s", marker, view)
	return 0, 0
}

func mousePress(x, y int) tea.MouseMsg {
	return tea.MouseMsg{Action: tea.MouseActionPress, Button: tea.MouseButtonLeft, X: x, Y: y}
}

func mouseMotion(x, y int) tea.MouseMsg {
	return tea.MouseMsg{Action: tea.MouseActionMotion, Button: tea.MouseButtonLeft, X: x, Y: y}
}

func mouseRelease(x, y int) tea.MouseMsg {
	return tea.MouseMsg{Action: tea.MouseActionRelease, Button: tea.MouseButtonLeft, X: x, Y: y}
}

// drag presses, moves, and releases the left button, then runs the copy the
// release scheduled.
func drag(t *testing.T, model tea.Model, fromX, fromY, toX, toY int) tea.Model {
	t.Helper()
	model, _ = model.Update(mousePress(fromX, fromY))
	model, _ = model.Update(mouseMotion(toX, toY))
	var command tea.Cmd
	model, command = model.Update(mouseRelease(toX, toY))
	if command != nil {
		if message := command(); message != nil {
			model, _ = model.Update(message)
		}
	}
	return model
}

// assertBorderedRowsFit fails when a transcript row is not exactly as wide as
// the terminal. A row that changes width makes the layout pad every other row
// to match it, and the renderer then clips the right border off the whole
// screen.
func assertBorderedRowsFit(t *testing.T, view string, width int) {
	t.Helper()
	rows := 0
	for index, line := range strings.Split(view, "\n") {
		if !strings.HasPrefix(ansi.Strip(line), "│") {
			continue
		}
		rows++
		if got := lipgloss.Width(line); got != width {
			t.Fatalf("transcript row %d is %d cells wide, want %d: %q", index, got, width, ansi.Strip(line))
		}
	}
	if rows == 0 {
		t.Fatal("the view has no transcript rows; the layout changed")
	}
}

func longTranscript() []tui.Message {
	messages := make([]tui.Message, 0, 30)
	for index := 0; index < 30; index++ {
		messages = append(messages, tui.Message{Role: tui.RoleAssistant, Content: strings.Repeat("message ", 12)})
	}
	return messages
}

func TestDragSelectionCopiesTheVisibleText(t *testing.T) {
	model, spy := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "alpha bravo charlie delta"})

	row, column := locate(t, model.View(), "bravo")
	model = drag(t, model, column, row, column+4, row)

	if got := spy.copied(); got != "bravo" {
		t.Fatalf("copied %q, want %q", got, "bravo")
	}
	if view := model.View(); !strings.Contains(view, "\x1b[7m") {
		t.Fatalf("the selection is not highlighted:\n%s", view)
	}
	if status := model.View(); !strings.Contains(status, "Copied 1 line") || strings.Contains(status, "lines") {
		t.Fatalf("view does not report the copied line count: %q", status)
	}
}

func TestDragSelectionSpansLines(t *testing.T) {
	model, spy := newSelectionTUI(t,
		tui.Message{Role: tui.RoleAssistant, Content: "alpha bravo"},
		tui.Message{Role: tui.RoleAssistant, Content: "charlie delta"},
	)

	view := model.View()
	firstRow, firstColumn := locate(t, view, "bravo")
	secondRow, secondColumn := locate(t, view, "charlie")
	if secondRow <= firstRow {
		t.Fatalf("the transcript did not put the two messages on separate rows: %d and %d", firstRow, secondRow)
	}

	model = drag(t, model, firstColumn, firstRow, secondColumn+12, secondRow)

	lines := strings.Split(spy.copied(), "\n")
	if len(lines) != secondRow-firstRow+1 {
		t.Fatalf("copied %q, want one line per covered row", spy.copied())
	}
	// Every covered row is copied as it is drawn: the first one from the
	// pointer rightwards, which is where the selection started.
	covered := strings.Split(ansi.Strip(model.View()), "\n")[firstRow : secondRow+1]
	for index, row := range covered {
		row = ansi.TruncateLeft(strings.TrimSuffix(row, "│"), 1, "")
		if index == 0 {
			row = ansi.TruncateLeft(row, firstColumn-1, "")
		}
		if want := strings.TrimRight(row, " "); lines[index] != want {
			t.Fatalf("line %d copied as %q, want %q", index, lines[index], want)
		}
	}
	if !strings.HasPrefix(lines[0], "bravo") || !strings.HasSuffix(lines[len(lines)-1], "charlie delta") {
		t.Fatalf("copied %q, want the drag's endpoints", spy.copied())
	}
}

func TestSelectionAlignsWideCharacters(t *testing.T) {
	model, spy := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "中文测试文本 abc"})

	row, column := locate(t, model.View(), "中文测试文本")
	// 12 cells of CJK text: pressing on the first cell and releasing on the
	// second half of the last character must cover whole characters only.
	model = drag(t, model, column, row, column+11, row)

	if got := spy.copied(); got != "中文测试文本" {
		t.Fatalf("copied %q, want %q", got, "中文测试文本")
	}
	assertBorderedRowsFit(t, model.View(), selectionWidth)
}

func TestSelectionSnapsToTheGraphemeUnderThePointer(t *testing.T) {
	model, spy := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "中文测试文本 abc"})

	row, column := locate(t, model.View(), "中文测试文本")
	// Both ends land inside the first character: pressing on its second half
	// and releasing on its first must still copy the whole character.
	model = drag(t, model, column+1, row, column, row)

	if got := spy.copied(); got != "中" {
		t.Fatalf("copied %q, want %q", got, "中")
	}
	assertBorderedRowsFit(t, model.View(), selectionWidth)
}

func TestSelectionKeepsEveryRowAtTheTerminalWidth(t *testing.T) {
	model, _ := newSelectionTUI(t, longTranscript()...)

	assertBorderedRowsFit(t, model.View(), selectionWidth)
	row, column := locate(t, model.View(), "message message")
	model = drag(t, model, column, row, column+40, row-1)
	assertBorderedRowsFit(t, model.View(), selectionWidth)
}

func TestWheelScrollsTheTranscript(t *testing.T) {
	model, _ := newSelectionTUI(t, longTranscript()...)
	if view := model.View(); !strings.Contains(view, "100%") {
		t.Fatalf("the transcript does not start at the bottom:\n%s", view)
	}

	model, _ = model.Update(tea.MouseMsg{Action: tea.MouseActionPress, Button: tea.MouseButtonWheelUp, X: 10, Y: 10})

	if view := model.View(); strings.Contains(view, "100%") {
		t.Fatal("the wheel did not scroll the transcript")
	}
}

func TestShiftWheelLeavesTheTranscriptAlone(t *testing.T) {
	model, _ := newSelectionTUI(t, longTranscript()...)

	message := tea.MouseMsg{Action: tea.MouseActionPress, Button: tea.MouseButtonWheelUp, Shift: true, X: 10, Y: 10}
	model, _ = model.Update(message)

	if view := model.View(); !strings.Contains(view, "100%") {
		t.Fatal("shift+wheel scrolled horizontally and clipped the transcript")
	}
}

func TestClickWithoutDragCopiesNothing(t *testing.T) {
	model, spy := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "alpha bravo charlie"})

	row, column := locate(t, model.View(), "bravo")
	model = drag(t, model, column, row, column, row)

	if len(spy.writes) != 0 {
		t.Fatalf("a click copied %q", spy.copied())
	}
	if view := model.View(); strings.Contains(view, "\x1b[7m") {
		t.Fatalf("a click left a highlight:\n%s", view)
	}
}

func TestShiftDragStaysWithTheTerminal(t *testing.T) {
	model, spy := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "alpha bravo charlie"})

	row, column := locate(t, model.View(), "bravo")
	model, _ = model.Update(tea.MouseMsg{Action: tea.MouseActionPress, Button: tea.MouseButtonLeft, Shift: true, X: column, Y: row})
	model, _ = model.Update(tea.MouseMsg{Action: tea.MouseActionMotion, Button: tea.MouseButtonLeft, Shift: true, X: column + 5, Y: row})
	model, _ = model.Update(tea.MouseMsg{Action: tea.MouseActionRelease, Button: tea.MouseButtonLeft, Shift: true, X: column + 5, Y: row})

	if len(spy.writes) != 0 {
		t.Fatalf("shift+drag copied %q instead of leaving the terminal to select", spy.copied())
	}
	if view := model.View(); strings.Contains(view, "\x1b[7m") {
		t.Fatalf("shift+drag left a highlight:\n%s", view)
	}
}

func TestClickOutsideTheTranscriptSelectsNothing(t *testing.T) {
	model, spy := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "alpha bravo charlie"})

	_, column := locate(t, model.View(), "bravo")
	// Row 0 is the header, and the footer is below the transcript.
	for _, row := range []int{0, selectionHeight - 1} {
		model, _ = model.Update(mousePress(column, row))
		model, _ = model.Update(mouseMotion(column+5, row))
		model, _ = model.Update(mouseRelease(column+5, row))
	}

	if len(spy.writes) != 0 {
		t.Fatalf("a click outside the transcript copied %q", spy.copied())
	}
}

func TestReplacingTheTranscriptDropsTheSelection(t *testing.T) {
	model, spy := newSelectionTUI(t, longTranscript()...)

	row, column := locate(t, model.View(), "message message")
	model = drag(t, model, column, row, column+20, row)
	if view := model.View(); !strings.Contains(view, "\x1b[7m") {
		t.Fatal("the drag left no highlight to clear")
	}

	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyCtrlL})

	if view := model.View(); strings.Contains(view, "\x1b[7m") {
		t.Fatalf("clearing the viewport kept the highlight:\n%s", view)
	}
	before := len(spy.writes)
	model, _ = model.Update(mouseRelease(column+20, row))
	if len(spy.writes) != before {
		t.Fatalf("releasing a dropped selection copied %q", spy.copied())
	}
}

func TestResizingDropsTheSelection(t *testing.T) {
	model, _ := newSelectionTUI(t, longTranscript()...)

	row, column := locate(t, model.View(), "message message")
	model = drag(t, model, column, row, column+20, row)

	model, _ = model.Update(tea.WindowSizeMsg{Width: selectionWidth, Height: selectionHeight - 2})

	if view := model.View(); strings.Contains(view, "\x1b[7m") {
		t.Fatalf("resizing kept a highlight whose lines were reflowed:\n%s", view)
	}
}

func TestTypingDropsTheSelection(t *testing.T) {
	model, _ := newSelectionTUI(t, tui.Message{Role: tui.RoleAssistant, Content: "alpha bravo charlie"})

	row, column := locate(t, model.View(), "bravo")
	model = drag(t, model, column, row, column+4, row)
	model, _ = model.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'x'}})

	if view := model.View(); strings.Contains(view, "\x1b[7m") {
		t.Fatalf("typing kept the highlight:\n%s", view)
	}
}

func TestDragPastTheEdgeScrollsUnderOneTickChain(t *testing.T) {
	model, _ := newSelectionTUI(t, longTranscript()...)

	row, column := locate(t, model.View(), "message message")
	model, firstTick := model.Update(mousePress(column, row))
	if firstTick == nil {
		t.Fatal("pressing armed no auto-scroll")
	}
	model, _ = model.Update(mouseMotion(column, 0))
	model, _ = model.Update(mouseRelease(column, 0))

	// A second drag must not inherit the first drag's tick: it would scroll at
	// twice the rate.
	model, secondTick := model.Update(mousePress(column, row))
	if secondTick == nil {
		t.Fatal("the second press armed no auto-scroll")
	}
	model, _ = model.Update(mouseMotion(column, 0))

	model, _ = model.Update(firstTick())
	if view := model.View(); !strings.Contains(view, "100%") {
		t.Fatal("a tick from a finished drag scrolled the transcript")
	}

	model, _ = model.Update(secondTick())
	if view := model.View(); strings.Contains(view, "100%") {
		t.Fatal("the drag's own tick did not scroll the transcript")
	}
}

func TestReleasedDragStopsAutoScrolling(t *testing.T) {
	model, _ := newSelectionTUI(t, longTranscript()...)

	row, column := locate(t, model.View(), "message message")
	model, tick := model.Update(mousePress(column, row))
	model, _ = model.Update(mouseMotion(column, 0))
	model, _ = model.Update(mouseRelease(column, 0))

	model, next := model.Update(tick())
	if next != nil {
		t.Fatal("the tick chain kept running after the button was released")
	}
}
