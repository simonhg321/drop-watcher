#!/bin/bash
# Pull GitHub code scanning alerts
# SGH
gh api repos/simonhg321/drop-watcher/code-scanning/alerts --jq '.[] | "\(.rule.id): \(.most_recent_instance.location.path):\(.most_recent_instance.location.start_line) — \(.rule.description)"'
