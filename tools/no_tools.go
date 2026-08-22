package tools

import (
	"context"
	"errors"

	"super-agent/runtime/protocol"
)

type NoTools struct{}

func (NoTools) Specs() []protocol.ToolSpec {
	return nil
}

func (NoTools) Run(context.Context, protocol.ToolCall) (string, error) {
	return "", errors.New("tools are disabled")
}
