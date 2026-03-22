package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const emitterVersion = "0.1.0"

// Wrap adds envelope metadata to the upstream payload.
// It returns a new map containing the original payload under "payload"
// plus top-level metadata fields.
func Wrap(payload map[string]interface{}, subagentFlag bool) map[string]interface{} {
	now := time.Now().UnixMilli()

	// Extract session_id from the payload if present.
	sessionID, _ := payload["session_id"].(string)

	// Extract agent_id from the payload if present.
	agentID, _ := payload["agent_id"].(string)

	// Determine subagent status.
	isSubagent := subagentFlag || agentID != ""

	// Normalize tool_name: "Task" → "Agent".
	if tn, ok := payload["tool_name"].(string); ok && tn == "Task" {
		payload["tool_name"] = "Agent"
	}

	// Get monotonic sequence number.
	seq := nextSeq()

	env := map[string]interface{}{
		"received_at_ms":  now,
		"mono_seq":        seq,
		"emitter_version": emitterVersion,
		"is_subagent":     isSubagent,
		"payload":         payload,
	}

	if sessionID != "" {
		env["session_id"] = sessionID
	}
	if agentID != "" {
		env["agent_id"] = agentID
	}

	return env
}

// runtimeDir returns $XDG_RUNTIME_DIR/cc-sidecar, creating it if needed.
func runtimeDir() string {
	base := os.Getenv("XDG_RUNTIME_DIR")
	if base == "" {
		base = fmt.Sprintf("/tmp/runtime-%d", os.Getuid())
	}
	dir := filepath.Join(base, "cc-sidecar")
	_ = os.MkdirAll(dir, 0700)
	return dir
}

// nextSeq atomically increments a file-based counter using flock.
// Returns the new sequence number, or 0 on any error.
func nextSeq() int64 {
	seqPath := filepath.Join(runtimeDir(), "seq")

	f, err := os.OpenFile(seqPath, os.O_RDWR|os.O_CREATE, 0600)
	if err != nil {
		return 0
	}
	defer f.Close()

	// Acquire exclusive lock.
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return 0
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)

	// Read current value.
	data := make([]byte, 64)
	n, _ := f.Read(data)
	current := int64(0)
	if n > 0 {
		val := strings.TrimSpace(string(data[:n]))
		if parsed, err := strconv.ParseInt(val, 10, 64); err == nil {
			current = parsed
		}
	}

	// Increment and write back.
	next := current + 1
	_ = f.Truncate(0)
	_, _ = f.Seek(0, 0)
	_, _ = f.WriteString(strconv.FormatInt(next, 10))

	return next
}
