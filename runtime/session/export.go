package session

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"path"
	"strings"
)

type exportWriter interface {
	WriteExport(string, []byte) (string, error)
}

func (s *Session) Export(format string) (string, error) {
	writer, ok := s.workspace.(exportWriter)
	if !ok {
		return "", errors.New("session export is unavailable")
	}
	format = strings.ToLower(strings.TrimSpace(format))
	if format == "md" {
		format = "markdown"
	}
	meta := s.Metadata()
	messages := s.Snapshot().Messages
	var events []AuditEvent
	if s.repository != nil {
		var err error
		events, err = s.repository.LoadAuditEvents(meta.ID)
		if err != nil {
			return "", err
		}
	}
	var content []byte
	var extension string
	switch format {
	case "markdown":
		content = []byte(markdownExport(meta, messages, events))
		extension = ".md"
	case "json":
		encoded, err := json.MarshalIndent(struct {
			Metadata Metadata     `json:"metadata"`
			Messages []Message    `json:"messages"`
			Events   []AuditEvent `json:"events"`
		}{meta, messages, events}, "", "  ")
		if err != nil {
			return "", err
		}
		content = append(encoded, '\n')
		extension = ".json"
	case "html":
		content = []byte(htmlExport(meta, messages, events))
		extension = ".html"
	default:
		return "", errors.New("export format must be markdown, json, or html")
	}
	return writer.WriteExport(path.Join(".super-agent", "exports", string(meta.ID)+extension), content)
}

func markdownExport(meta Metadata, messages []Message, events []AuditEvent) string {
	var output strings.Builder
	fmt.Fprintf(&output, "# %s\n\n- Session: `%s`\n- Model: `%s/%s`\n- Working directory: `%s`\n\n", meta.Title, meta.ID, meta.Provider, meta.Model, meta.CWD)
	for _, message := range messages {
		fmt.Fprintf(&output, "## %s\n\n%s\n\n", strings.Title(string(message.Role)), message.Content)
	}
	writeMarkdownEvents(&output, events)
	return output.String()
}

func writeMarkdownEvents(output *strings.Builder, events []AuditEvent) {
	if len(events) == 0 {
		return
	}
	output.WriteString("## Audit events\n\n")
	for _, event := range events {
		fmt.Fprintf(output, "- `%s` %s", event.Type, event.Time.Format("2006-01-02T15:04:05Z07:00"))
		if event.ToolCall != nil {
			fmt.Fprintf(output, " tool=`%s`", event.ToolCall.Name)
		}
		if event.Decision != "" {
			fmt.Fprintf(output, " decision=`%s`", event.Decision)
		}
		if event.Error != "" {
			fmt.Fprintf(output, " error=%s", event.Error)
		}
		if event.Result != "" {
			fmt.Fprintf(output, " result=%s", event.Result)
		}
		output.WriteString("\n")
	}
}

func htmlExport(meta Metadata, messages []Message, events []AuditEvent) string {
	var body strings.Builder
	for _, message := range messages {
		fmt.Fprintf(&body, "<section><h2>%s</h2><pre>%s</pre></section>", html.EscapeString(string(message.Role)), html.EscapeString(message.Content))
	}
	if len(events) > 0 {
		body.WriteString("<section><h2>Audit events</h2><ul>")
		for _, event := range events {
			detail := event.Decision + event.Error + event.Result
			if event.ToolCall != nil {
				detail = event.ToolCall.Name + " " + detail
			}
			fmt.Fprintf(&body, "<li><code>%s</code> %s</li>", html.EscapeString(event.Type), html.EscapeString(strings.TrimSpace(detail)))
		}
		body.WriteString("</ul></section>")
	}
	return "<!doctype html><meta charset=\"utf-8\"><title>" + html.EscapeString(meta.Title) + "</title><style>body{max-width:900px;margin:40px auto;font:16px system-ui}pre{white-space:pre-wrap;background:#f5f5f5;padding:16px;border-radius:8px}</style><h1>" + html.EscapeString(meta.Title) + "</h1>" + body.String()
}
