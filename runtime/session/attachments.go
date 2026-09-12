package session

import "errors"

type attachmentReader interface {
	ReadAttachment(string) (Attachment, error)
}

func (s *Session) Attach(path string) (Attachment, error) {
	reader, ok := s.workspace.(attachmentReader)
	if !ok {
		return Attachment{}, errors.New("attachments are unavailable")
	}
	attachment, err := reader.ReadAttachment(path)
	if err != nil {
		return Attachment{}, err
	}
	s.attachmentMu.Lock()
	s.attachments = append(s.attachments, attachment)
	s.attachmentMu.Unlock()
	return attachment, nil
}

func (s *Session) PendingAttachments() []Attachment {
	s.attachmentMu.Lock()
	defer s.attachmentMu.Unlock()
	return append([]Attachment(nil), s.attachments...)
}
