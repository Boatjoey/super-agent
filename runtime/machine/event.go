package machine

// this file lists all event, which must have isEvent() method
type Event interface {
	isEvent()
	kind() eventKind
}

type eventKind string

const (
	eventUserMessageSubmitted     eventKind = "UserMessageSubmitted"
	eventAssistantMessageReceived eventKind = "AssistantMessageReceived"
	eventToolBatchReceived        eventKind = "ToolBatchReceived"
	eventToolCallNeedsApproval    eventKind = "ToolCallNeedsApproval"
	eventToolCallReadyToRun       eventKind = "ToolCallReadyToRun"
	eventToolCallDenied           eventKind = "ToolCallDenied"
	eventToolBatchFinished        eventKind = "ToolBatchFinished"
	eventToolResultReceived       eventKind = "ToolResultReceived"
	eventApprovalGranted          eventKind = "ApprovalGranted"
	eventApprovalAlwaysGranted    eventKind = "ApprovalAlwaysGranted"
	eventApprovalDenied           eventKind = "ApprovalDenied"
	eventErrorOccurred            eventKind = "ErrorOccurred"
	eventCancelRequested          eventKind = "CancelRequested"
	eventResetRequested           eventKind = "ResetRequested"
	eventEngineReady              eventKind = "EngineReady"
)

type UserMessageSubmitted struct {
	Content     string
	Attachments []Attachment
}

func (UserMessageSubmitted) isEvent()        {}
func (UserMessageSubmitted) kind() eventKind { return eventUserMessageSubmitted }

type AssistantMessageReceived struct {
	Response ModelResponse
}

func (AssistantMessageReceived) isEvent()        {}
func (AssistantMessageReceived) kind() eventKind { return eventAssistantMessageReceived }

type ToolBatchReceived struct {
	Content          string
	Calls            []ToolCall
	ReasoningContent string
}

func (ToolBatchReceived) isEvent()        {}
func (ToolBatchReceived) kind() eventKind { return eventToolBatchReceived }

type ToolCallNeedsApproval struct {
	Call    ToolCall
	Request PermissionRequest
}

func (ToolCallNeedsApproval) isEvent()        {}
func (ToolCallNeedsApproval) kind() eventKind { return eventToolCallNeedsApproval }

type ToolCallReadyToRun struct {
	Call ToolCall
}

func (ToolCallReadyToRun) isEvent()        {}
func (ToolCallReadyToRun) kind() eventKind { return eventToolCallReadyToRun }

type ToolCallDenied struct {
	Call   ToolCall
	Reason string
}

func (ToolCallDenied) isEvent()        {}
func (ToolCallDenied) kind() eventKind { return eventToolCallDenied }

type ToolBatchFinished struct{}

func (ToolBatchFinished) isEvent()        {}
func (ToolBatchFinished) kind() eventKind { return eventToolBatchFinished }

type ToolResultReceived struct {
	Call   ToolCall
	Result string
}

func (ToolResultReceived) isEvent()        {}
func (ToolResultReceived) kind() eventKind { return eventToolResultReceived }

type ApprovalGranted struct {
	Call ToolCall
}

func (ApprovalGranted) isEvent()        {}
func (ApprovalGranted) kind() eventKind { return eventApprovalGranted }

type ApprovalAlwaysGranted struct {
	Call ToolCall
}

func (ApprovalAlwaysGranted) isEvent()        {}
func (ApprovalAlwaysGranted) kind() eventKind { return eventApprovalAlwaysGranted }

type ApprovalDenied struct {
	Call ToolCall
}

func (ApprovalDenied) isEvent()        {}
func (ApprovalDenied) kind() eventKind { return eventApprovalDenied }

type ErrorOccurred struct {
	Err error
}

func (ErrorOccurred) isEvent()        {}
func (ErrorOccurred) kind() eventKind { return eventErrorOccurred }

type CancelRequested struct{}

func (CancelRequested) isEvent()        {}
func (CancelRequested) kind() eventKind { return eventCancelRequested }

type ResetRequested struct{}

func (ResetRequested) isEvent()        {}
func (ResetRequested) kind() eventKind { return eventResetRequested }

type EngineReady struct{}

func (EngineReady) isEvent()        {}
func (EngineReady) kind() eventKind { return eventEngineReady }

// AllEvents lists every Event type for registration, serialization, and testing.
var AllEvents = []Event{
	UserMessageSubmitted{},
	AssistantMessageReceived{},
	ToolBatchReceived{},
	ToolCallNeedsApproval{},
	ToolCallReadyToRun{},
	ToolCallDenied{},
	ToolBatchFinished{},
	ToolResultReceived{},
	ApprovalGranted{},
	ApprovalAlwaysGranted{},
	ApprovalDenied{},
	ErrorOccurred{},
	CancelRequested{},
	ResetRequested{},
	EngineReady{},
}
