package main

import (
	"encoding/json"
	"net"
	"path/filepath"
	"time"
)

// Send connects to the daemon Unix socket, writes the envelope as a JSON line,
// and closes the connection. Returns an error if the socket is unreachable or
// the write fails.
func Send(envelope map[string]interface{}) error {
	sockPath := filepath.Join(runtimeDir(), "daemon.sock")

	conn, err := net.DialTimeout("unix", sockPath, 200*time.Millisecond)
	if err != nil {
		return err
	}
	defer conn.Close()

	data, err := json.Marshal(envelope)
	if err != nil {
		return err
	}

	// Write JSON line (envelope + newline).
	data = append(data, '\n')
	_, err = conn.Write(data)
	return err
}
