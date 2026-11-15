package api

import (
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

var (
	// Blocked networks (loopback, cloud metadata, RFC1918)
	blockedCIDRs = []string{
		"127.0.0.0/8",
		"169.254.0.0/16", // AWS, GCP, Azure, Hetzner, DO metadata service
		"10.0.0.0/8",
		"172.16.0.0/12",
		"192.168.0.0/16",
		"::1/128",
		"fc00::/7",
		"fe80::/10",
	}

	dangerousShellPatterns = []*regexp.Regexp{
		regexp.MustCompile(`\brm\s+-[rf]{1,2}\s+/`),
		regexp.MustCompile(`\bmkfs\b`),
		regexp.MustCompile(`\bdd\s+if=`),
		regexp.MustCompile(`:\(\)\s*\{\s*:\|:&\s*\};:`),
		regexp.MustCompile(`\breboot\b`),
		regexp.MustCompile(`\bshutdown\b`),
		regexp.MustCompile(`\bpoweroff\b`),
		regexp.MustCompile(`\bsetenforce\s+0\b`),
		regexp.MustCompile(`\bmount\s+-[o\s]*remount`),
		regexp.MustCompile(`\bwipe\s+data\b`),
		regexp.MustCompile(`/system/bin/sh\s+-i`),
		regexp.MustCompile(`\bnc\s+-[le]`),
		regexp.MustCompile(`\b/dev/tcp/`),
	}

	sensitivePathPatterns = []*regexp.Regexp{
		regexp.MustCompile(`\.env($|\.)`),
		regexp.MustCompile(`\.ssh($|/)`),
		regexp.MustCompile(`\.git($|/)`),
		regexp.MustCompile(`\.netrc`),
		regexp.MustCompile(`/etc/shadow`),
		regexp.MustCompile(`/etc/passwd`),
		regexp.MustCompile(`/proc/`),
		regexp.MustCompile(`/sys/`),
		regexp.MustCompile(`\.\./`),
		regexp.MustCompile(`/\.\.`),
	}
)

// SecurityGuardrails enforces security policies on incoming web requests.
type SecurityGuardrails struct {
	Enabled             bool
	AllowPrivateNetworks bool
	AllowShell          bool
	parsedCIDRs         []*net.IPNet
	limiter             *RateLimiter
}

// NewSecurityGuardrails constructs guardrails with parsed IP networks.
func NewSecurityGuardrails(enabled bool) *SecurityGuardrails {
	sg := &SecurityGuardrails{
		Enabled:             enabled,
		AllowPrivateNetworks: false,
		AllowShell:          false,
		limiter:             NewRateLimiter(60, time.Minute),
	}

	for _, cidr := range blockedCIDRs {
		_, ipNet, err := net.ParseCIDR(cidr)
		if err == nil {
			sg.parsedCIDRs = append(sg.parsedCIDRs, ipNet)
		}
	}
	return sg
}

// ValidateRateLimit checks if client IP is within rate limits.
func (sg *SecurityGuardrails) ValidateRateLimit(clientIP string) error {
	if !sg.Enabled {
		return nil
	}
	if !sg.limiter.Allow(clientIP) {
		return fmt.Errorf("rate limit exceeded: max 60 requests per minute")
	}
	return nil
}

// ValidateURL validates URLs to prevent SSRF and cloud metadata access.
func (sg *SecurityGuardrails) ValidateURL(rawURL string) error {
	if !sg.Enabled {
		return nil
	}

	u, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return fmt.Errorf("invalid URL format: %w", err)
	}

	scheme := strings.ToLower(u.Scheme)
	if scheme != "http" && scheme != "https" && scheme != "market" && scheme != "geo" && scheme != "tel" {
		return fmt.Errorf("URL scheme '%s' is prohibited by security guardrails (allowed: http, https, market, geo, tel)", scheme)
	}

	if scheme == "http" || scheme == "https" {
		hostname := strings.ToLower(u.Hostname())
		if hostname == "" {
			return fmt.Errorf("empty host in URL")
		}

		if hostname == "metadata.google.internal" || hostname == "instance-data" || hostname == "metadata" {
			return fmt.Errorf("access to cloud metadata endpoints is prohibited")
		}

		if !sg.AllowPrivateNetworks {
			ips, err := net.LookupIP(hostname)
			if err == nil {
				for _, ip := range ips {
					for _, block := range sg.parsedCIDRs {
						if block.Contains(ip) {
							return fmt.Errorf("access to private/metadata IP %s (%s) is blocked by security guardrails", ip.String(), hostname)
						}
					}
				}
			}
		}
	}

	return nil
}

// ValidateHostPath blocks directory traversal and sensitive host file inspection.
func (sg *SecurityGuardrails) ValidateHostPath(p string) error {
	if !sg.Enabled {
		return nil
	}
	clean := strings.ReplaceAll(p, `\`, `/`)
	for _, pattern := range sensitivePathPatterns {
		if pattern.MatchString(clean) {
			return fmt.Errorf("access to path matching '%s' is blocked by security guardrails", pattern.String())
		}
	}
	return nil
}

// ValidateShellCommand checks for destructive root shell commands.
func (sg *SecurityGuardrails) ValidateShellCommand(cmd string) error {
	if !sg.Enabled {
		return nil
	}
	if !sg.AllowShell {
		return fmt.Errorf("direct shell commands are disabled in web security mode; use semantic UI actions instead")
	}
	for _, pattern := range dangerousShellPatterns {
		if pattern.MatchString(cmd) {
			return fmt.Errorf("command contains prohibited pattern (%s)", pattern.String())
		}
	}
	return nil
}

// RateLimiter manages per-client rate buckets.
type RateLimiter struct {
	mu       sync.Mutex
	history  map[string][]time.Time
	maxLimit int
	window   time.Duration
}

// NewRateLimiter creates an in-memory sliding window rate limiter.
func NewRateLimiter(maxLimit int, window time.Duration) *RateLimiter {
	return &RateLimiter{
		history:  make(map[string][]time.Time),
		maxLimit: maxLimit,
		window:   window,
	}
}

// Allow returns true if the client is allowed to proceed.
func (rl *RateLimiter) Allow(clientID string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-rl.window)

	var valid []time.Time
	for _, t := range rl.history[clientID] {
		if t.After(cutoff) {
			valid = append(valid, t)
		}
	}

	if len(valid) >= rl.maxLimit {
		rl.history[clientID] = valid
		return false
	}

	valid = append(valid, now)
	rl.history[clientID] = valid
	return true
}
