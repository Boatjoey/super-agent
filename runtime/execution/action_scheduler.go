package execution

import "strconv"

type ActionScheduler struct {
	queue []QueuedAction
	next  int64
}

func NewActionScheduler() *ActionScheduler {
	return &ActionScheduler{}
}

func (s *ActionScheduler) Queue(runID RunID, action ScheduledAction) QueuedAction {
	s.next++
	queued := QueuedAction{
		RunID:    runID,
		ActionID: ActionID("action-" + strconv.FormatInt(s.next, 10)),
		Action:   action,
	}
	s.queue = append(s.queue, queued)
	return queued
}

func (s *ActionScheduler) Pop() (QueuedAction, bool) {
	if len(s.queue) == 0 {
		return QueuedAction{}, false
	}
	action := s.queue[0]
	s.queue = s.queue[1:]
	return action, true
}

func (s *ActionScheduler) Clear() {
	s.queue = nil
}

func (s *ActionScheduler) Len() int {
	return len(s.queue)
}
