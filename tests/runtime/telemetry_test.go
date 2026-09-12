package runtime_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	. "super-agent/runtime"
	"super-agent/runtime/telemetry"
)

func TestEngineWritesCorrelatedTelemetry(t *testing.T) {
	path := filepath.Join(t.TempDir(), "telemetry.jsonl")
	if err := telemetry.Configure(path); err != nil {
		t.Fatal(err)
	}
	defer telemetry.Close()
	engine := NewEngineWithExecutor(&staticExecutor{}, nil)
	if err := engine.Ready(); err != nil {
		t.Fatal(err)
	}
	if err := engine.RunTurn(context.Background(), UserMessageSubmitted{Content: "hello"}, nil, nil); err != nil {
		t.Fatal(err)
	}
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	log := string(content)
	for _, expected := range []string{`"kind":"transition"`, `"kind":"action"`, `"kind":"run"`, `"run_id":"run-1"`, `"action_id":"action-1"`, `"component":"model"`, `"input_tokens_estimate"`, `"output_tokens_estimate"`} {
		if !strings.Contains(log, expected) {
			t.Fatalf("telemetry missing %s: %s", expected, log)
		}
	}
}
