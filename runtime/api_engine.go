package runtime

import "super-agent/runtime/engine"

type Engine = engine.Engine

func NewEngine(model Model, tools ToolRunner, initial []Message) *Engine {
	return engine.NewEngine(model, tools, initial)
}
func NewEngineWithExecutor(executor ScheduledActionExecutor, initial []Message) *Engine {
	return engine.NewEngineWithExecutor(executor, initial)
}
func NewEngineWithExecutorAndPolicy(executor ScheduledActionExecutor, policy Policy, initial []Message) *Engine {
	return engine.NewEngineWithExecutorAndPolicy(executor, policy, initial)
}
func NewEngineWithComponents(runner ScheduledActionRunner, resolver ActionResultResolver, stateChangeApplier StateChangeApplier, runs RunController, approvals ApprovalStore, initial []Message) *Engine {
	return engine.NewEngineWithComponents(runner, resolver, stateChangeApplier, runs, approvals, initial)
}
