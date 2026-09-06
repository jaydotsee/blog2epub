# Find uv, including from a cron job whose PATH is nearly empty. Sourced by the scripts in bin/.
# Sets UV to the executable.

_find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return
  fi
  local candidate
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv /usr/bin/uv; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  echo "uv not found. Install it (https://docs.astral.sh/uv/) or set UV=/path/to/uv." >&2
  exit 127
}

UV="${UV:-$(_find_uv)}"
