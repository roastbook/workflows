#!/usr/bin/env bash
# Apply repository metadata and settings for the Roastbook Open Coffee repos.
# Idempotent: rerunning converges to the same state. Topics are replaced, not merged.
#
#   scripts/repo-metadata.sh --dry-run   # print what would be called
#   scripts/repo-metadata.sh             # apply (needs admin on each repo)
#   scripts/repo-metadata.sh open-coffee-data   # limit to some repos
set -euo pipefail

OWNER=Roastbook
DRY_RUN=0
repos=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h | --help) sed -n '2,8p' "$0"; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) repos+=("$arg") ;;
  esac
done
((${#repos[@]})) || repos=(open-coffee-schema open-coffee-data workflows)

run() {
  if ((DRY_RUN)); then
    printf '+'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# Read-only probe; in dry-run it reports "missing" so every write is shown.
probe() {
  ((DRY_RUN)) && return 1
  gh api "$@" > /dev/null 2>&1
}

settings() {
  local repo="$OWNER/$1" description="$2" homepage="$3"; shift 3
  echo "== $repo"
  run gh repo edit "$repo" \
    --description "$description" \
    --homepage "$homepage" \
    --enable-discussions \
    --enable-wiki=false \
    --enable-projects=false \
    --enable-squash-merge \
    --enable-merge-commit=false \
    --enable-rebase-merge=false \
    --delete-branch-on-merge
  local topic_args=()
  for topic in "$@"; do topic_args+=(-f "names[]=$topic"); done
  run gh api --method PUT "repos/$repo/topics" "${topic_args[@]}" --silent
  run gh api --method PUT "repos/$repo/private-vulnerability-reporting" --silent
}

# Pages from the Actions artifact (no gh-pages branch), custom domain, HTTPS, and a
# github-pages environment that accepts main plus release tags.
pages() {
  local repo="$OWNER/$1" cname="$2" tag_pattern="$3"
  if probe "repos/$repo/pages"; then
    run gh api --method PUT "repos/$repo/pages" -f build_type=workflow -f cname="$cname" --silent
  else
    run gh api --method POST "repos/$repo/pages" -f build_type=workflow --silent
    run gh api --method PUT "repos/$repo/pages" -f cname="$cname" --silent
  fi
  # GitHub issues the certificate only after DNS resolves; rerun later if this fails.
  run gh api --method PUT "repos/$repo/pages" -F https_enforced=true --silent ||
    echo "warning: HTTPS not enforceable yet for $cname (DNS or certificate pending); rerun later" >&2

  run gh api --method PUT "repos/$repo/environments/github-pages" \
    -F 'deployment_branch_policy[protected_branches]=false' \
    -F 'deployment_branch_policy[custom_branch_policies]=true' --silent
  local existing=""
  ((DRY_RUN)) || existing="$(gh api "repos/$repo/environments/github-pages/deployment-branch-policies" \
    --jq '.branch_policies[] | "\(.type):\(.name)"')"
  local policy
  for policy in "branch:main" "tag:$tag_pattern"; do
    grep -qxF "$policy" <<< "$existing" && continue
    run gh api --method POST "repos/$repo/environments/github-pages/deployment-branch-policies" \
      -f type="${policy%%:*}" -f name="${policy#*:}" --silent
  done
}

for repo in "${repos[@]}"; do
  case "$repo" in
    open-coffee-schema)
      settings open-coffee-schema \
        "Open standard for describing coffee places: JSON Schema, JSON-LD context and docs. By Roastbook." \
        "https://schema.roastbook.coffee/" \
        open-data open-standard data-standard json-schema json-ld schema-org linked-data coffee \
        specialty-coffee coffee-shops cafes points-of-interest geospatial roastbook managed-workflows
      pages open-coffee-schema schema.roastbook.coffee 'v*.*.*'
      ;;
    open-coffee-data)
      settings open-coffee-data \
        "Open dataset of coffee places and specialty cafés, validated against the Open Coffee Schema. CC BY 4.0. By Roastbook." \
        "https://data.roastbook.coffee/" \
        open-data dataset coffee specialty-coffee coffee-shops cafes points-of-interest geojson \
        geoparquet maplibre germany munich cc-by roastbook managed-workflows
      pages open-coffee-data data.roastbook.coffee '[0-9]*.[0-9]*.[0-9]*.[0-9]*'
      ;;
    workflows)
      settings workflows \
        "Shared reusable GitHub Actions workflows, composite actions and Orcastrate templates for Roastbook repositories." \
        "https://github.com/Roastbook/workflows#readme" \
        github-actions reusable-workflows composite-actions orcastrate ci roastbook
      ;;
    *) echo "unknown repository: $repo" >&2; exit 2 ;;
  esac
done
