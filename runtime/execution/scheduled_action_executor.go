package execution

import (
	"context"
	"errors"
)

type ScheduledActionInput struct {
	Messages  []Message
	ToolSpecs []ToolSpec
}

type ScheduledActionExecutor interface {
	Execute(ctx context.Context, action ScheduledAction, env ScheduledActionInput, chunkFunc func(StreamChunk)) (ScheduledActionResult, error)
}

type DefaultScheduledActionExecutor struct {
	model Model
	tools ToolRunner
}

func NewDefaultScheduledActionExecutor(model Model, tools ToolRunner) *DefaultScheduledActionExecutor {
	return &DefaultScheduledActionExecutor{model: model, tools: tools}
}

func (x *DefaultScheduledActionExecutor) ToolSpecs() []ToolSpec {
	return x.tools.Specs()
}

func (x *DefaultScheduledActionExecutor) Execute(ctx context.Context, action ScheduledAction, env ScheduledActionInput, chunkFunc func(StreamChunk)) (ScheduledActionResult, error) {
	switch fx := action.(type) {
	case CallModel:
		resp, err := x.model.Next(ctx, env.Messages, env.ToolSpecs, chunkFunc)
		if err != nil {
			return nil, err
		}
		return ModelReplied{Response: resp}, nil
	case RunTool:
		result, err := x.tools.Run(ctx, fx.Call)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return nil, err
			}
			return ToolFinished{Call: fx.Call, Result: "Error: " + err.Error()}, nil
		}
		return ToolFinished{Call: fx.Call, Result: result}, nil
	case CheckToolQueue:
		return ToolQueueChecked{}, nil
	default:
		return nil, errors.New("unknown action")
	}
}
