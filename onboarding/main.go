// Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
//
// onboarding-sse — Real-time onboarding status via Server-Sent Events.
// Streams signup verification status to watchlist.html after a user signs up.
// Polls watcher data every 2s, sends SSE events, closes on verify or timeout.
// HGR

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

var (
	watchersPath string
	listenAddr   = "127.0.0.1:5002"
	pollInterval = 2 * time.Second
	nudgeAfter   = 30 * time.Second
	maxTimeout   = 10 * time.Minute
)

type sseEvent struct {
	Status       string `json:"status"`
	Message      string `json:"message"`
	Step         int    `json:"step"`
	DashboardURL string `json:"dashboard_url,omitempty"`
}

func init() {
	dataDir := os.Getenv("DW_DATA_DIR")
	if dataDir == "" {
		dataDir = "data"
	}
	watchersPath = filepath.Join(dataDir, "watchers"+".json")
}

func sendSSE(w http.ResponseWriter, event sseEvent) {
	data, _ := json.Marshal(event)
	fmt.Fprintf(w, "data: %s\n\n", data)
	if f, ok := w.(http.Flusher); ok {
		f.Flush()
	}
}

func handleOnboarding(w http.ResponseWriter, r *http.Request) {
	// Extract watcher ID from /api/onboarding/{id}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/onboarding/"), "/")
	id := parts[0]
	if id == "" {
		http.Error(w, "missing watcher id", http.StatusBadRequest)
		return
	}

	// SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.Header().Set("Access-Control-Allow-Origin", "https://instockornot.club")

	log.Printf("[%s] SSE connection opened", id)

	// Check if watcher exists at all
	watcher, err := findWatcher(watchersPath, id)
	if err != nil {
		log.Printf("[%s] Error reading watchers: %v", id, err)
		sendSSE(w, sseEvent{Status: "error", Message: "Unable to check status. Try refreshing.", Step: 0})
		return
	}
	if watcher == nil {
		sendSSE(w, sseEvent{Status: "error", Message: "Watch not found.", Step: 0})
		return
	}

	// Already verified? Send immediate success and close
	if watcher.Active {
		dashURL := fmt.Sprintf("/my-alerts.html?token=%s", watcher.UnsubscribeToken)
		sendSSE(w, sseEvent{Status: "verified", Message: "You're live! Email alerts are active — we'll text you when a drop hits so you know to check it.", Step: 3, DashboardURL: dashURL})
		log.Printf("[%s] Already verified, closing", id)
		return
	}

	// Send initial pending status
	sendSSE(w, sseEvent{Status: "pending", Message: "Watch created — check your email for the verification link. Check spam too — we're new.", Step: 1})

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	deadline := time.After(maxTimeout)
	nudgeTimer := time.After(nudgeAfter)
	nudgeSent := false

	for {
		select {
		case <-r.Context().Done():
			log.Printf("[%s] Client disconnected", id)
			return

		case <-deadline:
			sendSSE(w, sseEvent{Status: "timeout", Message: "Still pending — check your email or try signing up again.", Step: 2})
			log.Printf("[%s] Timeout after %v", id, maxTimeout)
			return

		case <-nudgeTimer:
			if !nudgeSent {
				sendSSE(w, sseEvent{Status: "pending", Message: "Still waiting for verification — check your inbox or spam folder.", Step: 2})
				nudgeSent = true
			}

		case <-ticker.C:
			watcher, err = findWatcher(watchersPath, id)
			if err != nil {
				log.Printf("[%s] Poll error: %v", id, err)
				continue
			}
			if watcher == nil {
				sendSSE(w, sseEvent{Status: "error", Message: "Watch not found — it may have expired.", Step: 0})
				return
			}
			if watcher.Active {
				dashURL := fmt.Sprintf("/my-alerts.html?token=%s", watcher.UnsubscribeToken)
				sendSSE(w, sseEvent{
					Status:       "verified",
					Message:      "Verified! You're live — email alerts active, SMS nudge on. Bookmark your dashboard.",
					Step:         3,
					DashboardURL: dashURL,
				})
				log.Printf("[%s] Verified!", id)
				return
			}
		}
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"status":"ok","service":"onboarding-sse"}`)
}

func main() {
	log.SetPrefix("[onboarding] ")
	log.SetFlags(log.Ldate | log.Ltime)

	if addr := os.Getenv("ONBOARDING_ADDR"); addr != "" {
		listenAddr = addr
	}

	http.HandleFunc("/api/onboarding/", handleOnboarding)
	http.HandleFunc("/health", handleHealth)

	log.Printf("Listening on %s (watchers: %s)", listenAddr, watchersPath)
	if err := http.ListenAndServe(listenAddr, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
