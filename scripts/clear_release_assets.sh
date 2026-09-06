#!/usr/bin/env bash
# Remove every asset from the GitHub release at a tag, so a re-run replaces the files rather
# than piling new ones next to the old. A release is one issue: one set of volumes.
#
#   scripts/clear_release_assets.sh <tag>          needs GH_TOKEN and GITHUB_REPOSITORY
#
# Exits 0 when there is no release at the tag yet. Callers should run it only after a build
# has produced something to upload, so a failed build never empties a good release.
set -euo pipefail

tag="${1:?usage: clear_release_assets.sh <tag>}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}"

# `gh api` writes the error body to STDOUT and skips --jq when the request fails, so an empty
# capture is not what "no release at this tag" looks like: a 404 handed back the whole
# `{"message":"Not Found",...}` blob as the id, and the next call built a URL around it. Trust
# an id only when it is one.
id=$(gh api "repos/$repo/releases/tags/$tag" --jq .id 2>/dev/null || true)
case "$id" in
  '' | *[!0-9]*)
    echo "No release at $tag yet; nothing to clear."
    exit 0
    ;;
esac
gh api "repos/$repo/releases/$id/assets" --paginate --jq '.[] | "\(.id) \(.name)"' |
  while read -r asset name; do
    echo "removing $name"
    gh api -X DELETE "repos/$repo/releases/assets/$asset"
  done
