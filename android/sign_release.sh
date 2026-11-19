#!/usr/bin/env bash
# Подписывает собранный APK release-ключом Cerastilo (вместо отладочного).
# Обычная сборка (build_apk.sh) не меняется: подпись — отдельный шаг.
#
#   bash android/sign_release.sh android/Cerastilo-0.1-arm64-v8a-debug.apk
#
# Ключ и пароль хранятся ВНЕ репозитория (по умолчанию ~/.config/cerastilo-signing/):
#   CERASTILO_KEYSTORE  — файл ключа PKCS12 (cerastilo-release.p12)
#   CERASTILO_KEY_PASS  — файл с паролем (password.txt), не сам пароль
# Внимание: APK с другой подписью нельзя поставить поверх старого — только
# удалить и поставить заново (данные планшета перед этим выгрузить).
set -euo pipefail
# Пароль ключа = пароль хранилища (PKCS12), поэтому --key-pass не передаём:
# apksigner читает один файл построчно, второй раз получил бы конец файла.

src="${1:?укажите APK}"
dir="${CERASTILO_SIGNING_DIR:-$HOME/.config/cerastilo-signing}"
ks="${CERASTILO_KEYSTORE:-$dir/cerastilo-release.p12}"
pass="${CERASTILO_KEY_PASS:-$dir/password.txt}"
bt="${ANDROID_BUILD_TOOLS:-$(ls -d "$HOME"/Android/Sdk/build-tools/* | sort -V | tail -1)}"
export JAVA_HOME="${JAVA_HOME:-$HOME/Android/jdk-17}"
export PATH="$JAVA_HOME/bin:$PATH"

[ -f "$ks" ] || { echo "Нет ключа: $ks" >&2; exit 1; }
[ -f "$pass" ] || { echo "Нет файла пароля: $pass" >&2; exit 1; }

out="${src%.apk}"; out="${out%-debug}-release.apk"
tmp="$(mktemp --suffix=.apk)"
trap 'rm -f "$tmp"' EXIT
# -P 16: .so выровнены на 16 КиБ (устройства со страницами 16 КиБ)
"$bt/zipalign" -f -P 16 4 "$src" "$tmp"
"$bt/apksigner" sign --ks "$ks" --ks-key-alias cerastilo \
    --ks-pass "file:$pass" --out "$out" "$tmp"
"$bt/apksigner" verify --print-certs "$out" | grep -E "Signer #1 certificate (DN|SHA-256)"
echo "Готово: $out"
