package tui

import (
	"fmt"
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
		"", "enter        Submit / steer active turn", "tab          Queue while running", "ctrl+j       Insert newline", "up/down      History / move lines", "pgup/pgdn    Scroll history",
		"tab          Complete slash command", "up/down      Select slash command", "esc/ctrl+u   Clear input / Cancel", "ctrl+l       Clear viewport", "ctrl+y       Copy last code block", "ctrl+c       Quit / Cancel", "?            Toggle help",
		"", "Tool Approval:", "up/down      Select decision", "enter        Confirm decision", "1/y          Approve once", "2/a          Always allow", "3/n          Deny call",
	}
	return helpStyle.Render(title + "\n\n" + strings.Join(items, "\n"))
}

func formatSessions(summaries []SessionSummary) string {
	if len(summaries) == 0 {
		return "No saved sessions"
	}
	lines := make([]string, 0, len(summaries))
	for _, summary := range summaries {
		parent := ""
		if summary.ParentID != "" {
			parent = "  child-of:" + summary.ParentID
		}
		lines = append(lines, fmt.Sprintf("%s  %s  %s/%s%s", summary.ID, summary.Title, summary.Provider, summary.Model, parent))
	}
	return strings.Join(lines, "\n")
}

func formatMCPServers(servers []MCPServerSummary) string {
	if len(servers) == 0 {
		return "No MCP servers"
	}
	lines := make([]string, 0, len(servers))
	for _, server := range servers {
		tools := strings.Join(server.Tools, ", ")
		if tools == "" {
			tools = "no tools"
		}
		lines = append(lines, fmt.Sprintf("%s  %s", server.Name, tools))
	}
	return strings.Join(lines, "\n")
}

func formatInstructions(paths []string) string {
	if len(paths) == 0 {
		return "No instruction files loaded"
	}
	var result strings.Builder
	result.WriteString("Loaded instruction sources:\n")
	for _, path := range paths {
		result.WriteString("- ")
		result.WriteString(path)
		result.WriteByte('\n')
	}
	return strings.TrimSpace(result.String())
}

func formatPermissions(info StartupInfo) string {
	mode := firstNonEmpty(info.PermissionMode, "ask")
	return fmt.Sprintf("Permission mode: %s\nTools: %s\nApproval: %s\nCWD: %s", mode, onOff(!info.NoTools), onOff(info.AutoApprove), info.CWD)
}

func onOff(enabled bool) string {
	if enabled {
		return "on"
	}
	return "off"
}
func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

// clampLines truncates every line of block to at most width columns so the
// terminal never hard-wraps it. Truncation is ANSI- and width-aware.
func clampLines(width int, block string) string {
	return lipgloss.NewStyle().MaxWidth(max(1, width)).Render(block)
}

// viewportHeightFor is the shared vertical budget for the scrollable viewport:
// terminal height minus the clamped header/footer, floored so the bordered
// viewport keeps at least one content row.
func (a App) viewportHeightFor(headerHeight, footerHeight int) int {
	minHeight := a.styles.ViewportBorder.GetVerticalFrameSize() + 1
	return max(minHeight, a.height-headerHeight-footerHeight)
}

func (a App) View() string {
	if !a.ready {
		return "\n  Initializing..."
	}
	header, footer := a.headerView(), a.footerView()
	a.viewport.Height = a.viewportHeightFor(lipgloss.Height(header), lipgloss.Height(footer))
	main := lipgloss.JoinVertical(lipgloss.Left, header, a.viewport.View(), footer)
	if !a.showHelp {
		return main
	}
	help := clampLines(a.width, a.helpView())
	return lipgloss.Place(a.width, a.height, lipgloss.Center, lipgloss.Center, help, lipgloss.WithWhitespaceChars(" "), lipgloss.WithWhitespaceForeground(lipgloss.Color("8")))
}
