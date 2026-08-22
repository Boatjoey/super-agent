package runtime_test

import (
	"testing"

	. "super-agent/runtime"
)

func TestActionSchedulerQueuesScheduledActionsWithRunAndIncrementingIDs(t *testing.T) {
	scheduler := NewActionScheduler()

	first := scheduler.Queue("run-1", CallModel{})
	second := scheduler.Queue("run-1", ProcessNextToolCall{})

	if first.RunID != "run-1" {
		t.Fatalf("first RunID = %q, want run-1", first.RunID)
	}
	if first.ActionID != "action-1" {
		t.Fatalf("first ActionID = %q, want action-1", first.ActionID)
	}
	if second.ActionID != "action-2" {
		t.Fatalf("second ActionID = %q, want action-2", second.ActionID)
	}
	if scheduler.Len() != 2 {
		t.Fatalf("Len = %d, want 2", scheduler.Len())
	}
}

func TestActionSchedulerPopsInFIFOOrder(t *testing.T) {
	scheduler := NewActionScheduler()
	first := scheduler.Queue("run-1", CallModel{})
	second := scheduler.Queue("run-1", ProcessNextToolCall{})

	got, ok := scheduler.Pop()
	if !ok {
		t.Fatal("Pop returned ok=false, want true")
	}
	if got != first {
		t.Fatalf("first Pop = %+v, want %+v", got, first)
	}

	got, ok = scheduler.Pop()
	if !ok {
		t.Fatal("second Pop returned ok=false, want true")
	}
	if got != second {
		t.Fatalf("second Pop = %+v, want %+v", got, second)
	}

	if _, ok := scheduler.Pop(); ok {
		t.Fatal("Pop on empty scheduler returned ok=true")
	}
}

func TestActionSchedulerClearDropsPendingScheduledActions(t *testing.T) {
	scheduler := NewActionScheduler()
	scheduler.Queue("run-1", CallModel{})
	scheduler.Queue("run-1", ProcessNextToolCall{})

	scheduler.Clear()

	if scheduler.Len() != 0 {
		t.Fatalf("Len = %d, want 0", scheduler.Len())
	}
	if _, ok := scheduler.Pop(); ok {
		t.Fatal("Pop after Clear returned ok=true")
	}
}
