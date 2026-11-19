#!/usr/bin/env bash
# Ставит ярлык Cerastilo в меню приложений текущего пользователя:
# подставляет в cerastilo.desktop папку, где лежит программа.
#
#   bash scripts/install_desktop.sh
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
# экранируем для sed: \, | и &
esc="$(printf '%s' "$dir" | sed 's/[\\|&]/\\&/g')"
sed "s|@CERASTILO_DIR@|$esc|g" "$dir/cerastilo.desktop" > "$apps/cerastilo.desktop"
chmod +x "$apps/cerastilo.desktop"
echo "Ярлык: $apps/cerastilo.desktop"
