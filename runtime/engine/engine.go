package engine

import (
	"sync"

	"super-agent/runtime/execution"
	"super-agent/runtime/machine"
	"super-agent/runtime/protocol"
)

type Engine struct {
	mu                       sync.Mutex
	runner                   execution.ScheduledActionRunner
	resolver                 execution.ActionResultResolver
	runtimeDataChangeApplier machine.RuntimeDataChangeApplier
	runs                     execution.RunController
	approvals                execution.ApprovalStore
	runtimeData              machine.RuntimeData
	actionQueue              *execution.ActionQueue

	// stateObserver is notified after state-changing transitions while
	// actions drain. It runs outside the engine lock so it can read
	// snapshots. session.RunTurn installs a per-turn observer.
	stateObserver func()
}

type policySetter interface {
	SetPolicy(execution.Policy)
}

type policyStore interface {
	SetPermissionPolicy(execution.PermissionMode, execution.PermissionRules)
}

type policySnapshot interface {
	Mode() execution.PermissionMode
	Rules() execution.PermissionRules
}

func NewEngine(model protocol.Model, tools protocol.ToolRunner, initial []protocol.Message) *Engine {
	return NewEngineWithExecutor(execution.NewDefaultScheduledActionExecutor(model, tools), initial)
}

func NewEngineWithExecutor(executor execution.ScheduledActionExecutor, initial []protocol.Message) *Engine {
	approvals := execution.NewMemoryApprovalStore()
	policy := execution.NewDefaultPolicy()
	approvals.SetPermissionPolicy(policy.Mode(), policy.Rules())
	return NewEngineWithComponents(
		execution.NewDefaultScheduledActionRunner(executor),
		execution.NewDefaultActionResultResolver(policy, approvals),
		machine.DefaultRuntimeDataChangeApplier{},
		execution.NewDefaultRunController(),
		approvals,
		initial,
	)
}

func NewEngineWithExecutorAndPolicy(executor execution.ScheduledActionExecutor, policy execution.Policy, initial []protocol.Message) *Engine {
	approvals := execution.NewMemoryApprovalStore()
	if snapshot, ok := policy.(policySnapshot); ok {
		approvals.SetPermissionPolicy(snapshot.Mode(), snapshot.Rules())
	}
	return NewEngineWithComponents(execution.NewDefaultScheduledActionRunner(executor), execution.NewDefaultActionResultResolver(policy, approvals), machine.DefaultRuntimeDataChangeApplier{}, execution.NewDefaultRunController(), approvals, initial)
}

func NewEngineWithComponents(runner execution.ScheduledActionRunner, resolver execution.ActionResultResolver, runtimeDataChangeApplier machine.RuntimeDataChangeApplier, runs execution.RunController, approvals execution.ApprovalStore, initial []protocol.Message) *Engine {
	messages := append([]protocol.Message(nil), initial...)
	return &Engine{
		runner:                   runner,
		resolver:                 resolver,
		runtimeDataChangeApplier: runtimeDataChangeApplier,
		runs:                     runs,
		approvals:                approvals,
		actionQueue:              execution.NewActionQueue(),
		runtimeData: machine.RuntimeData{
			State:    machine.StateInitializing,
			Messages: messages,
		},
	}
}

// SetStateObserver registers a callback fired after state-changing
// transitions while actions drain. The callback runs outside the engine
// lock so it can read snapshots.
func (e *Engine) SetStateObserver(observer func()) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.stateObserver = observer
}

func (e *Engine) notifyStateObserver() {
	e.mu.Lock()
	observer := e.stateObserver
	e.mu.Unlock()
	if observer != nil {
		observer()
	}
}
