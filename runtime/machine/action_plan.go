package machine

// ActionPlan describes how a committed transition updates future work.
type ActionPlan struct {
	ClearExisting bool
	Schedule      []ScheduledAction
}
