# AgentDroid Modular Go REST API Server & Go SDK

High-performance, modular Go REST API server and typed Go SDK client for **AgentDroid**.

---

## Architecture & Modular Handlers

The Go server is split into clean, modular domain handlers under `pkg/api/`:

| Handler File | Description | Endpoints Handled |
| :--- | :--- | :--- |
| `router.go` | Route registration, CORS middleware, API key auth | Middleware & root router |
| `health.go` | Vitality & diagnostics | `GET /health`, `GET /api/v1/health`, `GET /api/v1/doctor` |
| `run.go` | Compound single-call pipeline execution | `POST /api/v1/run` |
| `do.go` | Step-by-step semantic UI actions | `POST /api/v1/do` |
| `ui.go` | Compact ~150-token UI dumps & gestures | `GET /api/v1/ui/dump`, `POST /api/v1/ui/tap`, `POST /api/v1/ui/type`, `POST /api/v1/ui/key`, `GET /api/v1/ui/screenshot` |
| `device.go` | Clipboard, notifications, URLs, apps | `GET /api/v1/device/info`, `GET/POST /api/v1/device/clipboard`, `GET /api/v1/device/notifications`, `POST /api/v1/device/open-url`, `GET /api/v1/apps`, `POST /api/v1/app/install` |
| `playground.go`| Embedded developer web console | `GET /`, `GET /playground` |

---

## Starting the Go Server

```bash
cd api/go
go run ./cmd/agentdroid-server --port 8080
```

Flags:
- `--host`: Host to bind (default: `0.0.0.0` or env `AGENTDROID_HOST`)
- `--port`: Port to listen on (default: `8080` or env `AGENTDROID_PORT`)
- `--api-key`: Optional API key required via `X-API-Key` or `Authorization: Bearer`
- `--serial`: Target ADB serial (default: `127.0.0.1:5555` or env `REDROID_ADDR`)

---

## Using the Go Client SDK

```go
package main

import (
	"context"
	"fmt"
	"github.com/theajmalrazaq/agentdroid/api/go/pkg/client"
)

func main() {
	c := client.NewClient("http://localhost:8080", "")

	// 1. Run a compound pipeline
	res, err := c.Run(context.Background(), &client.RunRequest{
		OpenURL: "https://news.ycombinator.com",
		Do:      []string{"scroll:down", "click:Past"},
	})
	if err != nil {
		panic(err)
	}
	fmt.Printf("Success: %v in %vs\n", res.OK, res.DurationSec)

	// 2. Dump screen UI in ~150 tokens
	ui, _ := c.DumpUI(context.Background())
	fmt.Printf("Visible elements: %d\n", ui.ElementCount)
}
```
