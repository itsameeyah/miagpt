#!/usr/bin/env bash
# install.sh — install miagpt as a systemd user service.
#     ./install.sh              install and start it
#     ./install.sh --uninstall  stop it and remove the unit
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/miagpt.service"
VENV="$DIR/.venv"
PYTHON="${PYTHON:-$VENV/bin/python}"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now miagpt.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "removed $UNIT"
  exit 0
fi

if [[ ! -f "$DIR/.env" ]]; then
  echo "no .env found — run: cp .env.example .env  and put your bot token in it" >&2
  exit 1
fi

if [[ ! -f "$DIR/persona.md" ]]; then
  echo "no persona.md found — run: cp persona.example.md persona.md  and write yours" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "creating a virtualenv in .venv"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$DIR/requirements.txt"

# check the config parses before handing it to systemd
if ! ( cd "$DIR" && "$PYTHON" -c "from miagpt import config; config.get(); config.section('bot')" ) >/dev/null 2>&1; then
  echo "config.toml doesn't load — run '$PYTHON bot.py' from $DIR to see the error" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<UNITEOF
[Unit]
Description=miagpt - user-installable /ask command
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$PYTHON $DIR/bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF

systemctl --user daemon-reload
systemctl --user enable --now miagpt.service

echo "installed $UNIT"
echo "  systemctl --user status miagpt"
echo "  journalctl --user -u miagpt -f"
echo "  loginctl enable-linger $USER   # keep it running after logout"
