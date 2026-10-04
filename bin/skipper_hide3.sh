#!/usr/bin/env bash
# Hide the 3 PII posts on the public blog (soft delete via Skipper API, rows kept).
# Reversible: UPDATE posts SET deleted_at=NULL WHERE uuid='<uuid>' as user skipper.
set -euo pipefail
T=$(cat ~/.skipper.token)
LIST=${1:-$HOME/blog-cleanup/priority3.txt}
for u in $(grep -E '^[0-9a-f-]{36}$' "$LIST"); do
  printf "%s -> " "$u"
  curl -s -X DELETE -H "Authorization: Bearer $T" "http://127.0.0.1:5004/api/v1/posts/$u"; echo
done
python3 "$(dirname "$0")/gen_public_blog.py" 2>&1 | tail -1
for u in $(grep -E '^[0-9a-f-]{36}$' "$LIST"); do
  printf "public page %s -> " "$u"
  curl -s -o /dev/null -w "%{http_code}\n" "https://instockornot.club/posts/$u/"
done
