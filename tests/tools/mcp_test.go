package tools_test

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"

	"super-agent/runtime"
	. "super-agent/tools"
	mcptools "super-agent/tools/mcp"
)

func TestMCPHelperProcess(t *testing.T) {
	if os.Getenv("SUPER_AGENT_MCP_HELPER") != "1" {
		return
	}
	server := sdk.NewServer(&sdk.Implementation{Name: "fake", Version: "1"}, nil)
	type echoInput struct {
		Text string `json:"text" jsonschema:"required"`
	}
	sdk.AddTool(server, &sdk.Tool{Name: "echo", Description: "Echo text"}, func(_ context.Context, _ *sdk.CallToolRequest, input echoInput) (*sdk.CallToolResult, any, error) {
		return &sdk.CallToolResult{Content: []sdk.Content{&sdk.TextContent{Text: "echo: " + input.Text}}}, nil, nil
	})
	if err := server.Run(context.Background(), &sdk.StdioTransport{}); err != nil {
		os.Exit(2)
	}
}

func TestMCPStdioDiscoversAndCallsTool(t *testing.T) {
	config := fakeMCPConfig("fake")
	manager, err := mcptools.Connect(context.Background(), []mcptools.ServerConfig{config})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}
	t.Cleanup(func() { _ = manager.Close() })

	discovered := manager.Tools()
	if len(discovered) != 1 {
		t.Fatalf("tools = %d, want 1", len(discovered))
	}
	spec := discovered[0].Spec()
	if spec.Name != "echo" || spec.Description != "Echo text" || !spec.Risky {
		t.Fatalf("spec = %+v", spec)
	}
	if spec.Parameters["type"] != "object" {
		t.Fatalf("schema = %+v", spec.Parameters)
	}

	registry := NewRegistry()
	if err := registry.Add(discovered...); err != nil {
		t.Fatalf("Add MCP tools: %v", err)
	}
	result, err := registry.Run(context.Background(), runtime.ToolCall{Name: "echo", Input: `{"text":"hello"}`})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if result != "echo: hello" {
		t.Fatalf("result = %q", result)
	}
}

func TestMCPManagerAddsRemovesAndRestartsServers(t *testing.T) {
	manager, err := mcptools.Connect(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	config := fakeMCPConfig("dynamic")
	added, err := manager.Add(context.Background(), config)
	if err != nil || len(added) != 1 {
		t.Fatalf("Add = %d tools, %v", len(added), err)
	}
	servers := manager.Servers()
	if len(servers) != 1 || servers[0].Name != "dynamic" || len(servers[0].Tools) != 1 || servers[0].Tools[0] != "echo" {
		t.Fatalf("Servers = %+v", servers)
	}
	oldNames, replacement, err := manager.Restart(context.Background(), "dynamic")
	if err != nil || len(oldNames) != 1 || len(replacement) != 1 {
		t.Fatalf("Restart = %+v, %d, %v", oldNames, len(replacement), err)
	}
	removed, err := manager.Remove("dynamic")
	if err != nil || len(removed) != 1 || len(manager.Tools()) != 0 {
		t.Fatalf("Remove = %+v, tools %d, %v", removed, len(manager.Tools()), err)
	}
	if _, err := manager.Remove("dynamic"); err == nil {
		t.Fatal("second Remove succeeded")
	}
}

func TestMCPConnectNormalizesServerFailure(t *testing.T) {
	_, err := mcptools.Connect(context.Background(), []mcptools.ServerConfig{{
		Name:           "broken",
		Command:        os.Args[0],
		Args:           []string{"-test.run=TestMCPHelperProcess"},
		ConnectTimeout: time.Second,
	}})
	if err == nil || !strings.Contains(err.Error(), `MCP server "broken"`) {
		t.Fatalf("err = %v", err)
	}
}

func fakeMCPConfig(name string) mcptools.ServerConfig {
	return mcptools.ServerConfig{
		Name:           name,
		Command:        os.Args[0],
		Args:           []string{"-test.run=TestMCPHelperProcess"},
		Env:            map[string]string{"SUPER_AGENT_MCP_HELPER": "1"},
		ConnectTimeout: 5 * time.Second,
		CallTimeout:    5 * time.Second,
	}
}
