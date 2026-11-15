package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"

	"github.com/theajmalrazaq/agentdroid/api/go/pkg/api"
)

func main() {
	defaultPort := 8080
	if envPort := os.Getenv("AGENTDROID_PORT"); envPort != "" {
		if p, err := strconv.Atoi(envPort); err == nil {
			defaultPort = p
		}
	}

	defaultHost := os.Getenv("AGENTDROID_HOST")
	if defaultHost == "" {
		defaultHost = "0.0.0.0"
	}

	host := flag.String("host", defaultHost, "Host address to bind")
	port := flag.Int("port", defaultPort, "HTTP port to listen on")
	apiKey := flag.String("api-key", os.Getenv("AGENTDROID_API_KEY"), "Optional API key for authorization")
	serial := flag.String("serial", os.Getenv("REDROID_ADDR"), "Target Android device serial (default: 127.0.0.1:5555)")
	artemisURL := flag.String("artemis-url", os.Getenv("ARTEMIS_BASE_URL"), "Artemis Controller daemon URL")
	cliPath := flag.String("cli", "agentdroid", "Path to agentdroid CLI executable")
	flag.Parse()

	cfg := &api.Config{
		Host:          *host,
		Port:          *port,
		APIKey:        *apiKey,
		Serial:        *serial,
		ArtemisURL:    *artemisURL,
		AgentDroidCLI: *cliPath,
	}

	router := api.NewRouter(cfg)
	addr := fmt.Sprintf("%s:%d", *host, *port)

	authStatus := "disabled (open access)"
	if *apiKey != "" {
		authStatus = "enabled (X-API-Key required)"
	}

	log.Printf("🚀 [agentdroid:go-server] Listening at http://%s\n", addr)
	log.Printf("   • Device Target:  %s\n", cfg.Serial)
	log.Printf("   • Authentication: %s\n", authStatus)
	log.Printf("   • Playground:     http://%s/playground\n", addr)
	log.Printf("   • REST Health:    http://%s/health\n", addr)
	log.Printf("   • Compound Run:   POST http://%s/api/v1/run\n", addr)

	if err := http.ListenAndServe(addr, router); err != nil {
		log.Fatalf("Server exited: %v", err)
	}
}
