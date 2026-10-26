#!/usr/bin/env bash
# Render start script for StorePro.
#
# Render mounts the persistent disk at /var/data (see render.yaml). StorePro
# was written around a single installation root, so the persistent folders are
# linked into that root before Gunicorn starts. Only one process may use the
# SQLite database, hence the single Gunicorn worker in gunicorn.conf.py.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

DATA_DIR="${STOREPRO_DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR/instance" "$DATA_DIR/uploads" "$DATA_DIR/backups" "$DATA_DIR/backups-secondary"

link_dir() {
  local target="$1" source="$2" seed="${3:-0}"
  if [ -L "$target" ]; then
    rm -f "$target"
  elif [ -e "$target" ]; then
    if [ "$seed" = "1" ]; then
      # Keep files that ship with the repository (demo product photos) on the
      # first boot. Never overwrite files already saved on the disk.
      cp -a -n "$target/." "$source/" 2>/dev/null || true
    fi
    rm -rf "$target"
  fi
  ln -s "$source" "$target"
}

link_dir instance "$DATA_DIR/instance"
link_dir static/uploads "$DATA_DIR/uploads" 1
# Repository copies of these folders are sample archives, not live data. The
# disk remains the only backup destination so restarts and deploys keep them.
link_dir backups "$DATA_DIR/backups"
link_dir backups-secondary "$DATA_DIR/backups-secondary"

# Render installs requirements into the service environment, so gunicorn is on
# PATH. A local Linux checkout may keep it inside .venv instead.
if [ -x "$APP_DIR/.venv/bin/gunicorn" ]; then
  GUNICORN="$APP_DIR/.venv/bin/gunicorn"
else
  GUNICORN="gunicorn"
fi

# Render's Python runtime exports GUNICORN_CMD_ARGS="--preload ...". Preloading
# would build the SQLite engine and start background threads in the master and
# then fork them away, which is unsafe for this application.
unset GUNICORN_CMD_ARGS

exec "$GUNICORN" --config gunicorn.conf.py wsgi:app
