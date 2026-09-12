package app

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"strings"

	"super-agent/runtime"
	"super-agent/tools"
)

type WorkflowController struct {
	registry   *tools.Registry
	extensions Extensions
}

func (c *WorkflowController) GitDiff(ctx context.Context) (string, error) {
	if c == nil || c.registry == nil {
		return "", errors.New("workflow tools are unavailable")
	}
	input, _ := json.Marshal(map[string]any{})
	return c.registry.Run(ctx, runtime.ToolCall{Name: "git_diff", Input: string(input)})
}

func (c *WorkflowController) RunHook(ctx context.Context, event string) error {
	for _, command := range c.extensions.Hooks[event] {
		input, _ := json.Marshal(map[string]any{"command": command})
		if c.registry == nil {
			return errors.New("hooks require tools")
		}
		if _, err := c.registry.RunDirect(ctx, runtime.ToolCall{Name: "run_command", Input: string(input)}); err != nil {
			return err
		}
	}
	return nil
}

func (c *WorkflowController) RunHooks(ctx context.Context, events ...string) error {
	var result error
	for _, event := range events {
		result = errors.Join(result, c.RunHook(ctx, event))
	}
	return result
}

func (c *WorkflowController) CustomCommands() []string {
	names := make([]string, 0, len(c.extensions.Commands))
	for name := range c.extensions.Commands {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
func (c *WorkflowController) Skills() []string { return append([]string(nil), c.extensions.Skills...) }
func (c *WorkflowController) Plugins() []string {
	return append([]string(nil), c.extensions.Plugins...)
}

func (c *WorkflowController) ExpandCommand(name, arguments string) (string, error) {
	template, ok := c.extensions.Commands[name]
	if !ok {
		return "", errors.New("unknown custom command: " + name)
	}
	if strings.Contains(template, "$ARGUMENTS") {
		return strings.ReplaceAll(template, "$ARGUMENTS", arguments), nil
	}
	if strings.TrimSpace(arguments) != "" {
		template += "\n\nArguments: " + arguments
	}
	return template, nil
}

func (c *WorkflowController) GitStatus(ctx context.Context) (string, error) {
	if c == nil || c.registry == nil {
		return "", errors.New("workflow tools are unavailable")
	}
	input, _ := json.Marshal(map[string]any{})
	return c.registry.Run(ctx, runtime.ToolCall{Name: "git_status", Input: string(input)})
}

func (c *WorkflowController) Diagnostics(ctx context.Context, path string) (string, error) {
	if c == nil || c.registry == nil {
		return "", errors.New("workflow tools are unavailable")
	}
	input, _ := json.Marshal(map[string]any{"path": path})
	return c.registry.Run(ctx, runtime.ToolCall{Name: "lsp_diagnostics", Input: string(input)})
}
