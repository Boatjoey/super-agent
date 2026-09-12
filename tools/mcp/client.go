package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"time"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"

	"super-agent/runtime/protocol"
	builtintools "super-agent/tools"
)

const (
	defaultConnectTimeout = 10 * time.Second
	defaultCallTimeout    = 60 * time.Second
	maxResultBytes        = 200000
)

type ServerConfig struct {
	Name           string
	Command        string
	Args           []string
	Env            map[string]string
	CWD            string
	ConnectTimeout time.Duration
	CallTimeout    time.Duration
}

type Manager struct {
	mu      sync.RWMutex
	servers map[string]*server
	tools   []builtintools.Tool
	closed  bool
}

type server struct {
	name        string
	session     *sdk.ClientSession
	callTimeout time.Duration
}

type remoteTool struct {
	server     *server
	remoteName string
	spec       protocol.ToolSpec
}

func Connect(ctx context.Context, configs []ServerConfig) (*Manager, error) {
	manager := &Manager{servers: make(map[string]*server)}
	for _, config := range configs {
		if err := manager.connect(ctx, config); err != nil {
			_ = manager.Close()
			return nil, err
		}
	}
	return manager, nil
}

func (m *Manager) connect(ctx context.Context, config ServerConfig) error {
	if config.Name == "" || config.Command == "" {
		return errors.New("MCP server name and command are required")
	}
	if _, exists := m.servers[config.Name]; exists {
		return fmt.Errorf("MCP server %q is duplicated", config.Name)
	}
	connectTimeout := config.ConnectTimeout
	if connectTimeout <= 0 {
		connectTimeout = defaultConnectTimeout
	}
	callTimeout := config.CallTimeout
	if callTimeout <= 0 {
		callTimeout = defaultCallTimeout
	}
	connectCtx, cancel := context.WithTimeout(ctx, connectTimeout)
	defer cancel()

	command := exec.Command(config.Command, config.Args...)
	command.Dir = config.CWD
	command.Env = commandEnvironment(config.Env)
	client := sdk.NewClient(&sdk.Implementation{Name: "super-agent", Version: "dev"}, nil)
	session, err := client.Connect(connectCtx, &sdk.CommandTransport{Command: command}, nil)
	if err != nil {
		return fmt.Errorf("connect MCP server %q: %w", config.Name, err)
	}
	connected := &server{name: config.Name, session: session, callTimeout: callTimeout}
	discovered, err := session.ListTools(connectCtx, nil)
	if err != nil {
		_ = session.Close()
		return fmt.Errorf("list tools from MCP server %q: %w", config.Name, err)
	}

	batch := make([]builtintools.Tool, 0, len(discovered.Tools))
	for _, tool := range discovered.Tools {
		spec, err := toolSpec(tool)
		if err != nil {
			_ = session.Close()
			return fmt.Errorf("map MCP tool from server %q: %w", config.Name, err)
		}
		batch = append(batch, &remoteTool{server: connected, remoteName: tool.Name, spec: spec})
	}
	m.servers[config.Name] = connected
	m.tools = append(m.tools, batch...)
	return nil
}

func (m *Manager) Tools() []builtintools.Tool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return append([]builtintools.Tool(nil), m.tools...)
}

func (m *Manager) Close() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.closed {
		return nil
	}
	m.closed = true
	names := make([]string, 0, len(m.servers))
	for name := range m.servers {
		names = append(names, name)
	}
	sort.Strings(names)
	var closeErr error
	for _, name := range names {
		if err := m.servers[name].session.Close(); err != nil {
			closeErr = errors.Join(closeErr, fmt.Errorf("close MCP server %q: %w", name, err))
		}
	}
	return closeErr
}

func (t *remoteTool) Spec() protocol.ToolSpec { return t.spec }

func (t *remoteTool) Run(ctx context.Context, call protocol.ToolCall) (string, error) {
	var arguments json.RawMessage
	if strings.TrimSpace(call.Input) == "" {
		arguments = json.RawMessage(`{}`)
	} else if err := json.Unmarshal([]byte(call.Input), &arguments); err != nil {
		return "", fmt.Errorf("MCP tool %s.%s input: %w", t.server.name, t.remoteName, err)
	}
	callCtx, cancel := context.WithTimeout(ctx, t.server.callTimeout)
	defer cancel()
	result, err := t.server.session.CallTool(callCtx, &sdk.CallToolParams{Name: t.remoteName, Arguments: arguments})
	if err != nil {
		return "", fmt.Errorf("call MCP tool %s.%s: %w", t.server.name, t.remoteName, err)
	}
	return formatResult(result), nil
}

func toolSpec(tool *sdk.Tool) (protocol.ToolSpec, error) {
	if tool == nil || tool.Name == "" {
		return protocol.ToolSpec{}, errors.New("tool name is required")
	}
	parameters := map[string]any{"type": "object"}
	if tool.InputSchema != nil {
		encoded, err := json.Marshal(tool.InputSchema)
		if err != nil {
			return protocol.ToolSpec{}, err
		}
		if err := json.Unmarshal(encoded, &parameters); err != nil {
			return protocol.ToolSpec{}, err
		}
	}
	return protocol.ToolSpec{Name: tool.Name, Description: tool.Description, Parameters: parameters, Risky: true}, nil
}

func formatResult(result *sdk.CallToolResult) string {
	if result == nil {
		return ""
	}
	parts := make([]string, 0, len(result.Content)+1)
	for _, content := range result.Content {
		if text, ok := content.(*sdk.TextContent); ok {
			parts = append(parts, text.Text)
			continue
		}
		if encoded, err := content.MarshalJSON(); err == nil {
			parts = append(parts, string(encoded))
		}
	}
	if result.StructuredContent != nil {
		if encoded, err := json.Marshal(result.StructuredContent); err == nil {
			parts = append(parts, string(encoded))
		}
	}
	output := strings.Join(parts, "\n")
	if result.IsError && output == "" {
		output = "MCP tool reported an error"
	}
	if len(output) > maxResultBytes {
		output = output[:maxResultBytes] + "\n... truncated"
	}
	return output
}

func commandEnvironment(overrides map[string]string) []string {
	keys := []string{"HOME", "LANG", "LC_ALL", "PATH", "PATHEXT", "SYSTEMROOT", "TMPDIR", "USER"}
	env := make([]string, 0, len(keys)+len(overrides))
	for _, key := range keys {
		if value, ok := os.LookupEnv(key); ok {
			env = append(env, key+"="+value)
		}
	}
	overrideKeys := make([]string, 0, len(overrides))
	for key := range overrides {
		overrideKeys = append(overrideKeys, key)
	}
	sort.Strings(overrideKeys)
	for _, key := range overrideKeys {
		env = append(env, key+"="+overrides[key])
	}
	return env
}
