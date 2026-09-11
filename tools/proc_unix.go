//go:build unix

package tools

import (
	"os/exec"
	"syscall"
	"time"
)

// processGroupWaitDelay bounds how long Wait keeps waiting for the stdout and
// stderr pipes to close after the command itself has exited or been killed.
const processGroupWaitDelay = 2 * time.Second

// isolateProcessGroup puts the child into its own process group so the whole
// tree can be terminated on timeout.
//
// Killing only the direct child is not enough: `bash -lc "make"` leaves the
// compiler running, and `bash -lc "sleep 300 &"` leaves the background job
// running, both after the tool call has already returned.
func isolateProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		return killProcessGroup(cmd)
	}
	// Without WaitDelay, Wait blocks until every holder of the stdout/stderr
	// pipe closes it. A surviving grandchild keeps that pipe open, so a command
	// that already hit its deadline would hang past it.
	cmd.WaitDelay = processGroupWaitDelay
}

func killProcessGroup(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	// A negative pid targets every process in the group.
	err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	if err == syscall.ESRCH {
		return nil
	}
	return err
}
