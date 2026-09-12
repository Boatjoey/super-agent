package app

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
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
}

func loadExtensions(settings ExtensionSettings, cwd string) (Extensions, error) {
	commands := cloneStringMap(settings.Commands)
	hooks := cloneHooks(settings.Hooks)
	skillPaths := append([]string(nil), settings.Skills...)
	for _, pluginPath := range settings.Plugins {
		root := resolveConfigPath(cwd, pluginPath)
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
	reserved := map[string]bool{"clear": true, "compact": true, "delete-session": true, "help": true, "instructions": true, "permissions": true, "mcp": true, "quit": true, "rename": true, "reset": true, "resume": true, "sessions": true, "undo": true, "agent": true, "build": true, "plan": true, "fork": true, "memory": true, "remember": true, "forget": true, "review": true, "diff": true, "fix-ci": true, "branch": true, "commit-message": true}
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
		if event != "startup" && event != "before_turn" && event != "after_turn" {
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
	return Extensions{Commands: commands, Hooks: hooks, SkillPrompt: strings.Join(skills, "\n\n")}, nil
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
