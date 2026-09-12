package tools

import (
	"context"
	"errors"
	"fmt"

	"super-agent/runtime/protocol"
)

type Tool interface {
	Spec() protocol.ToolSpec
	Run(ctx context.Context, call protocol.ToolCall) (string, error)
}

type Registry struct {
	order      []string
	tools      map[string]Tool
	checkpoint func(protocol.ToolCall) error
}

func NewRegistry(items ...Tool) *Registry {
	registry := &Registry{
		tools: make(map[string]Tool, len(items)),
	}
	for _, item := range items {
		name := item.Spec().Name
		registry.order = append(registry.order, name)
		registry.tools[name] = item
	}
	return registry
}

// Add atomically adds dynamically discovered tools. No tool is added when a
// name is empty, duplicated in the batch, or already registered.
func (r *Registry) Add(items ...Tool) error {
	seen := make(map[string]struct{}, len(items))
	for _, item := range items {
		if item == nil {
			return errors.New("cannot register nil tool")
		}
		name := item.Spec().Name
		if name == "" {
			return errors.New("cannot register tool with empty name")
		}
		if _, exists := r.tools[name]; exists {
			return fmt.Errorf("tool %q is already registered", name)
		}
		if _, exists := seen[name]; exists {
			return fmt.Errorf("tool %q is duplicated", name)
		}
		seen[name] = struct{}{}
	}
	for _, item := range items {
		name := item.Spec().Name
		r.order = append(r.order, name)
		r.tools[name] = item
	}
	return nil
}

func (r *Registry) SetCheckpointCallback(callback func(protocol.ToolCall) error) {
	r.checkpoint = callback
}

func DefaultRegistry() *Registry {
	return registryWithRunner(nil)
}

func SandboxedRegistry(config SandboxConfig) (*Registry, error) {
	runner, err := newCommandRunner(config)
	if err != nil {
		return nil, err
	}
	return registryWithRunner(runner), nil
}

func registryWithRunner(runner *commandRunner) *Registry {
	return NewRegistry(
		ReadFileTool{},
		ListFilesTool{},
		SearchTool{},
		ApplyPatchTool{},
		WriteFileTool{},
		RunCommandTool{runner: runner},
		GoTestTool{runner: runner},
		FormatTool{runner: runner},
		GitStatusTool{runner: runner},
		GitDiffTool{runner: runner},
		BashTool{runner: runner},
	)
}

func (r *Registry) Specs() []protocol.ToolSpec {
	specs := make([]protocol.ToolSpec, 0, len(r.order))
	for _, name := range r.order {
		specs = append(specs, r.tools[name].Spec())
	}
	return specs
}

func (r *Registry) Run(ctx context.Context, call protocol.ToolCall) (string, error) {
	tool, ok := r.tools[call.Name]
	if !ok {
		return "", errors.New("unknown tool: " + call.Name)
	}
	if tool.Spec().Risky && r.checkpoint != nil {
		if err := r.checkpoint(call); err != nil {
			return "", err
		}
	}
	return tool.Run(ctx, call)
}
