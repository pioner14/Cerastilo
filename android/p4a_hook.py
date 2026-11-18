"""Хуки python-for-android для сборки APK (подключает android/deploy_keep_cache.py).

before_apk_build вызывается в папке dist перед Gradle, когда исходники Java
бутстрапа уже скопированы, — правим их здесь.
"""
from pathlib import Path

# До super.onCreate(): Qt проверяет переменную, когда создаёт окно Activity, —
# из Python это уже поздно. Без неё при включённой службе специальных
# возможностей (например, у лаунчера Nova) приложение падает почти на каждом
# нажатии: «Failed to acquire deadlock protector for
# QAndroidPlatformOpenGLWindow::eglSurface()».
A11Y_LINE = 'setEnvironmentVariable("QT_ANDROID_DISABLE_ACCESSIBILITY", "1");'
ANCHOR = 'Log.v(TAG, "About to do super onCreate");'

# Бутстрап p4a перехватывает ЛЮБУЮ аппаратную клавишу, включая «Назад»:
# первое нажатие съедает с тостом «Click again to close the app», второе
# закрывает программу. Отдаём клавиши Qt — «Назад» обрабатывает
# ui/android_back.py (закрыть меню/окно, выход по двойному нажатию).
BACK_TOAST = 'Toast.makeText(this, "Click again to close the app", Toast.LENGTH_LONG).show();'
BACK_BLOCK_START = "if (SystemClock.elapsedRealtime() - lastBackClick > 2000) {"
BACK_PATCHED = "if (false) {  // Cerastilo: «Назад» обрабатывает Qt"


def patch_back_key(text: str) -> str:
    """Убрать перехват клавиш из onKeyDown PythonActivity (условие «2 секунды»
    становится ложным — сразу вызывается super.onKeyDown, то есть Qt)."""
    if BACK_TOAST not in text or BACK_PATCHED in text:
        return text
    if BACK_BLOCK_START not in text:
        raise RuntimeError("p4a_hook: не найден перехват «Назад» в PythonActivity.java")
    return text.replace(BACK_BLOCK_START, BACK_PATCHED, 1)


def before_apk_build(toolchain):
    java = Path("src/main/java/org/kivy/android/PythonActivity.java")
    text = java.read_text(encoding="utf-8")
    original = text
    if A11Y_LINE not in text:
        if ANCHOR not in text:
            raise RuntimeError(f"p4a_hook: в {java.resolve()} не найдено место для отключения a11y")
        text = text.replace(ANCHOR, A11Y_LINE + "\n        " + ANCHOR)
        print(f"p4a_hook: a11y Qt отключена в {java}")
    text = patch_back_key(text)
    if text != original:
        java.write_text(text, encoding="utf-8")
