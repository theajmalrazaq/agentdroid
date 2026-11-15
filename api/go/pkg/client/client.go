package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client is a typed Go SDK client for the AgentDroid Cloud REST API.
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

// NewClient constructs an AgentDroid API client.
func NewClient(baseURL, apiKey string) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  apiKey,
		httpClient: &http.Client{
			Timeout: 120 * time.Second,
		},
	}
}

// RunRequest defines the payload for a compound single-call Android pipeline.
type RunRequest struct {
	OpenURL       string   `json:"open_url,omitempty"`
	Install       []string `json:"install,omitempty"`
	Launch        string   `json:"launch,omitempty"`
	Do            []string `json:"do,omitempty"`
	AssertText    []string `json:"assert_text,omitempty"`
	Notifications bool     `json:"notifications,omitempty"`
	Clipboard     string   `json:"clipboard,omitempty"`
	GetClipboard  bool     `json:"get_clipboard,omitempty"`
	Serial        string   `json:"serial,omitempty"`
}

// RunResponse holds the execution report of a compound pipeline.
type RunResponse struct {
	OK            bool             `json:"ok"`
	Mode          string           `json:"mode"`
	Device        string           `json:"device"`
	DurationSec   float64          `json:"duration_sec"`
	InstalledAPKs []map[string]any `json:"installed_apks"`
	OpenedURLs    []map[string]any `json:"opened_urls"`
	Clipboard     *string          `json:"clipboard"`
	Notifications []map[string]any `json:"notifications"`
	UISummary     map[string]any   `json:"ui_summary"`
	Errors        []string         `json:"errors"`
}

// UIDumpResponse holds the token-efficient compact UI tree (~150 tokens).
type UIDumpResponse struct {
	OK           bool             `json:"ok"`
	ElementCount int              `json:"element_count"`
	Elements     []map[string]any `json:"elements"`
	Foreground   map[string]any   `json:"foreground"`
}

func (c *Client) sendRequest(ctx context.Context, method, path string, body any, dest any) error {
	var bodyReader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("serialize request body: %w", err)
		}
		bodyReader = bytes.NewReader(raw)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bodyReader)
	if err != nil {
		return fmt.Errorf("create http request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("X-API-Key", c.apiKey)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("http execute: %w", err)
	}
	defer resp.Body.Close()

	respBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("agentdroid api error (status %d): %s", resp.StatusCode, string(respBytes))
	}

	if dest != nil {
		if err := json.Unmarshal(respBytes, dest); err != nil {
			return fmt.Errorf("unmarshal response: %w", err)
		}
	}
	return nil
}

// Run executes a compound Android workflow in one call.
func (c *Client) Run(ctx context.Context, r *RunRequest) (*RunResponse, error) {
	var out RunResponse
	if err := c.sendRequest(ctx, http.MethodPost, "/api/v1/run", r, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Do executes one or more semantic UI actions sequentially.
func (c *Client) Do(ctx context.Context, actions ...string) (map[string]any, error) {
	var out map[string]any
	payload := map[string]any{"actions": actions}
	if err := c.sendRequest(ctx, http.MethodPost, "/api/v1/do", payload, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// DumpUI fetches the compact visible screen elements (~150 tokens).
func (c *Client) DumpUI(ctx context.Context) (*UIDumpResponse, error) {
	var out UIDumpResponse
	if err := c.sendRequest(ctx, http.MethodGet, "/api/v1/ui/dump", nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// OpenURL opens a web page or deep link on the Android device.
func (c *Client) OpenURL(ctx context.Context, url string) error {
	payload := map[string]any{"url": url}
	return c.sendRequest(ctx, http.MethodPost, "/api/v1/device/open-url", payload, nil)
}

// GetClipboard reads the Android clipboard text.
func (c *Client) GetClipboard(ctx context.Context) (string, error) {
	var out struct {
		Clipboard string `json:"clipboard"`
	}
	if err := c.sendRequest(ctx, http.MethodGet, "/api/v1/device/clipboard", nil, &out); err != nil {
		return "", err
	}
	return out.Clipboard, nil
}

// SetClipboard sets the Android clipboard text.
func (c *Client) SetClipboard(ctx context.Context, text string) error {
	payload := map[string]any{"text": text}
	return c.sendRequest(ctx, http.MethodPost, "/api/v1/device/clipboard", payload, nil)
}
