#!/usr/bin/env bash
# Fill in the repository's About sidebar on GitHub: the one-line description, the website link
# and the topics that make the project findable. Idempotent; run it again after editing the
# values below.
#
#   scripts/set_github_about.sh              needs the gh CLI, logged in with repo scope
#   GITHUB_REPOSITORY=you/fork scripts/set_github_about.sh
#
# The social preview image (docs/social-preview.png, refreshed by `make docs`) cannot be set by
# the API: upload it once by hand under Settings → General → Social preview.
set -euo pipefail

repo="${GITHUB_REPOSITORY:-jaydotsee/blog2epub}"

# GitHub caps the description at 350 characters.
description='Turn the blogs you read into navigable EPUB 3 books and monthly magazine digests for your e-reader. Syncs posts through the WordPress API, RSS/Atom or the sitemap, isolates each article with readability, shrinks images to e-reader size, and publishes volumes to GitHub Releases on a schedule. Every book passes epubcheck clean.'

homepage="https://github.com/$repo/releases"

# At most 20; lowercase, digits and hyphens only.
topics=(
  epub
  epub3
  ebook
  e-reader
  kindle
  kobo
  blog
  rss
  atom
  wordpress
  readability
  web-scraping
  digest
  magazine
  newsletter
  archive
  python
  cli
  github-actions
  api-management
)

if (( ${#description} > 350 )); then
  echo "description is ${#description} characters; GitHub allows 350" >&2
  exit 1
fi
if (( ${#topics[@]} > 20 )); then
  echo "${#topics[@]} topics; GitHub allows 20" >&2
  exit 1
fi

topic_list=$(IFS=,; echo "${topics[*]}")

echo "== $repo"
gh repo edit "$repo" --description "$description" --homepage "$homepage"
gh repo edit "$repo" --add-topic "$topic_list"

# Drop any topic that is no longer in the list above, so the sidebar mirrors this file.
current=$(gh api "repos/$repo/topics" --jq '.names[]')
for t in $current; do
  keep=0
  for want in "${topics[@]}"; do
    [[ "$t" == "$want" ]] && keep=1 && break
  done
  if (( ! keep )); then
    echo "removing stale topic $t"
    gh repo edit "$repo" --remove-topic "$t"
  fi
done

echo
gh api "repos/$repo" --jq '"description: \(.description)\nhomepage:    \(.homepage)\ntopics:      \(.topics | join(", "))"'
