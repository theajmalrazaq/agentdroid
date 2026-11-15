package api

import (
	"encoding/json"
	"net/http"
	"os/exec"
)

// handleDo executes sequential semantic UI actions (click, fill, scroll, key).
func (r *Router) handleDo(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON body: "+err.Error(), http.StatusBadRequest)
		return
	}

	var actions []string
	if act, ok := body["action"].(string); ok && act != "" {
		actions = append(actions, act)
	}
	if acts, ok := body["actions"].([]any); ok {
		for _, a := range acts {
			if s, ok := a.(string); ok && s != "" {
				actions = append(actions, s)
			}
		}
	}
	if d, ok := body["do"].(string); ok && d != "" {
		actions = append(actions, d)
	}
	if dList, ok := body["do"].([]any); ok {
		for _, a := range dList {
			if s, ok := a.(string); ok && s != "" {
				actions = append(actions, s)
			}
		}
	}

	if len(actions) == 0 {
		sendError(w, "Missing 'action' or 'actions' list in request body", http.StatusBadRequest)
		return
	}

	args := []string{"run", "--headless", "-s", r.cfg.Serial, "--json"}
	for _, act := range actions {
		args = append(args, "--do", act)
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, args...)
	out, err := cmd.CombinedOutput()

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	var parsed map[string]any
	if jsonErr := json.Unmarshal(out, &parsed); jsonErr == nil {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(out)
		return
	}

	if err != nil {
		sendJSON(w, map[string]any{
			"ok":     false,
			"error":  err.Error(),
			"output": string(out),
		}, http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}
