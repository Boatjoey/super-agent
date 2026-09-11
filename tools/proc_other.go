//go:build !unix

package tools

import (
	"os/exec"
	"time"
)

const processGroupWaitDelay = 2 * time.Second

// isolateProcessGroup falls back to killing the direct child on platforms
// without process groups. WaitDelay still guards against a surviving
// grandchild holding the output pipes open.
func isolateProcessGroup(cmd *exec.Cmd) {
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return cmd.Process.Kill()
	}
	cmd.WaitDelay = processGroupWaitDelay
}
