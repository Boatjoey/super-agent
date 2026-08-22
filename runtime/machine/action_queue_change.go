package machine

type ActionQueueChange interface {
	isActionQueueChange()
}

type ClearActionQueue struct{}

func (ClearActionQueue) isActionQueueChange() {}

var AllActionQueueChanges = []ActionQueueChange{
	ClearActionQueue{},
}
