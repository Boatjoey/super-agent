package app_test

import (
	"context"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"

	. "super-agent/app"
	"super-agent/tools"
	mcptools "super-agent/tools/mcp"
)

func TestAppMCPHelperProcess(t *testing.T) {
	if os.Getenv("SUPER_AGENT_APP_MCP_HELPER") != "1" {
		return
	}
	server := sdk.NewServer(&sdk.Implementation{Name: "fake", Version: "1"}, nil)
	sdk.AddTool(server, &sdk.Tool{Name: "remote"}, func(_ context.Context, _ *sdk.CallToolRequest, _ struct{}) (*sdk.CallToolResult, any, error) {
		return &sdk.CallToolResult{Content: []sdk.Content{&sdk.TextContent{Text: "ok"}}}, nil, nil
	})
	if err := server.Run(context.Background(), &sdk.StdioTransport{}); err != nil {
		os.Exit(2)
	}
}

func TestMCPControllerPersistsAddAndRemove(t *testing.T) {
	manager, err := mcptools.Connect(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close() })
	registry := tools.NewRegistry()
	settingsPath := filepath.Join(t.TempDir(), "settings.json")
	if err := SaveSettingsFile(settingsPath, DefaultSettings()); err != nil {
		t.Fatal(err)
	}
	controller := NewMCPController(manager, registry, settingsPath, t.TempDir(), nil)
	command := "SUPER_AGENT_APP_MCP_HELPER=1 exec " + strconv.Quote(os.Args[0]) + " -test.run=TestAppMCPHelperProcess"
	if err := controller.Add(context.Background(), "fake", "sh", []string{"-c", command}); err != nil {
		t.Fatalf("Add: %v", err)
	}
	if len(controller.List()) != 1 || len(registry.Specs()) != 1 {
		t.Fatalf("runtime state = %+v, specs = %+v", controller.List(), registry.Specs())
	}
	settings, err := LoadSettingsFile(settingsPath)
	if err != nil || settings.MCPServers["fake"].Command != "sh" {
		t.Fatalf("settings = %+v, %v", settings.MCPServers, err)
	}
	if err := controller.Remove("fake"); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	settings, err = LoadSettingsFile(settingsPath)
	if err != nil || len(settings.MCPServers) != 0 || len(registry.Specs()) != 0 {
		t.Fatalf("removed settings = %+v, specs = %+v, %v", settings.MCPServers, registry.Specs(), err)
	}
}
