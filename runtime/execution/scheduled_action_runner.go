package execution

import "context"

type QueuedAction struct {
	RunID    RunID
	ActionID ActionID
	Action   ScheduledAction
}

type ActionOutcome struct {
	RunID    RunID
	ActionID ActionID
	Result   ExecutionResult
}

type ScheduledActionRunner interface {
	Run(ctx context.Context, action QueuedAction, input ExecutionInput, chunkFunc func(StreamChunk)) (ActionOutcome, error)
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

func (r *DefaultScheduledActionRunner) Run(ctx context.Context, action QueuedAction, input ExecutionInput, chunkFunc func(StreamChunk)) (ActionOutcome, error) {
	result, err := r.executor.Execute(ctx, action.Action, input, chunkFunc)
	if err != nil {
		return ActionOutcome{}, err
	}
	return ActionOutcome{
		RunID:    action.RunID,
		ActionID: action.ActionID,
		Result:   result,
	}, nil
}
