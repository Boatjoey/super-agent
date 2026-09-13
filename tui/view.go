package tui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

func (a App) helpView() string {
	helpStyle := lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("6")).Padding(1, 2).Width(max(20, min(64, a.width-4)))
	title := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("6")).Render("Commands & Shortcuts")
	items := []string{
		a.styles.CommandLabel.Render("/agent") + "    Select agent profile",
		a.styles.CommandLabel.Render("/attach") + "   Queue image or file",
		a.styles.CommandLabel.Render("/clear") + "    Reset conversation",
		a.styles.CommandLabel.Render("/sessions") + " List saved sessions",
		a.styles.CommandLabel.Render("/resume") + "   Resume saved session",
		a.styles.CommandLabel.Render("/compact") + "  Compact context",
		a.styles.CommandLabel.Render("/undo") + "     Restore checkpoint",
		a.styles.CommandLabel.Render("/permissions") + " Show permission policy",
		a.styles.CommandLabel.Render("/mcp") + "      Manage MCP servers",
		a.styles.CommandLabel.Render("/review") + "   Review current changes",
		a.styles.CommandLabel.Render("/export") + "   Export or share session",
		a.styles.CommandLabel.Render("/help") + "     Show this menu",
		a.styles.CommandLabel.Render("/quit") + "     Exit application",
		"", "enter        Submit / steer active turn", "tab          Queue while running", "ctrl+j       Insert newline", "up/down      History / move lines",
		"tab          Complete slash command", "up/down      Select slash command", "esc/ctrl+u   Clear input / Cancel", "ctrl+l       Clear screen", "ctrl+y       Copy last code block", "ctrl+o       Toggle latest tools", "alt+o        Toggle all tools", "ctrl+t       Toggle latest reasoning", "alt+t        Toggle all reasoning", "ctrl+c       Quit / Cancel", "?            Toggle help",
		"", "Tool Approval:", "up/down      Select decision", "enter        Confirm decision", "1/y          Approve once", "2/a          Always allow", "3/n          Deny call",
	}
	return helpStyle.Render(title + "\n\n" + strings.Join(items, "\n"))
}

// clampLines truncates every line of block to at most width columns so the
// terminal never hard-wraps it. Truncation is ANSI- and width-aware.
func clampLines(width int, block string) string {
	return lipgloss.NewStyle().MaxWidth(max(1, width)).Render(block)
}

func (a App) View() string {
	if !a.ready {
		return "\n  Initializing..."
	}
	if a.showHelp {
		return fitDynamicArea(a.width, a.height, a.helpView())
	}
	parts := make([]string, 0, 3)
	if content := a.transcript.View(); content != "" {
		parts = append(parts, content)
	}
	parts = append(parts, a.footerView())
	return fitDynamicArea(a.width, a.height, strings.Join(parts, "\n\n"))
}

func fitDynamicArea(width, height int, content string) string {
	content = clampLines(width, content)
	lines := strings.Split(content, "\n")
	if height > 0 && len(lines) > height {
		lines = lines[len(lines)-height:]
	}
	return strings.Join(lines, "\n")
}
