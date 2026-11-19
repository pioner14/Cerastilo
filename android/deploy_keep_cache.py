"""pyside6-android-deploy, который не удаляет кэш сборки.

Штатный pyside6-android-deploy в начале каждого запуска вызывает cleanup():
удаляет build_src/deployment/ и build_src/.buildozer, а в конце сборки сам
переносит .buildozer в deployment/. В итоге кэш python-for-android всегда
стирается, и Python под Android компилируется заново (~40 мин).

Здесь cleanup() подменён: кэш (.buildozer — из папки проекта или из
deployment/) откладывается в сторону, штатная очистка проходит, и кэш
возвращается на место как build_src/.buildozer.

Заодно подключает хуки python-for-android из android/p4a_hook.py, а при
WITH_DOCX=1 — свои рецепты из android/p4a_recipes/.

Запуск — как у pyside6-android-deploy, с теми же аргументами
(см. android/build_apk.sh).
"""
import os
import re
import runpy
import shutil
import sys
from pathlib import Path

import PySide6

SCRIPTS = Path(PySide6.__file__).resolve().parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import deploy_lib  # noqa: E402  (из SCRIPTS)

_original_cleanup = deploy_lib.cleanup


def _cleanup_keeping_cache(config, is_android=False):
    project_dir = Path(config.project_dir).resolve()
    stash = project_dir.parent / ".buildozer-stash"
    candidates = [project_dir / ".buildozer"]
    if config.generated_files_path:
        candidates.append(Path(config.generated_files_path).resolve() / ".buildozer")
    for cache in candidates:
        if cache.is_dir() and not stash.exists():
            shutil.move(cache, stash)
    _original_cleanup(config=config, is_android=is_android)
    if stash.exists():
        shutil.move(stash, project_dir / ".buildozer")


deploy_lib.cleanup = _cleanup_keeping_cache

# Хуки p4a (android/p4a_hook.py) — правка PythonActivity.java перед Gradle.
# buildozer.spec генерируется заново при каждой сборке, поэтому строку
# p4a.hook дописываем в него перед запуском buildozer.
from deploy_lib.android.buildozer import Buildozer  # noqa: E402

P4A_HOOK = Path(__file__).resolve().parent / "p4a_hook.py"
# Свои рецепты (lxml 6 и libxml2 2.9.14, см. android/p4a_recipes/README.md) —
# только при WITH_DOCX=1: android/build_apk.sh тогда же добавляет lxml в требования
P4A_RECIPES = Path(__file__).resolve().parent / "p4a_recipes"
_original_create_executable = Buildozer.create_executable


def _create_executable_with_hook(mode):
    spec = Path("buildozer.spec")
    text = spec.read_text(encoding="utf-8")
    extra = ""
    if "p4a.hook" not in text:
        extra += f"p4a.hook = {P4A_HOOK}\n"
    if os.environ.get("WITH_DOCX") == "1":
        # pyside6-android-deploy уже задаёт p4a.local_recipes (deployment/recipes
        # с рецептами PySide6/shiboken6) — тогда кладём свои рецепты туда же
        found = re.search(r"^p4a\.local_recipes\s*=\s*(.+)$", text, re.M)
        if found:
            for recipe in P4A_RECIPES.iterdir():
                if recipe.is_dir():
                    shutil.copytree(recipe, Path(found.group(1).strip()) / recipe.name,
                                    dirs_exist_ok=True)
        else:
            extra += f"p4a.local_recipes = {P4A_RECIPES}\n"
    # «Доступ ко всем файлам»: без него Android 13 не показывает программе
    # файлы, положенные в «Загрузки/Cerastilo» другими приложениями (EPUB, бэкап с ПК)
    if "MANAGE_EXTERNAL_STORAGE" not in text:
        text = re.sub(r"^(android\.permissions\s*=.*)$",
                      r"\1, android.permission.MANAGE_EXTERNAL_STORAGE", text, count=1, flags=re.M)
        spec.write_text(text, encoding="utf-8")
    # venv p4a для чисто-питоновых пакетов: «pip install -U pip» в старом venv
    # оставляет смесь версий pip (ImportError в pip._internal) — каждый раз
    # создаём заново, это секунды
    for base in (Path.cwd(), Path.cwd().parent):
        for venv in base.glob(".buildozer/android/platform/build-*/build/venv"):
            shutil.rmtree(venv, ignore_errors=True)
        # Рецепт PySide6 копирует в libs/ привязки только тех модулей Qt, что
        # нашёл в коде (QtPrintSupport и т. п.); p4a считает его собранным и
        # при новом модуле не перезапускает — APK падает на старте (dlopen
        # QtPrintSupport.abi3.so). Рецепт — лишь распаковка wheel, гоняем всегда;
        # PythonRecipe пропускает сборку, если пакет уже лежит в site-packages
        for pattern in ("other_builds/PySide6", "python-installs/*/*/PySide6"):
            for built in base.glob(f".buildozer/android/platform/build-*/build/{pattern}"):
                shutil.rmtree(built, ignore_errors=True)
    # release: buildozer по умолчанию собирает .aab — нам нужен .apk (без подписи,
    # подписывает android/sign_release.sh)
    if mode == "release" and "android.release_artifact" not in text:
        extra += "android.release_artifact = apk\n"
    if extra:
        spec.write_text(text.replace("[app]\n", f"[app]\n{extra}", 1), encoding="utf-8")
    _original_create_executable(mode)


Buildozer.create_executable = staticmethod(_create_executable_with_hook)

sys.argv[0] = str(SCRIPTS / "android_deploy.py")
runpy.run_path(sys.argv[0], run_name="__main__")
