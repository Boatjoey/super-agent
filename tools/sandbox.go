package tools

import (
	"errors"
	"os"
	"path/filepath"
	"time"
)

type SandboxMode string

const (
	SandboxModeOff    SandboxMode = "off"
	SandboxModeStrict SandboxMode = "strict"
)

type SandboxConfig struct {
	Mode         SandboxMode
	Workspace    string
	AllowNetwork bool
	CPUSeconds   int
	MemoryBytes  int64
	MaxProcesses int
	MaxOpenFiles int
}

func DefaultSandboxConfig(workspace string) SandboxConfig {
	return SandboxConfig{
		Mode:         SandboxModeStrict,
		Workspace:    workspace,
		CPUSeconds:   120,
		MemoryBytes:  1 << 30,
		MaxProcesses: 128,
		MaxOpenFiles: 256,
	}
}

func ValidSandboxMode(mode SandboxMode) bool {
	return mode == SandboxModeOff || mode == SandboxModeStrict
}

type commandSandbox interface {
	wrap(cwd, name string, args []string) (string, []string, string, error)
}

type commandRunner struct {
	sandbox commandSandbox
}

var directCommandRunner = &commandRunner{}

func newCommandRunner(config SandboxConfig) (*commandRunner, error) {
	if config.Mode == "" {
		config.Mode = SandboxModeStrict
	}
	if !ValidSandboxMode(config.Mode) {
		return nil, errors.New("invalid sandbox mode: " + string(config.Mode))
	}
	if config.Mode == SandboxModeOff {
		return &commandRunner{}, nil
	}
	if config.Workspace == "" {
		var err error
		config.Workspace, err = os.Getwd()
		if err != nil {
			return nil, err
		}
	}
	workspace, err := filepath.Abs(config.Workspace)
	if err != nil {
		return nil, err
	}
	workspace, err = filepath.EvalSymlinks(workspace)
	if err != nil {
		return nil, err
	}
	config.Workspace = workspace
	if config.CPUSeconds <= 0 {
		config.CPUSeconds = int(maxCommandTimeout / time.Second)
	}
	if config.MemoryBytes <= 0 {
		config.MemoryBytes = 1 << 30
	}
	if config.MaxProcesses <= 0 {
		config.MaxProcesses = 128
	}
	if config.MaxOpenFiles <= 0 {
		config.MaxOpenFiles = 256
	}
	sandbox, err := newPlatformSandbox(config)
	if err != nil {
		return nil, err
	}
	return &commandRunner{sandbox: sandbox}, nil
}

func runnerOrDefault(runner *commandRunner) *commandRunner {
	if runner == nil {
		return directCommandRunner
	}
	return runner
}
