#!/usr/bin/env bash
# Pins the composite actions that the reusable workflows load to the last commit that changed
# .github/actions, so a caller's Roastbook/workflows pin also fixes the actions it runs.
# A commit cannot name its own SHA: change .github/actions in one commit, then pin it in the next.
# Usage: scripts/pin-actions.sh          rewrite every reference
#        scripts/pin-actions.sh --check  fail on a missing, mixed or unknown pin; warn when stale
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uses='Roastbook/workflows/\.github/actions/[a-z-]+@'

if [[ "${1:-}" != --check ]]; then
  latest="$(git log -1 --format=%H -- .github/actions)"
  sed -i -E "s#(${uses})[0-9A-Za-z._-]+#\\1${latest}#" .github/workflows/*.yml
  echo "Pinned the composite actions to $latest."
  exit 0
fi

refs="$(grep -ohE "${uses}[0-9A-Za-z._-]+" .github/workflows/*.yml | sed 's/.*@//' | sort -u)"
if [[ ! "$refs" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::Every composite action reference must use one full commit SHA, found: ${refs//$'\n'/ }"
  exit 1
fi
if ! git merge-base --is-ancestor "$refs" HEAD; then
  echo "::error::The composite action pin $refs is not an ancestor of HEAD."
  exit 1
fi
if [[ "$(git rev-parse "$refs:.github/actions")" != "$(git rev-parse HEAD:.github/actions)" ]]; then
  echo "::warning::.github/actions changed since $refs. After merging, run scripts/pin-actions.sh and commit the result."
fi
echo "Composite actions are pinned to $refs."
