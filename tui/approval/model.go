package approval

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type Decision string

const (
	ApproveOnce   Decision = "once"
	ApproveAlways Decision = "always"
	Deny          Decision = "deny"
)

type Request struct {
	ToolName     string
	Input        string
	CommandClass string
	CWD          string
	TouchedPaths []string
	Reason       string
	BatchIndex   int
	BatchTotal   int
}

type Model struct {
	request   *Request
	selection int
	submitted bool
}

func (m Model) Active() bool { return m.request != nil }

func (m *Model) Open(request Request) {
	m.request = &request
	m.selection = 0
	m.submitted = false
}

func (m *Model) Clear() {
	m.request = nil
	m.selection = 0
	m.submitted = false
}

func (m Model) Update(message tea.KeyMsg) (Model, Decision, bool) {
	if m.request == nil || m.submitted {
		return m, "", false
	}
	var decision Decision
	switch strings.ToLower(message.String()) {
	case "up", "k":
		if m.selection > 0 {
			m.selection--
		}
		return m, "", false
	case "down", "j":
		if m.selection < 2 {
			m.selection++
		}
		return m, "", false
	case "enter":
		decision = []Decision{ApproveOnce, ApproveAlways, Deny}[m.selection]
	case "1", "y":
		decision = ApproveOnce
	case "2", "a":
		decision = ApproveAlways
	case "3", "n":
		decision = Deny
	default:
		return m, "", false
	}
	m.submitted = true
	return m, decision, true
}

func (m Model) View(fallbackCWD string) string {
	if m.request == nil {
		return ""
	}
	request := m.request
	prompt := lipgloss.NewStyle().Background(lipgloss.Color("3")).Foreground(lipgloss.Color("0")).Padding(0, 1).Render(" ACTION REQUIRED ")
	progress := ""
	if request.BatchTotal > 0 {
		progress = fmt.Sprintf(" tool %d/%d:", request.BatchIndex, request.BatchTotal)
	}
	lines := []string{prompt + progress + " approve " + lipgloss.NewStyle().Bold(true).Render(request.ToolName) + "?"}
	footer := lipgloss.NewStyle().Foreground(lipgloss.Color("8")).Italic(true)
	selected := lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	for index, option := range []string{"1. Yes, run once", "2. Yes, always allow", "3. No, deny"} {
		prefix, style := "  ", footer
		if index == m.selection {
			prefix, style = "› ", selected
		}
		lines = append(lines, style.Render(prefix+option))
	}
	if m.submitted {
		lines = append(lines, lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Italic(true).Render(" Decision submitted…"))
	}
	if request.CommandClass != "" || request.Reason != "" {
		cwd := request.CWD
		if cwd == "" {
			cwd = fallbackCWD
		}
		meta := fmt.Sprintf(" class: %s cwd: %s", request.CommandClass, cwd)
		if len(request.TouchedPaths) > 0 {
			meta += " paths: " + strings.Join(request.TouchedPaths, ",")
		}
		if request.Reason != "" {
			meta += " reason: " + request.Reason
		}
		lines = append(lines, footer.Render(meta))
	} else if request.Input != "" {
		input := request.Input
		if len(input) > 240 {
			input = input[:240] + "..."
		}
		lines = append(lines, footer.Render(" cwd: "+fallbackCWD+" input: "+input))
	}
	return strings.Join(lines, "\n")
}
