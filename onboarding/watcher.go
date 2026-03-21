package main

import (
	"encoding/json"
	"os"
	"syscall"
)

// Watcher is the subset of fields we need from the watcher data file.
type Watcher struct {
	ID               string `json:"id"`
	Active           bool   `json:"active"`
	Email            string `json:"email"`
	UnsubscribeToken string `json:"unsubscribe_token"`
	VerifyToken      *string `json:"verify_token"` // null when verified
}

// findWatcher reads the watcher data file with a shared lock and returns the watcher with the given ID.
func findWatcher(path string, id string) (*Watcher, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()

	// Shared lock — same pattern as Python's fcntl.LOCK_SH
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_SH); err != nil {
		return nil, err
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)

	var watchers []Watcher
	if err := json.NewDecoder(f).Decode(&watchers); err != nil {
		return nil, err
	}

	for _, w := range watchers {
		if w.ID == id {
			return &w, nil
		}
	}
	return nil, nil
}
