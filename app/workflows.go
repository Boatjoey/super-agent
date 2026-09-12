package app

import (
	"context"
	"encoding/json"
	"errors"

	"super-agent/runtime"
	"super-agent/tools"
)

type WorkflowController struct{ registry *tools.Registry }

func (c *WorkflowController) GitDiff(ctx context.Context) (string, error) {
	if c == nil || c.registry == nil {
		return "", errors.New("workflow tools are unavailable")
	}
	input, _ := json.Marshal(map[string]any{})
	return c.registry.Run(ctx, runtime.ToolCall{Name: "git_diff", Input: string(input)})
}

func (c *WorkflowController) GitStatus(ctx context.Context) (string, error) {
	if c == nil || c.registry == nil {
		return "", errors.New("workflow tools are unavailable")
	}
	input, _ := json.Marshal(map[string]any{})
	return c.registry.Run(ctx, runtime.ToolCall{Name: "git_status", Input: string(input)})
}
