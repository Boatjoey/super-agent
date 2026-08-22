package execution

type ScheduledActionResult interface {
	isScheduledActionResult()
}

type ModelReplied struct {
	Response ModelResponse
}

func (ModelReplied) isScheduledActionResult() {}

type ToolFinished struct {
	Call   ToolCall
	Result string
}

func (ToolFinished) isScheduledActionResult() {}

type ToolQueueChecked struct{}

func (ToolQueueChecked) isScheduledActionResult() {}
