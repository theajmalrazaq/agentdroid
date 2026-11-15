package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRouterHealthAndCORS(t *testing.T) {
	cfg := &Config{
		Host:       "127.0.0.1",
		Port:       8080,
		APIKey:     "test-key",
		Serial:     "127.0.0.1:5555",
		CORSOrigin: "*",
	}
	router := NewRouter(cfg)

	// 1. GET /health (Public endpoint, CORS headers)
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}
	if w.Header().Get("Access-Control-Allow-Origin") != "*" {
		t.Fatalf("expected CORS header *, got %s", w.Header().Get("Access-Control-Allow-Origin"))
	}
	body := w.Body.String()
	if !strings.Contains(body, `"status":"online"`) && !strings.Contains(body, `"status": "online"`) {
		t.Fatalf("expected status online in body, got: %s", body)
	}

	// 2. GET /playground (Developer web dashboard)
	reqPlay := httptest.NewRequest(http.MethodGet, "/playground", nil)
	wPlay := httptest.NewRecorder()
	router.ServeHTTP(wPlay, reqPlay)

	if wPlay.Code != http.StatusOK {
		t.Fatalf("expected status 200 for playground, got %d", wPlay.Code)
	}
	if !strings.Contains(wPlay.Body.String(), "AgentDroid") {
		t.Fatalf("expected AgentDroid in playground HTML")
	}

	// 3. GET /api/v1/device/info WITHOUT auth -> 401 Unauthorized
	reqAuth := httptest.NewRequest(http.MethodGet, "/api/v1/device/info", nil)
	wAuth := httptest.NewRecorder()
	router.ServeHTTP(wAuth, reqAuth)

	if wAuth.Code != http.StatusUnauthorized {
		t.Fatalf("expected status 401 without API key, got %d", wAuth.Code)
	}

	// 4. OPTIONS preflight
	reqOptions := httptest.NewRequest(http.MethodOptions, "/api/v1/run", nil)
	wOptions := httptest.NewRecorder()
	router.ServeHTTP(wOptions, reqOptions)

	if wOptions.Code != http.StatusNoContent {
		t.Fatalf("expected status 204 for OPTIONS preflight, got %d", wOptions.Code)
	}
}

func TestSecurityGuardrails(t *testing.T) {
	sg := NewSecurityGuardrails(true)

	// 1. SSRF URL check
	if err := sg.ValidateURL("http://169.254.169.254/latest/meta-data/"); err == nil {
		t.Fatalf("expected error for cloud metadata IP 169.254.169.254")
	}
	if err := sg.ValidateURL("file:///etc/passwd"); err == nil {
		t.Fatalf("expected error for file:// scheme")
	}
	if err := sg.ValidateURL("https://example.com"); err != nil {
		t.Fatalf("expected valid https URL to pass, got: %v", err)
	}

	// 2. Path traversal check
	if err := sg.ValidateHostPath("../../.ssh/id_rsa"); err == nil {
		t.Fatalf("expected error for .ssh path traversal")
	}
	if err := sg.ValidateHostPath("/etc/shadow"); err == nil {
		t.Fatalf("expected error for /etc/shadow")
	}
	if err := sg.ValidateHostPath("./artifacts/notes.md"); err != nil {
		t.Fatalf("expected safe artifacts path to pass, got: %v", err)
	}

	// 3. Shell command validation in safe mode
	if err := sg.ValidateShellCommand("rm -rf /"); err == nil {
		t.Fatalf("expected error for destructive shell command")
	}
}

