package machine

type ScheduledAction interface {
	isScheduledAction()
}

type CallModel struct{}

func (CallModel) isScheduledAction() {}

type RunTool struct {
	Call ToolCall
}

func (RunTool) isScheduledAction() {}

type CheckToolQueue struct{}

func (CheckToolQueue) isScheduledAction() {}

type AwaitApproval struct {
	Call    ToolCall
	Request PermissionRequest
}

func (AwaitApproval) isScheduledAction() {}

// AllScheduledActions lists every ScheduledAction type for registration, serialization, and testing.
var AllScheduledActions = []ScheduledAction{
	CallModel{},
	RunTool{},
	CheckToolQueue{},
	AwaitApproval{},
}
