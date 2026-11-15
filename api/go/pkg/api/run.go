package api

import (
	"encoding/json"
	"net/http"
	"os"
	"os/exec"
)

// handleRun executes a compound single-call Android pipeline.
func (r *Router) handleRun(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON body: "+err.Error(), http.StatusBadRequest)
		return
	}

	if _, ok := body["serial"]; !ok {
		body["serial"] = r.cfg.Serial
	}
	if _, ok := body["artemis_url"]; !ok && r.cfg.ArtemisURL != "" {
		body["artemis_url"] = r.cfg.ArtemisURL
	}

	// Create temporary pipeline specification file
	tmpFile, err := os.CreateTemp("", "agentdroid-pipeline-*.json")
	if err != nil {
		sendError(w, "Failed to allocate temp pipeline spec: "+err.Error(), http.StatusInternalServerError)
		return
	}
	defer os.Remove(tmpFile.Name())

	if err := json.NewEncoder(tmpFile).Encode(body); err != nil {
		_ = tmpFile.Close()
		sendError(w, "Failed to serialize pipeline spec: "+err.Error(), http.StatusInternalServerError)
		return
	}
	_ = tmpFile.Close()

	// Execute compound pipeline in one call
	cmd := exec.Command(r.cfg.AgentDroidCLI, "pipeline", tmpFile.Name(), "--json")
	out, err := cmd.CombinedOutput()

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if err != nil {
		// Even on non-zero exit, agentdroid emits JSON report with ok=false and failure details
		var parsed map[string]any
		if jsonErr := json.Unmarshal(out, &parsed); jsonErr == nil {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(out)
			return
		}
		w.WriteHeader(http.StatusInternalServerError)
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
