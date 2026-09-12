package app

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"time"

	"super-agent/app/instructions"
	"super-agent/llm"
	"super-agent/runtime"
	"super-agent/store"
	"super-agent/tools"
	mcptools "super-agent/tools/mcp"
	"super-agent/workspace"
)

func NewSession(cfg Config) (*runtime.Session, error) {
	session, _, err := NewSessionWithMCP(cfg)
	return session, err
}

func NewSessionWithMCP(cfg Config) (*runtime.Session, *MCPController, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return nil, nil, err
	}
	model, err := llm.NewModel(cfg.Provider, cfg.ModelConfig) // 模型调用的封装
	if err != nil {
		return nil, nil, err
	}
	var (
		toolRunner runtime.ToolRunner
		registry   *tools.Registry
		extension  io.Closer
		controller *MCPController
	)
	defer func() {
		if extension != nil {
			_ = extension.Close()
		}
	}()
	if cfg.NoTools {
		toolRunner = tools.NoTools{}
	} else {
		registry, err = tools.SandboxedRegistry(cfg.Sandbox)
		if err != nil {
			return nil, nil, err
		}
		manager, connectErr := mcptools.Connect(context.Background(), cfg.MCPServers)
		if connectErr != nil {
			return nil, nil, connectErr
		}
		if addErr := registry.Add(manager.Tools()...); addErr != nil {
			_ = manager.Close()
			return nil, nil, addErr
		}
		settingsPath, pathErr := SettingsPath()
		if pathErr != nil {
			_ = manager.Close()
			return nil, nil, pathErr
		}
		controller = NewMCPController(manager, registry, settingsPath, cwd, settingsMap(cfg.MCPServers))
		// The runtime session owns extension process lifetime after creation.
		extension = manager
		toolRunner = runtime.ToolRunner(registry) // 工具调用的封装
	}
	initial, bundle, err := initialMessages(cwd) //
	if err != nil {
		return nil, nil, err
	}
	engine := runtime.NewEngineWithExecutorAndPolicy(runtime.NewDefaultScheduledActionExecutor(model, toolRunner), runtime.NewPolicy(cfg.PermissionMode, cfg.PermissionRules), initial)
	if cfg.AutoApproveTools {
		engine.EnableAutoApproveTools()
	}
	if err := engine.Ready(); err != nil {
		return nil, nil, err
	}
	st, err := store.OpenDefault()
	if err != nil {
		return nil, nil, err
	}
	repository := store.NewRepository(st)
	session, err := runtime.CreatePersistentSession(engine, repository, workspace.Workspace{}, runtime.SessionMetadata{
		Provider: cfg.Provider, Model: cfg.ModelConfig.Model, CWD: cwd,
		Title: filepath.Base(cwd), InstructionSources: instructionSourcePaths(bundle),
	}, initial)
	if err != nil {
		return nil, nil, err
	}
	if registry != nil {
		registry.SetCheckpointCallback(session.Checkpoint)
	}
	session.ConfigurePermissions(cfg.PermissionMode, cfg.PermissionRules)
	if extension != nil {
		session.AddCloser(extension)
		extension = nil
	}
	return session, controller, nil
}

func settingsMap(configs []mcptools.ServerConfig) map[string]MCPServerSettings {
	result := make(map[string]MCPServerSettings, len(configs))
	for _, config := range configs {
		result[config.Name] = MCPServerSettings{
			Command: config.Command, Args: config.Args, Env: config.Env, CWD: config.CWD,
			ConnectTimeoutSeconds: int(config.ConnectTimeout / time.Second),
			CallTimeoutSeconds:    int(config.CallTimeout / time.Second),
		}
	}
	return result
}

func initialMessages(cwd string) ([]runtime.Message, instructions.Bundle, error) {
	bundle, err := instructions.Load(cwd)
	if err != nil {
		return nil, instructions.Bundle{}, err
	}
	content := SystemPrompt // `:=` 是短变量声明，系统提示词
	if bundle.Content != "" {
		content += "\n\n" + bundle.Content // 拼接 AGENTS.md 这类系统提示词
	}
	return []runtime.Message{{Role: runtime.RoleSystem, Content: content}}, bundle, nil
}

func instructionSourcePaths(bundle instructions.Bundle) []string {
	paths := make([]string, 0, len(bundle.Sources))
	for _, source := range bundle.Sources {
		paths = append(paths, source.Path)
	}
	return paths
}
