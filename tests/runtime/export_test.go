package runtime_test

import (
	"os"
	"strings"
	"testing"

	. "super-agent/runtime"
	"super-agent/workspace"
)

func TestSessionExportsMarkdownJSONAndLocalHTML(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	messages := []Message{{Role: RoleSystem, Content: "rules"}, {Role: RoleUser, Content: "<hello>"}}
	engine := NewEngineWithExecutor(&staticExecutor{}, messages)
	session := NewPersistentSession(engine, nil, workspace.Workspace{}, SessionMetadata{ID: "session-1", Title: "Demo", Provider: "test", Model: "model", CWD: dir})
	for _, format := range []string{"markdown", "json", "html"} {
		path, err := session.Export(format)
		if err != nil {
			t.Fatalf("Export(%s): %v", format, err)
		}
		content, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if len(content) == 0 {
			t.Fatalf("empty %s export", format)
		}
		if format == "html" && (!strings.Contains(string(content), "&lt;hello&gt;") || strings.Contains(string(content), "<hello>")) {
			t.Fatalf("unsafe HTML export: %s", content)
		}
	}
}
