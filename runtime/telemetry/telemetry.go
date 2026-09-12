package telemetry

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Fields map[string]any

type contextKey struct{}
type IDs struct{ RunID, ActionID string }

var sink struct {
	sync.Mutex
	file *os.File
}

func Configure(path string) error {
	sink.Lock()
	defer sink.Unlock()
	if sink.file != nil {
		_ = sink.file.Close()
		sink.file = nil
	}
	if path == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	sink.file = file
	return nil
}

func Close() error {
	sink.Lock()
	defer sink.Unlock()
	if sink.file == nil {
		return nil
	}
	err := sink.file.Close()
	sink.file = nil
	return err
}

func Record(kind string, fields Fields) {
	sink.Lock()
	defer sink.Unlock()
	if sink.file == nil {
		return
	}
	record := make(Fields, len(fields)+2)
	record["time"] = time.Now().UTC().Format(time.RFC3339Nano)
	record["kind"] = kind
	for key, value := range fields {
		record[key] = value
	}
	content, err := json.Marshal(record)
	if err == nil {
		_, _ = sink.file.Write(append(content, '\n'))
	}
}

func WithIDs(ctx context.Context, runID, actionID string) context.Context {
	return context.WithValue(ctx, contextKey{}, IDs{RunID: runID, ActionID: actionID})
}

func IDsFrom(ctx context.Context) IDs {
	ids, _ := ctx.Value(contextKey{}).(IDs)
	return ids
}
