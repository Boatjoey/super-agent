//go:build !linux

package tools

import "errors"

func newPlatformSandbox(SandboxConfig) (commandSandbox, error) {
	return nil, errors.New("strict sandbox is currently supported only on Linux; set sandbox.mode to off explicitly")
}
