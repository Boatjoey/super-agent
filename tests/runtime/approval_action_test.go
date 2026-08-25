package runtime_test

import (
	"context"
	"testing"

	. "super-agent/runtime"
)

func TestAwaitApprovalActionUsesInjectedWaiter(t *testing.T) {
	call := ToolCall{ID: "call-1", Name: "bash"}
	request := PermissionRequest{ToolName: "bash", Reason: "risky"}
	waiter := ApprovalWaitFunc(func(_ context.Context, gotCall ToolCall, gotRequest PermissionRequest) (ApprovalDecision, error) {
		if gotCall != call || gotRequest.ToolName != request.ToolName || gotRequest.Reason != request.Reason {
			t.Fatalf("approval input = %+v, %+v", gotCall, gotRequest)
		}
		return ApproveAlways, nil
	})
	executor := NewDefaultScheduledActionExecutor(nil, nil)

	result, err := executor.Execute(context.Background(), AwaitApproval{Call: call, Request: request}, ScheduledActionInput{ApprovalWaiter: waiter}, nil)
	if err != nil {
		t.Fatalf("Execute failed: %v", err)
	}
	approval, ok := result.(ApprovalReceived)
	if !ok {
		t.Fatalf("result = %T, want ApprovalReceived", result)
	}
	if approval.Call != call || approval.Decision != ApproveAlways {
		t.Fatalf("approval result = %+v", approval)
	}
}
