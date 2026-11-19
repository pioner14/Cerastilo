#!/bin/bash
# Сборка APK Cerastilo: тот же Qt-интерфейс (PySide6), что у десктопа.
#
#   bash android/build_apk.sh            # x86_64 — Waydroid
#   bash android/build_apk.sh aarch64    # arm64 — планшет
#
# Код приложения складывается в android/build_src/ (не в git): core/, ui/,
# modules/, assets/, migrations/, десктопный main.py как app_main.py,
# android/main.py как точка входа (без scheduler.db). APK — в android/.
#
# Нужны (см. память проекта android-pyside6-build): .android-venv с PySide6 6.12
# и requirements-android, wheels в ~/Android/wheels, SDK/NDK r28c в ~/Android/Sdk,
# JDK 17 в ~/Android/jdk-17 (Gradle не работает с системной Java 27).
set -euo pipefail
ARCH="${1:-x86_64}"
V=6.12.0
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/android/build_src"
cd "$ROOT"   # не из build_src: её пересоздаём ниже

# --- код приложения ---
# Код обновляем поверх, кэш сборщика (.buildozer) сохраняем — иначе каждая
# сборка заново компилирует Python под Android (~40 мин вместо пары минут)
mkdir -p "$SRC"
for d in core ui modules assets migrations; do
    rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$ROOT/$d" "$SRC/"
done
# Наблюдатель за темой через D-Bus — только Linux-десктоп; QtDBus нет в Android-wheels
# (подключается лишь в десктопном блоке запуска app_main.py)
rm -f "$SRC/ui/theme_watcher.py"
cp "$ROOT/main.py" "$SRC/app_main.py"
cp "$ROOT/android/main.py" "$SRC/main.py"
cp "$ROOT/alembic.ini" "$SRC/"
# Встроенная справка (ui/help_dialog.py): тексты и скриншоты
mkdir -p "$SRC/docs"
rsync -a --delete "$ROOT/docs/help" "$SRC/docs/"
# Рабочую базу в APK не кладём: в ней личные данные. Планшет стартует
# с пустой базой, данные приходят синхронизацией с ПК.
rm -f "$SRC/scheduler.db"
cp "$ROOT"/*.ttf "$SRC/" 2>/dev/null || true
if [ "${STAGE_ONLY:-}" = 1 ]; then echo "Подготовлено: $SRC"; exit 0; fi

export JAVA_HOME="$HOME/Android/jdk-17"
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_HOME="$HOME/Android/Sdk"
# buildozer ищет cython в PATH и ставит зависимости с --user, если не видит VIRTUAL_ENV
export VIRTUAL_ENV="$ROOT/.android-venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

# Переопределение параметров buildozer.spec через окружение (SECTION_TOKEN):
# какие файлы класть в APK, альбомная ориентация для планшета,
# чисто-питоновские зависимости, которые грузятся при старте главного окна.
export APP_SOURCE_INCLUDE_EXTS="py,png,jpg,ico,qss,db,ini,mako,ttf,json,qml,js,md"
export APP_ORIENTATION="landscape"
export APP_REQUIREMENTS="python3,shiboken6,PySide6,sqlalchemy==2.1.5,alembic,mako,markupsafe,typing_extensions"
# WITH_DOCX=1 — DOCX/S-89 (python-docx) и импорт EPUB (zipfile + beautifulsoup4).
# Меняет требования → кэш python-for-android сбрасывается, сборка ~40 мин.
# lxml и libxml2 — свои рецепты (android/p4a_recipes, подключает deploy_keep_cache.py).
if [ "${WITH_DOCX:-}" = 1 ]; then
    APP_REQUIREMENTS="$APP_REQUIREMENTS,lxml,python-docx,six,beautifulsoup4,soupsieve"
fi
export DISABLE_SQLALCHEMY_CEXT=1     # собрать SQLAlchemy без C-расширений
# Версия SQLAlchemy — как в .venv десктопа: рецепт p4a по умолчанию ставит 2.0.30,
# которая на Python 3.14 падает ("Can't replace canonical symbol for '__firstlineno__'")

cd "$SRC"
# pysidedeploy.spec остаётся от прошлой сборки, а arch из него важнее
# аргументов (wheel для aarch64 + arch = x86_64 → «libQt6Core_x86_64.so not found»)
if [ -f pysidedeploy.spec ]; then
    sed -i "s/^arch = .*/arch = $ARCH/" pysidedeploy.spec
    # значок APK — печать Cerastilo (иначе остаётся стандартный значок PySide)
    sed -i "s|^icon = .*|icon = $ROOT/assets/icon.png|" pysidedeploy.spec
    # RELEASE=1 — сборка без режима отладки (android:debuggable=false), APK без подписи;
    # подписать: bash android/sign_release.sh <apk>. По умолчанию — отладочная.
    if [ "${RELEASE:-}" = 1 ]; then
        sed -i "s/^mode = debug$/mode = release/" pysidedeploy.spec
    else
        sed -i "s/^mode = release$/mode = debug/" pysidedeploy.spec
    fi
fi
# pyside6-android-deploy сам стирает кэш .buildozer при каждом запуске —
# запускаем его через обёртку, которая кэш сохраняет
"$VIRTUAL_ENV/bin/python" "$ROOT/android/deploy_keep_cache.py" \
    --name Cerastilo \
    --wheel-pyside "$HOME/Android/wheels/pyside6-$V-$V-cp310-abi3-android_$ARCH.whl" \
    --wheel-shiboken "$HOME/Android/wheels/shiboken6-$V-$V-cp310-abi3-android_$ARCH.whl" \
    --ndk-path "$ANDROID_HOME/ndk/28.2.13676358" \
    --sdk-path "$ANDROID_HOME" \
    --force -v --keep-deployment-files   # не удалять .buildozer после сборки

# pyside6-android-deploy возвращает 0 и при ошибке — проверяем результат сами
APK=$(ls -t "$SRC"/*.apk 2>/dev/null | head -1 || true)
if [ -z "$APK" ]; then echo "APK не собран — см. вывод выше" >&2; exit 1; fi
mv "$APK" "$ROOT/android/"
ls -la "$ROOT/android/$(basename "$APK")"
