package tui

import (
	"fmt"
	"os"
	"strings"

	"github.com/atotto/clipboard"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/ansi"
)

// clipboardDoneMsg reports the outcome of an asynchronous clipboard write.
type clipboardDoneMsg struct {
	lines int
	err   error
}

func ExtractCodeBlocks(content string) []string {
	var blocks []string
	lines := strings.Split(content, "\n")
	inBlock := false
	var current strings.Builder
	for _, line := range lines {
		if strings.HasPrefix(strings.TrimSpace(line), "```") {
			if inBlock {
				blocks = append(blocks, strings.TrimSuffix(current.String(), "\n"))
				current.Reset()
			}
			inBlock = !inBlock
			continue
		}
		if inBlock {
			current.WriteString(line + "\n")
		}
	}
	return blocks
}

func (a *App) copyLastCodeBlock() tea.Cmd {
	for i := len(a.messages) - 1; i >= 0; i-- {
		blocks := ExtractCodeBlocks(a.messages[i].Content)
		if len(blocks) == 0 {
			continue
		}
		a.err = ""
		return a.copyCommand(blocks[len(blocks)-1])
	}
	a.err = "No code blocks found to copy"
	a.status = ""
	return nil
}

// copyCommand writes text to the clipboard off the update loop: the native
// clipboard tools are child processes, and copying a large block must not
// stall rendering.
func (a App) copyCommand(text string) tea.Cmd {
	if strings.TrimSpace(text) == "" {
		return nil
	}
	write := a.writeClipboard
	if write == nil {
		write = defaultClipboardWrite
	}
	lines := strings.Count(text, "\n") + 1
	return func() tea.Msg {
		return clipboardDoneMsg{lines: lines, err: write(text)}
	}
}

// finishCopy reports the outcome of an asynchronous clipboard write.
func (a App) finishCopy(message clipboardDoneMsg) (tea.Model, tea.Cmd) {
	if message.err != nil {
		a.err = "Failed to copy: " + message.err.Error()
		a.status = ""
		return a, nil
	}
	a.err = ""
	label := "lines"
	if message.lines == 1 {
		label = "line"
	}
	a.status = fmt.Sprintf("Copied %d %s", message.lines, label)
	return a, nil
}

// defaultClipboardWrite prefers a native clipboard tool and falls back to
// OSC 52, which reaches the terminal's own clipboard over SSH and inside tmux
// where no X11 or Wayland clipboard tool exists.
func defaultClipboardWrite(text string) error {
	if !clipboard.Unsupported {
		if err := clipboard.WriteAll(text); err == nil {
			return nil
		}
	}
	_, err := fmt.Fprint(os.Stdout, ansi.SetSystemClipboard(text))
	return err
}

func (a *App) cancelRun(clearQueue bool) {
	if a.pendingTool != nil {
		if err := a.session.Cancel(); err != nil {
			a.err = err.Error()
		}
	}
	if a.cancel != nil {
		a.cancel()
	}
	if clearQueue {
		a.queuedInputs = nil
		a.status = "Turn canceled"
	}
}
