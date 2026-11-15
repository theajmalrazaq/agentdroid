package api

import (
	"net/http"
	"os/exec"
	"strings"
)

// handleDeviceInfo queries Android properties (model, version, screen).
func (r *Router) handleDeviceInfo(w http.ResponseWriter, req *http.Request) {
	cmd := exec.Command("adb", "-s", r.cfg.Serial, "shell", "getprop", "ro.build.version.release")
	ver, _ := cmd.Output()

	cmdModel := exec.Command("adb", "-s", r.cfg.Serial, "shell", "getprop", "ro.product.model")
	model, _ := cmdModel.Output()

	cmdSize := exec.Command("adb", "-s", r.cfg.Serial, "shell", "wm", "size")
	size, _ := cmdSize.Output()

	cmdDensity := exec.Command("adb", "-s", r.cfg.Serial, "shell", "wm", "density")
	density, _ := cmdDensity.Output()

	sendJSON(w, map[string]any{
		"ok": true,
		"device": map[string]any{
			"serial":          r.cfg.Serial,
			"android_version": strings.TrimSpace(string(ver)),
			"model":           strings.TrimSpace(string(model)),
			"screen_size":     strings.TrimSpace(string(size)),
			"screen_density":  strings.TrimSpace(string(density)),
		},
	}, http.StatusOK)
}

// handleGetClipboard reads the device clipboard.
func (r *Router) handleGetClipboard(w http.ResponseWriter, req *http.Request) {
	cmd := exec.Command(r.cfg.AgentDroidCLI, "device", "clipboard", "-s", r.cfg.Serial, "-j")
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Failed to read clipboard: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleSetClipboard writes text to the Android clipboard.
func (r *Router) handleSetClipboard(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	text, _ := body["text"].(string)
	cmd := exec.Command(r.cfg.AgentDroidCLI, "device", "clipboard", text, "-s", r.cfg.Serial, "-j")
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Failed to set clipboard: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleNotifications reads active notifications from the Android notification listener.
func (r *Router) handleNotifications(w http.ResponseWriter, req *http.Request) {
	args := []string{"device", "notifications", "-s", r.cfg.Serial, "-j"}
	if req.URL.Query().Get("all") == "true" {
		args = append(args, "--all")
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Failed to read notifications: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleOpenURL opens a web URL or deep link on Android.
func (r *Router) handleOpenURL(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	url, _ := body["url"].(string)
	if url == "" {
		url, _ = body["uri"].(string)
	}
	if url == "" {
		sendError(w, "Field 'url' or 'uri' is required", http.StatusBadRequest)
		return
	}

	if err := r.security.ValidateURL(url); err != nil {
		sendError(w, "SecurityGuardrailViolation: "+err.Error(), http.StatusForbidden)
		return
	}

	args := []string{"device", "open", url, "-s", r.cfg.Serial, "-j"}
	if pkg, ok := body["package"].(string); ok && pkg != "" {
		args = append(args, "-p", pkg)
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "Failed to open URL: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}

// handleListApps lists installed 3rd party packages.
func (r *Router) handleListApps(w http.ResponseWriter, req *http.Request) {
	cmd := exec.Command("adb", "-s", r.cfg.Serial, "shell", "pm", "list", "packages", "-3")
	out, err := cmd.Output()
	if err != nil {
		sendError(w, "Failed to list packages: "+err.Error(), http.StatusInternalServerError)
		return
	}

	lines := strings.Split(string(out), "\n")
	var pkgs []string
	for _, l := range lines {
		l = strings.TrimSpace(l)
		if strings.HasPrefix(l, "package:") {
			pkgs = append(pkgs, strings.TrimPrefix(l, "package:"))
		}
	}

	sendJSON(w, map[string]any{
		"ok":       true,
		"packages": pkgs,
		"count":    len(pkgs),
	}, http.StatusOK)
}

// handleInstallApp installs an APK from a URL, local path, or F-Droid package.
func (r *Router) handleInstallApp(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := readJSON(req, &body); err != nil {
		sendError(w, "Invalid JSON: "+err.Error(), http.StatusBadRequest)
		return
	}

	source, _ := body["source"].(string)
	if source == "" {
		source, _ = body["apk"].(string)
	}
	if source == "" {
		sendError(w, "Field 'source' (file, URL, or fdroid:<pkg>) is required", http.StatusBadRequest)
		return
	}

	if strings.HasPrefix(source, "http://") || strings.HasPrefix(source, "https://") {
		if err := r.security.ValidateURL(source); err != nil {
			sendError(w, "SecurityGuardrailViolation: "+err.Error(), http.StatusForbidden)
			return
		}
	} else if !strings.HasPrefix(source, "fdroid:") {
		if err := r.security.ValidateHostPath(source); err != nil {
			sendError(w, "SecurityGuardrailViolation: "+err.Error(), http.StatusForbidden)
			return
		}
	}

	args := []string{"app", "install", source, "-s", r.cfg.Serial, "-j"}
	if body["launch"] == true {
		args = append(args, "--launch")
	}

	cmd := exec.Command(r.cfg.AgentDroidCLI, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		sendError(w, "App installation failed: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(out)
}
