#!/bin/bash
# Regenerate all stats pages on ironman with correct env vars
# Run ON IRONMAN: bash ~/drop-watcher/bin/regen.sh
export DW_DATA_DIR=/var/lib/drop-watcher
export DW_LOG_DIR=/var/log/drop-watcher
export DW_CONFIG_DIR=/etc/drop-watcher
export DW_ENV_FILE=/etc/drop-watcher/.env
cd ~/drop-watcher
python3 generate_alerts.py
python3 generate_traffic.py
python3 generate_security.py
python3 generate_simon_status.py
python3 generate_public_stats.py
echo "DONE — all pages regenerated"
