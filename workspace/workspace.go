package workspace

import (
	"encoding/base64"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"super-agent/runtime/session"
)

type Workspace struct{}

func (Workspace) ReadAttachment(path string) (session.Attachment, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return session.Attachment{}, err
	}
	if _, err := capture(absolute); err != nil {
		return session.Attachment{}, err
	}
	info, err := os.Stat(absolute)
	if err != nil {
		return session.Attachment{}, err
	}
	if info.Size() > 10<<20 {
		return session.Attachment{}, errors.New("attachment exceeds 10 MiB")
	}
	content, err := os.ReadFile(absolute)
	if err != nil {
		return session.Attachment{}, err
	}
	mime := http.DetectContentType(content)
	return session.Attachment{Name: filepath.Base(absolute), MIME: mime, Data: base64.StdEncoding.EncodeToString(content)}, nil
}

func (Workspace) WriteExport(relative string, content []byte) (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	path := filepath.Join(cwd, relative)
	rel, err := filepath.Rel(cwd, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", errors.New("export path is outside working directory")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return "", err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".export-*")
	if err != nil {
		return "", err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		_ = temporary.Close()
		return "", err
	}
	if _, err := temporary.Write(content); err != nil {
		_ = temporary.Close()
		return "", err
	}
	if err := temporary.Close(); err != nil {
		return "", err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return "", err
	}
	return path, nil
}

func (Workspace) Capture(paths []string) ([]session.FileSnapshot, error) {
	files := make([]session.FileSnapshot, 0, len(paths))
	for _, path := range paths {
		file, err := capture(path)
		if err != nil {
			return nil, err
		}
		files = append(files, file)
	}
	return files, nil
}

func capture(path string) (session.FileSnapshot, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return session.FileSnapshot{}, err
	}
	cwd, err := os.Getwd()
	if err != nil {
		return session.FileSnapshot{}, err
	}
	cwd, err = filepath.Abs(cwd)
	if err != nil {
		return session.FileSnapshot{}, err
	}
	rel, err := filepath.Rel(cwd, abs)
	if err != nil {
		return session.FileSnapshot{}, err
	}
	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return session.FileSnapshot{}, errors.New("checkpoint path is outside working directory")
	}
	info, err := os.Stat(abs)
	if errors.Is(err, os.ErrNotExist) {
		return session.FileSnapshot{Path: abs, Exists: false}, nil
	}
	if err != nil {
		return session.FileSnapshot{}, err
	}
	content, err := os.ReadFile(abs)
	if err != nil {
		return session.FileSnapshot{}, err
	}
	return session.FileSnapshot{Path: abs, Exists: true, Content: string(content), Mode: uint32(info.Mode().Perm())}, nil
}

func (Workspace) Restore(files []session.FileSnapshot) error {
	for _, file := range files {
		if !file.Exists {
			if err := os.Remove(file.Path); err != nil && !errors.Is(err, os.ErrNotExist) {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(file.Path), 0755); err != nil {
			return err
		}
		mode := os.FileMode(file.Mode)
		if mode == 0 {
			mode = 0644
		}
		if err := os.WriteFile(file.Path, []byte(file.Content), mode); err != nil {
			return err
		}
	}
	return nil
}
