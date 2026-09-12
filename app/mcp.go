package app

import (
	"context"
	"errors"
	"path/filepath"
	"sync"
	"time"

	"super-agent/tools"
	mcptools "super-agent/tools/mcp"
)

type MCPServerSummary struct {
	Name  string
	Tools []string
}

type MCPController struct {
	mu           sync.Mutex
	manager      *mcptools.Manager
	registry     *tools.Registry
	settingsPath string
	workspace    string
	configs      map[string]MCPServerSettings
}

func NewMCPController(manager *mcptools.Manager, registry *tools.Registry, settingsPath, workspace string, configs map[string]MCPServerSettings) *MCPController {
	return &MCPController{manager: manager, registry: registry, settingsPath: settingsPath, workspace: workspace, configs: cloneMCPSettings(configs)}
}

func (c *MCPController) List() []MCPServerSummary {
	servers := c.manager.Servers()
	result := make([]MCPServerSummary, 0, len(servers))
	for _, server := range servers {
		result = append(result, MCPServerSummary{Name: server.Name, Tools: server.Tools})
	}
	return result
}

func (c *MCPController) Add(ctx context.Context, name, command string, args []string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if name == "" || command == "" {
		return errors.New("MCP server name and command are required")
	}
	settings := MCPServerSettings{Command: command, Args: append([]string(nil), args...)}
	config := c.serverConfig(name, settings)
	added, err := c.manager.Add(ctx, config)
	if err != nil {
		return err
	}
	if err := c.registry.Add(added...); err != nil {
		_, _ = c.manager.Remove(name)
		return err
	}
	if err := c.persist(name, &settings); err != nil {
		c.registry.Remove(toolNames(added)...)
		_, _ = c.manager.Remove(name)
		return err
	}
	c.configs[name] = settings
	return nil
}

func (c *MCPController) Remove(name string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	settings, exists := c.configs[name]
	if !exists {
		return errors.New("MCP server not found: " + name)
	}
	names, err := c.manager.Remove(name)
	if err != nil {
		return err
	}
	c.registry.Remove(names...)
	if err := c.persist(name, nil); err != nil {
		added, reconnectErr := c.manager.Add(context.Background(), c.serverConfig(name, settings))
		if reconnectErr == nil {
			reconnectErr = c.registry.Add(added...)
		}
		return errors.Join(err, reconnectErr)
	}
	delete(c.configs, name)
	return nil
}

func (c *MCPController) Restart(ctx context.Context, name string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.manager.Restart(ctx, name, func(oldNames []string, replacement []tools.Tool) error {
		return c.registry.Replace(oldNames, replacement...)
	})
}

func (c *MCPController) persist(name string, server *MCPServerSettings) error {
	settings, err := LoadSettingsFile(c.settingsPath)
	if err != nil {
		return err
	}
	if settings.MCPServers == nil {
		settings.MCPServers = make(map[string]MCPServerSettings)
	}
	if server == nil {
		delete(settings.MCPServers, name)
	} else {
		settings.MCPServers[name] = *server
	}
	return SaveSettingsFile(c.settingsPath, settings)
}

func (c *MCPController) serverConfig(name string, settings MCPServerSettings) mcptools.ServerConfig {
	cwd := settings.CWD
	if cwd == "" {
		cwd = c.workspace
	} else if !filepath.IsAbs(cwd) {
		cwd = filepath.Join(c.workspace, cwd)
	}
	return mcptools.ServerConfig{
		Name: name, Command: settings.Command, Args: settings.Args, Env: settings.Env, CWD: cwd,
		ConnectTimeout: time.Duration(settings.ConnectTimeoutSeconds) * time.Second,
		CallTimeout:    time.Duration(settings.CallTimeoutSeconds) * time.Second,
	}
}

func cloneMCPSettings(configs map[string]MCPServerSettings) map[string]MCPServerSettings {
	result := make(map[string]MCPServerSettings, len(configs))
	for name, config := range configs {
		result[name] = config
	}
	return result
}

func toolNames(items []tools.Tool) []string {
	names := make([]string, 0, len(items))
	for _, item := range items {
		names = append(names, item.Spec().Name)
	}
	return names
}
