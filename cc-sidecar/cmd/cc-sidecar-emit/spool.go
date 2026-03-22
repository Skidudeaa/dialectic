package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const maxSpoolFileSize = 50 * 1024 * 1024 // 50 MB

// SpoolWrite appends the envelope as a JSON line to a spool file.
// File naming: <session_id>-<pid>.jsonl
// Best-effort telemetry — no fdatasync, errors are silently ignored.
func SpoolWrite(envelope map[string]interface{}, sessionID string) {
	spoolDir := filepath.Join(runtimeDir(), "spool")
	if err := os.MkdirAll(spoolDir, 0700); err != nil {
		return
	}

	filename := fmt.Sprintf("%s-%d.jsonl", sessionID, os.Getpid())
	path := filepath.Join(spoolDir, filename)

	// Check existing file size before writing.
	if info, err := os.Stat(path); err == nil {
		if info.Size() >= maxSpoolFileSize {
			return // Refuse to write — file too large.
		}
	}

	data, err := json.Marshal(envelope)
	if err != nil {
		return
	}
	data = append(data, '\n')

	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600)
	if err != nil {
		return
	}
	defer f.Close()

	_, _ = f.Write(data)
}
