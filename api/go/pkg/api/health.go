package api

import (
	"net/http"
	"os/exec"
	"strings"
	"time"
)

// handleHealth returns basic service vitality and device connection status.
func (r *Router) handleHealth(w http.ResponseWriter, req *http.Request) {
	connected := r.isDeviceConnected()

	sendJSON(w, map[string]any{
		"ok":               true,
		"status":           "online",
		"service":          "agentdroid",
		"version":          "0.2.0",
		"engine":           "go",
		"device":           r.cfg.Serial,
		"device_connected": connected,
		"timestamp":        time.Now().Unix(),
	}, http.StatusOK)
}

// handleDoctor performs system checks (ADB, kernel modules, device state).
func (r *Router) handleDoctor(w http.ResponseWriter, req *http.Request) {
	cmd := exec.Command(r.cfg.AgentDroidCLI, "doctor", "--json", "-s", r.cfg.Serial)
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendJSON(w, map[string]any{
			"ok":     false,
			"error":  err.Error(),
			"output": string(out),
		}, http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

func (r *Router) isDeviceConnected() bool {
	cmd := exec.Command("adb", "-s", r.cfg.Serial, "get-state")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) == "device"
}
