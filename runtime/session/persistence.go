package session

func (s *Session) persistTurnBoundary() {
	if s.repository != nil {
		_ = s.repository.AssignNewTurnID(s.metaID())
	}
}

func (s *Session) persistMessage(message Message) {
	if s.repository != nil {
		_ = s.repository.SaveMessage(s.metaID(), message)
	}
}

func (s *Session) persistApproval(decision ApprovalDecision, call ToolCall) {
	if s.repository == nil {
		return
	}
	_ = s.repository.SaveApproval(s.metaID(), decision, &call)
}

func (s *Session) persistError(err error) {
	if s.repository != nil && err != nil {
		_ = s.repository.SaveError(s.metaID(), err)
	}
}
