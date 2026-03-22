package main

import (
	"regexp"
)

const redactedPlaceholder = "[REDACTED]"

// Compiled regex patterns for secret detection.
var secretPatterns = []*regexp.Regexp{
	// Anthropic API keys
	regexp.MustCompile(`sk-ant-[A-Za-z0-9_\-]{10,}`),
	// Generic sk- keys (20+ chars after prefix)
	regexp.MustCompile(`sk-[A-Za-z0-9_\-]{20,}`),
	// GitHub personal access tokens
	regexp.MustCompile(`ghp_[A-Za-z0-9]{30,}`),
	// GitHub OAuth tokens
	regexp.MustCompile(`gho_[A-Za-z0-9]{30,}`),
	// pa- prefixed tokens (20+ chars after prefix)
	regexp.MustCompile(`pa-[A-Za-z0-9_\-]{20,}`),
	// Bearer tokens
	regexp.MustCompile(`Bearer\s+[A-Za-z0-9_\-\.]{10,}`),
	// Authorization header values
	regexp.MustCompile(`(?i)Authorization:\s*\S+`),
	// Environment variable assignments with sensitive names
	regexp.MustCompile(`(?i)export\s+\w*KEY\w*=\S+`),
	regexp.MustCompile(`(?i)export\s+\w*SECRET\w*=\S+`),
	regexp.MustCompile(`(?i)export\s+\w*TOKEN\w*=\S+`),
	regexp.MustCompile(`(?i)export\s+\w*PASSWORD\w*=\S+`),
	// Env var assignments without export
	regexp.MustCompile(`(?i)\w*SECRET\w*=[^\s"']+`),
	regexp.MustCompile(`(?i)\w*TOKEN\w*=[^\s"']+`),
	regexp.MustCompile(`(?i)\w*PASSWORD\w*=[^\s"']+`),
	regexp.MustCompile(`(?i)\w*KEY\w*=[^\s"']+`),
	// Connection strings
	regexp.MustCompile(`postgres://[^\s"']+`),
	regexp.MustCompile(`postgresql://[^\s"']+`),
	regexp.MustCompile(`mysql://[^\s"']+`),
	regexp.MustCompile(`mongodb://[^\s"']+`),
	regexp.MustCompile(`mongodb\+srv://[^\s"']+`),
}

// Redact walks a map[string]interface{} recursively and replaces any string
// values (or string elements in slices) that match known secret patterns.
func Redact(m map[string]interface{}) {
	for k, v := range m {
		switch val := v.(type) {
		case string:
			m[k] = redactString(val)
		case map[string]interface{}:
			Redact(val)
		case []interface{}:
			redactSlice(val)
		}
	}
}

// redactSlice walks a slice recursively, redacting string elements in place.
func redactSlice(s []interface{}) {
	for i, v := range s {
		switch val := v.(type) {
		case string:
			s[i] = redactString(val)
		case map[string]interface{}:
			Redact(val)
		case []interface{}:
			redactSlice(val)
		}
	}
}

// redactString applies all secret patterns to a single string value.
func redactString(s string) string {
	for _, pat := range secretPatterns {
		s = pat.ReplaceAllString(s, redactedPlaceholder)
	}
	return s
}
