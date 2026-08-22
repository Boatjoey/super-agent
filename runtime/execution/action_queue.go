package execution

import "strconv"

type ActionQueue struct {
	queue []QueuedAction
	next  int64
}

func NewActionQueue() *ActionQueue {
	return &ActionQueue{}
}

func (s *ActionQueue) Queue(runID RunID, action ScheduledAction) QueuedAction {
	s.next++
	queued := QueuedAction{
		RunID:    runID,
		ActionID: ActionID("action-" + strconv.FormatInt(s.next, 10)),
		Action:   action,
	}
	s.queue = append(s.queue, queued)
	return queued
}

func (s *ActionQueue) Pop() (QueuedAction, bool) {
	if len(s.queue) == 0 {
		return QueuedAction{}, false
	}
	action := s.queue[0]
	s.queue = s.queue[1:]
	return action, true
}

func (s *ActionQueue) Clear() {
	s.queue = nil
}

func (s *ActionQueue) Len() int {
	return len(s.queue)
}
