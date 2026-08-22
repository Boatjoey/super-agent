package runtime_test

import (
	"testing"

	. "super-agent/runtime"
)

func TestActionQueueQueuesScheduledActionsWithRunAndIncrementingIDs(t *testing.T) {
	queue := NewActionQueue()

	first := queue.Queue("run-1", CallModel{})
	second := queue.Queue("run-1", CheckToolQueue{})

	if first.RunID != "run-1" {
		t.Fatalf("first RunID = %q, want run-1", first.RunID)
	}
	if first.ActionID != "action-1" {
		t.Fatalf("first ActionID = %q, want action-1", first.ActionID)
	}
	if second.ActionID != "action-2" {
		t.Fatalf("second ActionID = %q, want action-2", second.ActionID)
	}
	if queue.Len() != 2 {
		t.Fatalf("Len = %d, want 2", queue.Len())
	}
}

func TestActionQueuePopsInFIFOOrder(t *testing.T) {
	queue := NewActionQueue()
	first := queue.Queue("run-1", CallModel{})
	second := queue.Queue("run-1", CheckToolQueue{})

	got, ok := queue.Pop()
	if !ok {
		t.Fatal("Pop returned ok=false, want true")
	}
	if got != first {
		t.Fatalf("first Pop = %+v, want %+v", got, first)
	}

	got, ok = queue.Pop()
	if !ok {
		t.Fatal("second Pop returned ok=false, want true")
	}
	if got != second {
		t.Fatalf("second Pop = %+v, want %+v", got, second)
	}

	if _, ok := queue.Pop(); ok {
		t.Fatal("Pop on empty queue returned ok=true")
	}
}

func TestActionQueueClearDropsPendingScheduledActions(t *testing.T) {
	queue := NewActionQueue()
	queue.Queue("run-1", CallModel{})
	queue.Queue("run-1", CheckToolQueue{})

	queue.Clear()

	if queue.Len() != 0 {
		t.Fatalf("Len = %d, want 0", queue.Len())
	}
	if _, ok := queue.Pop(); ok {
		t.Fatal("Pop after Clear returned ok=true")
	}
}
