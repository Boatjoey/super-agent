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

type ProcessNextToolCall struct{}

func (ProcessNextToolCall) isScheduledAction() {}

// AllScheduledActions lists every ScheduledAction type for registration, serialization, and testing.
var AllScheduledActions = []ScheduledAction{
	CallModel{},
	RunTool{},
	ProcessNextToolCall{},
}
