// cc-sidecar-emit: fire-and-forget CLI invoked by Claude Code hooks on every event.
// ARCHITECTURE: Optimised for <10ms wall-clock. No stdout, always exit 0.
// WHY: Hooks must never slow the interactive loop or surface errors to the user.
package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
)

func main() {
	// Guarantee exit 0 — we are telemetry, never break the host.
	defer os.Exit(0)

	// Recover from any panic so the hook never crashes.
	defer func() { _ = recover() }()

	// Immediately silence stdout so nothing leaks to the calling process.
	devNull, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err == nil {
		os.Stdout = devNull
		defer devNull.Close()
	}

	// Parse --subagent flag from os.Args.
	isSubagentFlag := false
	for _, arg := range os.Args[1:] {
		if arg == "--subagent" {
			isSubagentFlag = true
			break
		}
	}

	// Read all of stdin.
	raw, err := io.ReadAll(os.Stdin)
	if err != nil || len(raw) == 0 {
		return
	}

	// Parse JSON; if invalid, wrap in {"_raw": "..."}.
	var payload map[string]interface{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		payload = map[string]interface{}{
			"_raw": string(raw),
		}
	}

	// Extract hook_event name from the payload.
	hookEvent, _ := payload["hook_event_name"].(string)

	// Compute dedup_hash over the upstream payload only (before envelope).
	canonical, _ := json.Marshal(payload)
	hash := sha256.Sum256(canonical)
	dedupHash := fmt.Sprintf("%x", hash)

	// Wrap with envelope metadata.
	envelope := Wrap(payload, isSubagentFlag)
	envelope["dedup_hash"] = dedupHash
	if hookEvent != "" {
		envelope["hook_event"] = hookEvent
	}

	// Redact secrets from the entire envelope.
	Redact(envelope)

	// Extract session_id for spool file naming.
	sessionID, _ := envelope["session_id"].(string)
	if sessionID == "" {
		sessionID = "unknown"
	}

	// Try the Unix socket first; fall back to spool file.
	if err := Send(envelope); err != nil {
		SpoolWrite(envelope, sessionID)
	}
}
