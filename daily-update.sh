#!/bin/bash
# Daily Terry Awards update — fetches NBA data, commits, and pushes.
# Run by macOS launchd once a day.

cd "$(dirname "$0")"

# Pull latest
git pull --ff-only

# Run update
python3 update_data.py

# Commit and push if changed
git add data/
if ! git diff --staged --quiet; then
  git commit -m "Auto-update NBA data $(date +%Y-%m-%d)"
  git push
fi
