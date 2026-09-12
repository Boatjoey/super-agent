package app

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const maxExtensionFileSize = 128 << 10

type ExtensionSettings struct {
	Commands map[string]string   `json:"commands"`
	Hooks    map[string][]string `json:"hooks"`
	Skills   []string            `json:"skills"`
	Plugins  []string            `json:"plugins"`
}

type PluginManifest struct {
	Commands map[string]string   `json:"commands"`
	Hooks    map[string][]string `json:"hooks"`
	Skills   []string            `json:"skills"`
}

type Extensions struct {
	Commands    map[string]string
	Hooks       map[string][]string
	SkillPrompt string
	Skills      []string
	Plugins     []string
}

func loadExtensions(settings ExtensionSettings, cwd string) (Extensions, error) {
	commands := cloneStringMap(settings.Commands)
	hooks := cloneHooks(settings.Hooks)
	skillPaths := append([]string(nil), settings.Skills...)
	home, _ := os.UserHomeDir()
	for _, root := range []string{filepath.Join(home, ".superagent"), filepath.Join(cwd, ".superagent")} {
		discovered, err := discoverCommands(filepath.Join(root, "commands"))
		if err != nil {
			return Extensions{}, err
		}
		for name, prompt := range discovered {
			if _, configured := commands[name]; !configured {
				commands[name] = prompt
			}
		}
		discoveredSkills, err := discoverSkills(filepath.Join(root, "skills"))
		if err != nil {
			return Extensions{}, err
		}
		skillPaths = append(skillPaths, discoveredSkills...)
	}
	pluginPaths := append([]string(nil), settings.Plugins...)
	for _, root := range []string{filepath.Join(home, ".superagent", "plugins"), filepath.Join(cwd, ".superagent", "plugins")} {
		entries, err := os.ReadDir(root)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return Extensions{}, err
		}
		for _, entry := range entries {
			if entry.IsDir() {
				pluginPaths = append(pluginPaths, filepath.Join(root, entry.Name()))
			}
		}
	}
	seenPlugins := map[string]bool{}
	for _, pluginPath := range pluginPaths {
		root := resolveConfigPath(cwd, pluginPath)
		if seenPlugins[root] {
			continue
		}
		seenPlugins[root] = true
		content, err := readExtensionFile(filepath.Join(root, "plugin.json"))
		if err != nil {
			return Extensions{}, fmt.Errorf("load plugin %s: %w", pluginPath, err)
		}
		var manifest PluginManifest
		if err := json.Unmarshal(content, &manifest); err != nil {
			return Extensions{}, fmt.Errorf("decode plugin %s: %w", pluginPath, err)
		}
		for name, prompt := range manifest.Commands {
			name = strings.TrimPrefix(strings.TrimSpace(name), "/")
			if _, exists := commands[name]; exists {
				return Extensions{}, errors.New("duplicate custom command: " + name)
			}
			commands[name] = prompt
		}
		for event, commands := range manifest.Hooks {
			hooks[event] = append(hooks[event], commands...)
		}
		for _, path := range manifest.Skills {
			skillPaths = append(skillPaths, filepath.Join(root, path))
		}
	}
	reserved := map[string]bool{"clear": true, "compact": true, "delete-session": true, "help": true, "instructions": true, "permissions": true, "mcp": true, "quit": true, "rename": true, "reset": true, "resume": true, "sessions": true, "undo": true, "agent": true, "build": true, "plan": true, "mode": true, "fork": true, "memory": true, "remember": true, "forget": true, "review": true, "diff": true, "fix-ci": true, "branch": true, "commit-message": true, "export": true, "share": true, "attach": true, "attachments": true, "commands": true, "skills": true, "plugins": true, "diagnostics": true}
	for name, prompt := range commands {
		if name == "" || strings.ContainsAny(name, " \t\n") {
			return Extensions{}, errors.New("invalid custom command name: " + name)
		}
		if reserved[name] {
			return Extensions{}, errors.New("custom command is reserved: " + name)
		}
		if strings.TrimSpace(prompt) == "" {
			return Extensions{}, errors.New("custom command prompt is empty: " + name)
		}
	}
	for event := range hooks {
		if event != "startup" && event != "session_start" && event != "before_turn" && event != "pre_tool" && event != "post_tool" && event != "approval_requested" && event != "turn_complete" && event != "after_turn" && event != "error" {
			return Extensions{}, errors.New("unknown hook event: " + event)
		}
	}
	var skills []string
	for _, skillPath := range skillPaths {
		path := resolveConfigPath(cwd, skillPath)
		if filepath.Base(path) != "SKILL.md" {
			path = filepath.Join(path, "SKILL.md")
		}
		content, err := readExtensionFile(path)
		if err != nil {
			return Extensions{}, fmt.Errorf("load skill %s: %w", skillPath, err)
		}
		skills = append(skills, "Skill: "+filepath.Base(filepath.Dir(path))+"\n"+strings.TrimSpace(string(content)))
	}
	skillNames := make([]string, 0, len(skillPaths))
	for _, path := range skillPaths {
		if filepath.Base(path) == "SKILL.md" {
			path = filepath.Dir(path)
		}
		skillNames = append(skillNames, filepath.Base(path))
	}
	pluginNames := make([]string, 0, len(seenPlugins))
	for path := range seenPlugins {
		pluginNames = append(pluginNames, filepath.Base(path))
	}
	sort.Strings(skillNames)
	sort.Strings(pluginNames)
	return Extensions{Commands: commands, Hooks: hooks, SkillPrompt: strings.Join(skills, "\n\n"), Skills: skillNames, Plugins: pluginNames}, nil
}

func discoverCommands(dir string) (map[string]string, error) {
	result := map[string]string{}
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return result, nil
	}
	if err != nil {
		return nil, err
	}
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".md" {
			continue
		}
		content, err := readExtensionFile(filepath.Join(dir, entry.Name()))
		if err != nil {
			return nil, err
		}
		result[strings.TrimSuffix(entry.Name(), ".md")] = strings.TrimSpace(string(content))
	}
	return result, nil
}

func discoverSkills(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var result []string
	for _, entry := range entries {
		if entry.IsDir() {
			path := filepath.Join(dir, entry.Name(), "SKILL.md")
			if _, err := os.Stat(path); err == nil {
				result = append(result, path)
			}
		}
	}
	return result, nil
}

func readExtensionFile(path string) ([]byte, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if info.Size() > maxExtensionFileSize {
		return nil, errors.New("extension file exceeds 128 KiB")
	}
	return os.ReadFile(path)
}

func resolveConfigPath(cwd, path string) string {
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}
	return filepath.Join(cwd, path)
}

func cloneStringMap(input map[string]string) map[string]string {
	result := make(map[string]string, len(input))
	for name, value := range input {
		result[strings.TrimPrefix(strings.TrimSpace(name), "/")] = value
	}
	return result
}

func cloneHooks(input map[string][]string) map[string][]string {
	result := make(map[string][]string, len(input))
	for event, commands := range input {
		result[event] = append([]string(nil), commands...)
	}
	return result
}
