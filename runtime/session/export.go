package session

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"path/filepath"
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
	var content []byte
	var extension string
	switch format {
	case "markdown":
		content = []byte(markdownExport(meta, messages))
		extension = ".md"
	case "json":
		encoded, err := json.MarshalIndent(struct {
			Metadata Metadata  `json:"metadata"`
			Messages []Message `json:"messages"`
		}{meta, messages}, "", "  ")
		if err != nil {
			return "", err
		}
		content = append(encoded, '\n')
		extension = ".json"
	case "html":
		content = []byte(htmlExport(meta, messages))
		extension = ".html"
	default:
		return "", errors.New("export format must be markdown, json, or html")
	}
	return writer.WriteExport(filepath.Join(".super-agent", "exports", string(meta.ID)+extension), content)
}

func markdownExport(meta Metadata, messages []Message) string {
	var output strings.Builder
	fmt.Fprintf(&output, "# %s\n\n- Session: `%s`\n- Model: `%s/%s`\n- Working directory: `%s`\n\n", meta.Title, meta.ID, meta.Provider, meta.Model, meta.CWD)
	for _, message := range messages {
		fmt.Fprintf(&output, "## %s\n\n%s\n\n", strings.Title(string(message.Role)), message.Content)
	}
	return output.String()
}

func htmlExport(meta Metadata, messages []Message) string {
	var body strings.Builder
	for _, message := range messages {
		fmt.Fprintf(&body, "<section><h2>%s</h2><pre>%s</pre></section>", html.EscapeString(string(message.Role)), html.EscapeString(message.Content))
	}
	return "<!doctype html><meta charset=\"utf-8\"><title>" + html.EscapeString(meta.Title) + "</title><style>body{max-width:900px;margin:40px auto;font:16px system-ui}pre{white-space:pre-wrap;background:#f5f5f5;padding:16px;border-radius:8px}</style><h1>" + html.EscapeString(meta.Title) + "</h1>" + body.String()
}
