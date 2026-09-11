package tools_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"super-agent/runtime"
	. "super-agent/tools"
)

// maxOutputBytes is the ceiling run_command applies to a model-supplied
// max_output_bytes, mirrored here because the constant is unexported.
const maxOutputBytes = 200000

func TestReadFileRejectsSymlinkEscape(t *testing.T) {
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret.txt"), []byte("top secret"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Chdir(t.TempDir())
	if err := os.Symlink(outside, "link"); err != nil {
		t.Fatal(err)
	}

	// A lexical containment check accepts "link/secret.txt" because the relative
	// path contains no "..". Resolving the symlink first is what rejects it.
	_, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "read_file",
		Input: `{"path":"link/secret.txt"}`,
	})
	if err == nil || !strings.Contains(err.Error(), "outside working directory") {
		t.Fatalf("err = %v, want outside working directory", err)
	}
}

func TestWriteFileRejectsSymlinkEscape(t *testing.T) {
	outside := t.TempDir()
	t.Chdir(t.TempDir())
	if err := os.Symlink(outside, "link"); err != nil {
		t.Fatal(err)
	}

	_, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "write_file",
		Input: `{"path":"link/planted.txt","content":"owned"}`,
	})
	if err == nil || !strings.Contains(err.Error(), "outside working directory") {
		t.Fatalf("err = %v, want outside working directory", err)
	}
	if _, statErr := os.Stat(filepath.Join(outside, "planted.txt")); statErr == nil {
		t.Fatal("write escaped the workspace through the symlink")
	}
}

func TestRunCommandCapsRequestedOutputLimit(t *testing.T) {
	t.Chdir(t.TempDir())

	// The model asks for a 100 MB limit. Without a ceiling the command's entire
	// output is buffered in memory.
	got, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "run_command",
		Input: `{"command":"head -c 400000 /dev/zero | tr '\\0' 'a'","max_output_bytes":100000000}`,
	})
	if err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	if len(got) > maxOutputBytes+len("\n... truncated") {
		t.Fatalf("output length = %d, want at most %d", len(got), maxOutputBytes)
	}
	if !strings.Contains(got, "truncated") {
		t.Fatalf("result does not report truncation")
	}
}

func TestBashTruncatesOutput(t *testing.T) {
	t.Chdir(t.TempDir())

	got, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "bash",
		Input: `{"command":"head -c 400000 /dev/zero | tr '\\0' 'a'"}`,
	})
	if err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	if len(got) > maxOutputBytes+len("\n... truncated") {
		t.Fatalf("output length = %d, want the default cap applied", len(got))
	}
}

func TestRunCommandHidesCredentialEnvironment(t *testing.T) {
	t.Chdir(t.TempDir())
	t.Setenv("SUPER_AGENT_TEST_API_KEY", "sk-secret-value")

	got, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "run_command",
		Input: `{"command":"printenv SUPER_AGENT_TEST_API_KEY || echo absent"}`,
	})
	if err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	if strings.Contains(got, "sk-secret-value") {
		t.Fatalf("credential reached the tool environment: %q", got)
	}
	if !strings.Contains(got, "absent") {
		t.Fatalf("result = %q, want the variable to be unset", got)
	}
}

func TestRunCommandKeepsOrdinaryEnvironment(t *testing.T) {
	t.Chdir(t.TempDir())
	t.Setenv("SUPER_AGENT_TEST_PLAIN", "visible")

	// Scrubbing must not be so aggressive that ordinary variables disappear.
	got, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "run_command",
		Input: `{"command":"printenv SUPER_AGENT_TEST_PLAIN"}`,
	})
	if err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	if !strings.Contains(got, "visible") {
		t.Fatalf("result = %q, want the variable to survive", got)
	}
}

func TestRunCommandTimeoutKillsTheProcessTree(t *testing.T) {
	t.Chdir(t.TempDir())
	marker := filepath.Join(t.TempDir(), "survivor")

	// The backgrounded subshell outlives the foreground sleep. Killing only the
	// direct child would orphan it, and it would create the marker afterwards.
	_, err := DefaultRegistry().Run(context.Background(), runtime.ToolCall{
		Name:  "run_command",
		Input: `{"command":"(sleep 3; touch ` + marker + `) & sleep 30","timeout_seconds":1}`,
	})
	if err == nil {
		t.Fatal("Run succeeded, want timeout")
	}

	time.Sleep(4 * time.Second)
	if _, statErr := os.Stat(marker); statErr == nil {
		t.Fatal("background process survived the timeout")
	}
}

// bash shares runExec with run_command, so its timeout and process-group
// handling are covered by TestRunCommandTimeoutKillsTheProcessTree. Testing
// them again here would mean waiting out bash's full 30 second default.
