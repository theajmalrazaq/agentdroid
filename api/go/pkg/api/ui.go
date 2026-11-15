package api

import (
	"encoding/base64"
	"fmt"
	"net/http"
	"os/exec"
	"strconv"
)

// handleUIDump dumps the token-efficient compact visible UI tree (~150 tokens).
func (r *Router) handleUIDump(w http.ResponseWriter, req *http.Request) {
	maxEl := req.URL.Query().Get("max_elements")
	if maxEl == "" {
		maxEl = "60"
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, "ui", "dump", "-s", r.cfg.Serial, "--max-elements", maxEl, "-j")
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Failed to dump UI hierarchy: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleUITap taps screen coordinates (x, y).
func (r *Router) handleUITap(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	x, okX := body["x"].(float64)
	y, okY := body["y"].(float64)
	if !okX || !okY {
		sendError(w, "Fields 'x' and 'y' must be numbers", http.StatusBadRequest)
		return
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, "ui", "tap", fmt.Sprintf("%.0f", x), fmt.Sprintf("%.0f", y), "-s", r.cfg.Serial, "-j")
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Tap failed: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleUIType inputs text into the currently focused field.
func (r *Router) handleUIType(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	text, _ := body["text"].(string)
	cmd := exec.Command(r.cfg.AgentDroidCLI, "ui", "type", text, "-s", r.cfg.Serial, "-j")
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Type failed: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleUIKey sends a global action or hardware key (HOME, BACK, RECENTS, ENTER).
func (r *Router) handleUIKey(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	key, _ := body["key"].(string)
	if key == "" {
		key = "BACK"
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, "ui", "key", key, "-s", r.cfg.Serial, "-j")
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Key event failed: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleUIScreenshot captures a live screenshot as PNG or base64.
func (r *Router) handleUIScreenshot(w http.ResponseWriter, req *http.Request) {
	cmd := exec.Command("adb", "-s", r.cfg.Serial, "exec-out", "screencap", "-p")
	pngBytes, err := cmd.Output()
	if err != nil {
		sendError(w, "Failed to capture screenshot: "+err.Error(), http.StatusInternalServerError)
		return
	}

	if req.URL.Query().Get("format") == "base64" {
		sendJSON(w, map[string]any{
			"ok":           true,
			"format":       "base64",
			"image_base64": base64.StdEncoding.EncodeToString(pngBytes),
		}, http.StatusOK)
		return
	}

	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Content-Length", strconv.Itoa(len(pngBytes)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(pngBytes)
}
