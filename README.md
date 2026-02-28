Mission

Score cool knives and Steel Flame gear by catching drops early — without being a bad citizen to the makers and traders in the community.
 
Core Constraints

• User maintains the "cool list" — the system watches and alerts only
• Be a good citizen — polite polling, respectful rate limits, no hammering small maker sites
• Notifications are local only — no automated purchasing
• Owner makes all buy decisions manually
 Architecture

Agents (Always-on Daemons)
• Web Watcher Agent — polls maker/dealer websites on a polite randomized interval, detects inventory changes or new listings matching the cool list
• Feed Watcher Agent — consumes RSS feeds (Instagram/Facebook via 3rd party RSS bridge, YouTube API) watching for drop announcements matching keywords
• Orchestrator — manages both agents, enforces rate limits, handles restarts, keeps everything alive
 
 Notification
• Structured local log (JSON lines format) with timestamp, source, and what changed
• Terminal-friendly alert (notify-send or stdout print with sound)
 
