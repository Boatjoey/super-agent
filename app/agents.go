package app

import (
	"context"
	"errors"
	"sort"
	"strings"
	"sync"

	"super-agent/app/instructions"
	"super-agent/llm"
	"super-agent/runtime"
)

type AgentProfile struct {
	Name, Provider, Model, Prompt string
	PermissionMode                runtime.PermissionMode
	Tools                         []string
}

type filteredToolRunner struct {
	mu      sync.RWMutex
	runner  runtime.ToolRunner
	allowed map[string]struct{}
}

func (r *filteredToolRunner) Specs() []runtime.ToolSpec {
	r.mu.RLock()
	defer r.mu.RUnlock()
	specs := r.runner.Specs()
	if r.allowed == nil {
		return specs
	}
	result := make([]runtime.ToolSpec, 0, len(specs))
	for _, spec := range specs {
		if _, ok := r.allowed[spec.Name]; ok {
			result = append(result, spec)
		}
	}
	return result
}

func (r *filteredToolRunner) Run(ctx context.Context, call runtime.ToolCall) (string, error) {
	r.mu.RLock()
	_, allowed := r.allowed[call.Name]
	unrestricted := r.allowed == nil
	r.mu.RUnlock()
	if !unrestricted && !allowed {
		return "", errors.New("tool is not enabled for active agent: " + call.Name)
	}
	return r.runner.Run(ctx, call)
}

func (r *filteredToolRunner) setAllowed(names []string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(names) == 0 {
		r.allowed = nil
		return
	}
	r.allowed = make(map[string]struct{}, len(names))
	for _, name := range names {
		r.allowed[name] = struct{}{}
	}
}

type routedModel struct {
	mu    sync.RWMutex
	model runtime.Model
}

func (m *routedModel) Next(ctx context.Context, messages []runtime.Message, specs []runtime.ToolSpec, stream func(runtime.StreamChunk)) (runtime.ModelResponse, error) {
	m.mu.RLock()
	model := m.model
	m.mu.RUnlock()
	return model.Next(ctx, messages, specs, stream)
}

func (m *routedModel) set(model runtime.Model) {
	m.mu.Lock()
	m.model = model
	m.mu.Unlock()
}

type AgentController struct {
	mu        sync.RWMutex
	session   *runtime.Session
	model     *routedModel
	profiles  map[string]AgentProfile
	providers map[string]llm.ProviderConfig
	workflows *WorkflowController
	tools     *filteredToolRunner
	base      string
	current   string
}

func (c *AgentController) GitDiff(ctx context.Context) (string, error) {
	return c.workflows.GitDiff(ctx)
}

func (c *AgentController) GitStatus(ctx context.Context) (string, error) {
	return c.workflows.GitStatus(ctx)
}
func (c *AgentController) Diagnostics(ctx context.Context, path string) (string, error) {
	return c.workflows.Diagnostics(ctx, path)
}
func (c *AgentController) RunHook(ctx context.Context, event string) error {
	return c.workflows.RunHook(ctx, event)
}
func (c *AgentController) RunHooks(ctx context.Context, events ...string) error {
	return c.workflows.RunHooks(ctx, events...)
}
func (c *AgentController) CustomCommands() []string { return c.workflows.CustomCommands() }
func (c *AgentController) Skills() []string         { return c.workflows.Skills() }
func (c *AgentController) Plugins() []string        { return c.workflows.Plugins() }
func (c *AgentController) ExpandCommand(name, arguments string) (string, error) {
	return c.workflows.ExpandCommand(name, arguments)
}

func buildAgentProfiles(cfg Config, providers map[string]llm.ProviderConfig) (map[string]AgentProfile, error) {
	skillPrompt := ""
	if cfg.Extensions.SkillPrompt != "" {
		skillPrompt = "\n\nAvailable skills:\n" + cfg.Extensions.SkillPrompt
	}
	profiles := map[string]AgentProfile{
		"build": {Name: "build", Provider: cfg.Provider, Model: cfg.ModelConfig.Model, Prompt: "Build mode: inspect, implement, verify, and finish requested changes." + skillPrompt, PermissionMode: cfg.PermissionMode},
		"plan":  {Name: "plan", Provider: cfg.Provider, Model: cfg.ModelConfig.Model, Prompt: "Plan mode: investigate and propose a plan. Do not modify files or run mutating tools." + skillPrompt, PermissionMode: runtime.PermissionModePlan},
	}
	for name, item := range cfg.Agents {
		name = strings.TrimSpace(name)
		if name == "" || name == "build" || name == "plan" {
			return nil, errors.New("custom agent name is empty or reserved: " + name)
		}
		provider := firstNonEmpty(item.Provider, cfg.Provider)
		providerCfg, ok := providers[provider]
		if !ok {
			return nil, errors.New("agent " + name + " references unknown provider: " + provider)
		}
		if item.Model != "" {
			providerCfg.Model = item.Model
		}
		mode := runtime.PermissionMode(firstNonEmpty(item.PermissionMode, string(cfg.PermissionMode)))
		if !runtime.ValidPermissionMode(mode) {
			return nil, errors.New("agent " + name + " has invalid permission mode: " + string(mode))
		}
		profiles[name] = AgentProfile{Name: name, Provider: provider, Model: providerCfg.Model, Prompt: strings.TrimSpace(item.Prompt) + skillPrompt, PermissionMode: mode, Tools: append([]string(nil), item.Tools...)}
	}
	return profiles, nil
}

func (c *AgentController) List() []AgentProfile {
	c.mu.RLock()
	defer c.mu.RUnlock()
	result := make([]AgentProfile, 0, len(c.profiles))
	for _, profile := range c.profiles {
		result = append(result, profile)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Name < result[j].Name })
	return result
}

func (c *AgentController) Current() AgentProfile {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.profiles[c.current]
}

func (c *AgentController) Use(name string) error {
	c.mu.RLock()
	profile, ok := c.profiles[name]
	c.mu.RUnlock()
	if !ok {
		return errors.New("unknown agent: " + name)
	}
	config := c.providers[profile.Provider]
	if profile.Model != "" {
		config.Model = profile.Model
	}
	model, err := llm.NewModel(profile.Provider, config)
	if err != nil {
		return err
	}
	messages, _, err := initialMessagesWithAgent(c.base, profile)
	if err != nil {
		return err
	}
	memories, err := c.session.Memories()
	if err != nil {
		return err
	}
	if len(memories) > 0 {
		messages = append(messages, runtime.Message{Role: runtime.RoleSystem, Content: "Cross-session memory:\n- " + strings.Join(memories, "\n- ")})
	}
	if err := c.session.ReplaceConversation(messages); err != nil {
		return err
	}
	if err := c.session.SetPermissionMode(profile.PermissionMode); err != nil {
		return err
	}
	c.model.set(model)
	if c.tools != nil {
		c.tools.setAllowed(profile.Tools)
	}
	c.mu.Lock()
	c.current = name
	c.mu.Unlock()
	return nil
}

func initialMessagesWithAgent(cwd string, profile AgentProfile) ([]runtime.Message, instructions.Bundle, error) {
	messages, bundle, err := initialMessages(cwd)
	if err == nil && profile.Prompt != "" {
		messages[0].Content += "\n\nActive agent profile: " + profile.Name + "\n" + profile.Prompt
	}
	return messages, bundle, err
}
