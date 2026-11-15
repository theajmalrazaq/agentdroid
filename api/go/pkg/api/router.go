package api

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

// Config holds runtime configuration for the AgentDroid API server.
type Config struct {
	Host        string
	Port        int
	APIKey      string
	Serial      string
	ArtemisURL  string
	CORSOrigin  string
	AgentDroidCLI string
}

// Router dispatches HTTP requests across modular AgentDroid handlers.
type Router struct {
	cfg      *Config
	mux      *http.ServeMux
	security *SecurityGuardrails
}

// NewRouter initializes modular API routes with CORS and authentication.
func NewRouter(cfg *Config) *Router {
	if cfg.CORSOrigin == "" {
		cfg.CORSOrigin = "*"
	}
	if cfg.Serial == "" {
		cfg.Serial = os.Getenv("REDROID_ADDR")
		if cfg.Serial == "" {
			cfg.Serial = "127.0.0.1:5555"
		}
	}
	if cfg.AgentDroidCLI == "" {
		cfg.AgentDroidCLI = "agentdroid"
	}

	secEnabled := os.Getenv("AGENTDROID_SECURITY_MODE") != "off"
	r := &Router{
		cfg:      cfg,
		mux:      http.NewServeMux(),
		security: NewSecurityGuardrails(secEnabled),
	}

	r.registerRoutes()
	return r
}

func (r *Router) registerRoutes() {
	// Public & Health
	r.mux.HandleFunc("GET /", r.handlePlayground)
	r.mux.HandleFunc("GET /playground", r.handlePlayground)
	r.mux.HandleFunc("GET /health", r.handleHealth)
	r.mux.HandleFunc("GET /api/v1/health", r.handleHealth)
	r.mux.HandleFunc("GET /api/v1/doctor", r.handleDoctor)

	// Compound Pipeline Execution
	r.mux.HandleFunc("POST /api/v1/run", r.withAuth(r.handleRun))

	// Semantic UI Actions
	r.mux.HandleFunc("POST /api/v1/do", r.withAuth(r.handleDo))

	// UI Tree & Gestures
	r.mux.HandleFunc("GET /api/v1/ui/dump", r.withAuth(r.handleUIDump))
	r.mux.HandleFunc("POST /api/v1/ui/tap", r.withAuth(r.handleUITap))
	r.mux.HandleFunc("POST /api/v1/ui/type", r.withAuth(r.handleUIType))
	r.mux.HandleFunc("POST /api/v1/ui/key", r.withAuth(r.handleUIKey))
	r.mux.HandleFunc("GET /api/v1/ui/screenshot", r.withAuth(r.handleUIScreenshot))

	// Device State & Apps
	r.mux.HandleFunc("GET /api/v1/device/info", r.withAuth(r.handleDeviceInfo))
	r.mux.HandleFunc("GET /api/v1/info", r.withAuth(r.handleDeviceInfo))
	r.mux.HandleFunc("GET /api/v1/device/clipboard", r.withAuth(r.handleGetClipboard))
	r.mux.HandleFunc("POST /api/v1/device/clipboard", r.withAuth(r.handleSetClipboard))
	r.mux.HandleFunc("GET /api/v1/device/notifications", r.withAuth(r.handleNotifications))
	r.mux.HandleFunc("POST /api/v1/device/open-url", r.withAuth(r.handleOpenURL))
	r.mux.HandleFunc("GET /api/v1/apps", r.withAuth(r.handleListApps))
	r.mux.HandleFunc("POST /api/v1/app/install", r.withAuth(r.handleInstallApp))
}

// ServeHTTP handles all incoming requests, applying CORS and preflight handling.
func (r *Router) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", r.cfg.CORSOrigin)
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, Accept, Origin")

	if req.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	clientIP := req.RemoteAddr
	if host, _, err := net.SplitHostPort(req.RemoteAddr); err == nil && host != "" {
		clientIP = host
	}
	if err := r.security.ValidateRateLimit(clientIP); err != nil {
		sendError(w, err.Error(), http.StatusTooManyRequests)
		return
	}

	r.mux.ServeHTTP(w, req)
}

// withAuth verifies optional API key in X-API-Key header, Bearer token, or query parameter.
func (r *Router) withAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		if r.cfg.APIKey == "" {
			next(w, req)
			return
		}

		key := req.Header.Get("X-API-Key")
		if key == "" {
			authHeader := req.Header.Get("Authorization")
			if strings.HasPrefix(authHeader, "Bearer ") {
				key = strings.TrimPrefix(authHeader, "Bearer ")
			}
		}
		if key == "" {
			key = req.URL.Query().Get("api_key")
		}

		if key != r.cfg.APIKey {
			sendError(w, "Unauthorized: missing or invalid API key", http.StatusUnauthorized)
			return
		}

		next(w, req)
	}
}

func sendJSON(w http.ResponseWriter, data any, status int) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}

func sendError(w http.ResponseWriter, message string, status int) {
	sendJSON(w, map[string]any{
		"ok":    false,
		"error": message,
		"time":  time.Now().Unix(),
	}, status)
}

func readJSON(req *http.Request, dest any) error {
	if req.Body == nil {
		return fmt.Errorf("empty request body")
	}
	defer req.Body.Close()
	return json.NewDecoder(req.Body).Decode(dest)
}
