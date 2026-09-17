#!/usr/bin/env bash
# Delete the rolling per-book releases left over from the old numbering: `<book>-latest` and
# `<book>-collectors-latest`, which the single dated release replaces — the newest issue is now
# the repository's latest release, so /releases/latest is the standing link.
#
#   scripts/prune_rolling_releases.sh            list what would go (dry run)
#   scripts/prune_rolling_releases.sh --yes      delete them, and their tags
#
# Dated issues are never touched: only tags ending in `-latest` match, and every file in them
# exists in its issue's release as well. Needs `gh` logged in with write access; GITHUB_REPOSITORY
# overrides the repository of the current checkout.
set -euo pipefail

go=false
[ "${1:-}" = "--yes" ] && go=true

repo="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
tags=$(gh api "repos/$repo/releases" --paginate --jq '.[].tag_name' | grep -E -- '-latest$' || true)

if [ -z "$tags" ]; then
  echo "No rolling releases left in $repo."
  exit 0
fi

echo "$tags" | while read -r tag; do
  if $go; then
    echo "deleting $tag"
    gh release delete "$tag" --repo "$repo" --cleanup-tag --yes
  else
    echo "would delete $tag"
  fi
done

$go || echo "Dry run. Re-run with --yes to delete these releases and their tags."
