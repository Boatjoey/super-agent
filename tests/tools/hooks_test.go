package tools_test

import (
	"context"
	"reflect"
	"testing"

	"super-agent/runtime/protocol"
	"super-agent/tools"
)

type observedTool struct{}

func (observedTool) Spec() protocol.ToolSpec                                { return protocol.ToolSpec{Name: "observed"} }
func (observedTool) Run(context.Context, protocol.ToolCall) (string, error) { return "ok", nil }

func TestToolHooksRunBeforeAndAfterInOrder(t *testing.T) {
	registry := tools.NewRegistry(observedTool{})
	var events []string
	registry.SetToolObserver(func(_ context.Context, event string, _ protocol.ToolCall, _ error) error {
		events = append(events, event)
		return nil
	})
	if _, err := registry.Run(context.Background(), protocol.ToolCall{Name: "observed"}); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(events, []string{"pre_tool", "post_tool"}) {
		t.Fatalf("events = %+v", events)
	}
}
