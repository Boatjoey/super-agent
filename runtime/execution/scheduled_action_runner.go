package execution

import "context"

type QueuedAction struct {
	RunID    RunID
	ActionID ActionID
	Action   ScheduledAction
}

type ActionCompletion struct {
	RunID    RunID
	ActionID ActionID
	Result   ScheduledActionResult
}

type ScheduledActionRunner interface {
	Run(ctx context.Context, action QueuedAction, input ScheduledActionInput, chunkFunc func(StreamChunk)) (ActionCompletion, error)
	ToolSpecs() []ToolSpec
}

type DefaultScheduledActionRunner struct {
	executor ScheduledActionExecutor
}

func NewDefaultScheduledActionRunner(executor ScheduledActionExecutor) *DefaultScheduledActionRunner {
	return &DefaultScheduledActionRunner{executor: executor}
}

func (r *DefaultScheduledActionRunner) ToolSpecs() []ToolSpec {
	if provider, ok := r.executor.(interface{ ToolSpecs() []ToolSpec }); ok {
		return provider.ToolSpecs()
	}
	return nil
}

func (r *DefaultScheduledActionRunner) Run(ctx context.Context, action QueuedAction, input ScheduledActionInput, chunkFunc func(StreamChunk)) (ActionCompletion, error) {
	result, err := r.executor.Execute(ctx, action.Action, input, chunkFunc)
	if err != nil {
		return ActionCompletion{}, err
	}
	return ActionCompletion{
		RunID:    action.RunID,
		ActionID: action.ActionID,
		Result:   result,
	}, nil
}
