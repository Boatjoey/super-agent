package machine

type State string

const (
	StateInitializing    State = "Initializing"
	StateIdle            State = "Idle"
	StateWaitingLLM      State = "WaitingLLM"
	StateWaitingApproval State = "WaitingApproval"
	StateRunningTool     State = "RunningTool"
	StateAdvancingQueue  State = "AdvancingQueue"
)
