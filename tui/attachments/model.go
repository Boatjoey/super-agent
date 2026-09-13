package attachments

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type Item struct {
	Name string
	MIME string
}

type Port interface {
	Attach(string) (Item, error)
	PendingAttachments() []Item
}

type Loaded struct{ Items []Item }

type Attached struct {
	Item Item
	Err  error
}

type Outcome struct {
	Attached *Item
	Err      error
}

type Model struct {
	port  Port
	items []Item
}

func New(port Port) Model { return Model{port: port} }

func (m Model) Init() tea.Cmd {
	return func() tea.Msg { return Loaded{Items: m.port.PendingAttachments()} }
}

func (m Model) Attach(path string) tea.Cmd {
	return func() tea.Msg {
		item, err := m.port.Attach(path)
		return Attached{Item: item, Err: err}
	}
}

func (m Model) Update(message tea.Msg) (Model, *Outcome) {
	switch message := message.(type) {
	case Loaded:
		m.Set(message.Items)
		return m, nil
	case Attached:
		if message.Err != nil {
			return m, &Outcome{Err: message.Err}
		}
		m.items = append(m.items, message.Item)
		item := message.Item
		return m, &Outcome{Attached: &item}
	default:
		return m, nil
	}
}

func (m *Model) Set(items []Item) { m.items = append([]Item(nil), items...) }

func (m Model) Items() []Item { return append([]Item(nil), m.items...) }

func (m Model) View() string {
	if len(m.items) == 0 {
		return ""
	}
	names := make([]string, 0, len(m.items))
	for _, item := range m.items {
		names = append(names, item.Name)
	}
	return lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Italic(true).Render(" Attachments: " + strings.Join(names, ", "))
}
