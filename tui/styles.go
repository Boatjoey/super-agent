package tui

import (
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
)

type Styles struct {
	Status           lipgloss.Style
	UserLabel        lipgloss.Style
	ToolLabel        lipgloss.Style
	CommandLabel     lipgloss.Style
	Thinking         lipgloss.Style
	Error            lipgloss.Style
	Footer           lipgloss.Style
	MarkdownRenderer *glamour.TermRenderer
}

func DefaultStyles() Styles {
	secondary := lipgloss.Color("8")
	accent := lipgloss.Color("6")
	styles := Styles{
		Status:       lipgloss.NewStyle().Foreground(accent).Italic(true),
		UserLabel:    lipgloss.NewStyle().Foreground(lipgloss.Color("2")).Bold(true),
		ToolLabel:    lipgloss.NewStyle().Foreground(accent).Bold(true),
		CommandLabel: lipgloss.NewStyle().Foreground(lipgloss.Color("3")).Bold(true),
		Thinking:     lipgloss.NewStyle().Foreground(secondary).Italic(true),
		Error:        lipgloss.NewStyle().Foreground(lipgloss.Color("1")).Bold(true),
		Footer:       lipgloss.NewStyle().Foreground(secondary).Italic(true),
	}
	styles.MarkdownRenderer, _ = glamour.NewTermRenderer(glamour.WithAutoStyle(), glamour.WithWordWrap(0))
	return styles
}
