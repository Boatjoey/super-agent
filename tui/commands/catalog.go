package commands

import (
	"sort"
	"strings"
)

// Command is one palette entry: the name the composer completes and the hint it
// displays.
type Command struct {
	Name        string
	Description string
}

var slashCommands = []string{
	"/clear", "/compact", "/delete-session", "/help", "/instructions", "/permissions",
	"/mcp", "/quit", "/rename", "/reset", "/resume", "/sessions", "/undo", "/agent", "/build", "/plan", "/mode", "/fork", "/memory", "/remember", "/forget", "/review", "/diff", "/fix-ci", "/branch", "/commit-message", "/export", "/share", "/attach", "/attachments", "/commands", "/skills", "/plugins", "/diagnostics",
}

var slashCommandDescriptions = map[string]string{
	"/clear":          "Reset the conversation",
	"/agent":          "List or select an agent <name>",
	"/attach":         "Attach a workspace file <path>",
	"/attachments":    "List pending attachments",
	"/build":          "Switch to the build agent",
	"/branch":         "Show branch and working-tree status",
	"/commit-message": "Suggest a commit message",
	"/commands":       "List custom commands",
	"/compact":        "Compact context [summary]",
	"/delete-session": "Delete a saved session <id>",
	"/diff":           "Preview the current patch",
	"/diagnostics":    "Show LSP diagnostics <path>",
	"/export":         "Export session <markdown|json>",
	"/fix-ci":         "Inspect and fix failing CI checks",
	"/help":           "Show commands and shortcuts",
	"/fork":           "Fork the current transcript [title]",
	"/forget":         "Clear cross-session memory",
	"/instructions":   "Show loaded instruction files",
	"/mcp":            "Manage MCP servers <list|add|remove|restart>",
	"/mode":           "Switch mode <plan|build>",
	"/memory":         "Show cross-session memory",
	"/permissions":    "Inspect or change permission mode",
	"/plugins":        "List loaded plugins",
	"/plan":           "Switch to the plan agent",
	"/quit":           "Exit Super Agent",
	"/rename":         "Rename a session <id> <title>",
	"/remember":       "Add cross-session memory <text>",
	"/reset":          "Reset the conversation",
	"/review":         "Review the current changes",
	"/resume":         "Resume a saved session <id>",
	"/sessions":       "List saved sessions",
	"/share":          "Create a local HTML share file",
	"/skills":         "List loaded skills",
	"/undo":           "Restore the last checkpoint",
}

// IsCommand reports whether submitted text is a slash command rather than a
// prompt. It is a pure predicate so callers can route input without holding any
// command state.
func IsCommand(text string) bool { return strings.HasPrefix(text, "/") }

// Palette lists the built-in commands followed by the discovered custom
// commands, in the order the composer should offer them.
func (m Model) Palette() []Command {
	commands := make([]Command, 0, len(slashCommands)+len(m.customCommands))
	for _, name := range slashCommands {
		commands = append(commands, Command{Name: name, Description: slashCommandDescriptions[name]})
	}
	custom := append([]string(nil), m.customCommands...)
	sort.Strings(custom)
	for _, name := range custom {
		commands = append(commands, Command{Name: "/" + strings.TrimPrefix(name, "/"), Description: "Custom command"})
	}
	return commands
}
