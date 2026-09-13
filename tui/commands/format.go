package commands

import (
	"fmt"
	"strings"
)

func divider(label string) string { return "── " + label + " ──" }

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

// formatPermissions reports the runtime's own policy values so the display
// cannot drift from actual behavior.
func formatPermissions(config Config, mode string, autoApprove bool) string {
	if mode == "" {
		mode = "ask"
	}
	return fmt.Sprintf("Permission mode: %s\nTools: %s\nApproval: %s\nCWD: %s", mode, onOff(!config.NoTools), onOff(autoApprove), config.CWD)
}

func formatNamedItems(label string, items []string) string {
	if len(items) == 0 {
		return "No " + strings.ToLower(label)
	}
	return label + ":\n- " + strings.Join(items, "\n- ")
}

func onOff(enabled bool) string {
	if enabled {
		return "on"
	}
	return "off"
}
