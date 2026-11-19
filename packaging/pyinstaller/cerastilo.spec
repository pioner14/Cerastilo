# -*- mode: python ; coding: utf-8 -*-
# Сборка Cerastilo в папку (onedir): библиотеки Qt остаются отдельными файлами
# (LGPL — их можно заменить). Запуск из корня репозитория:
#   pyinstaller --noconfirm packaging/pyinstaller/cerastilo.spec
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))


def p(*parts):
    return os.path.join(ROOT, *parts)


a = Analysis(
    [p("main.py")],
    pathex=[ROOT, p("scripts")],
    binaries=[],
    datas=[
        (p("assets", "styles", "*.qss"), "assets/styles"),
        (p("assets", "icon.png"), "assets"),
        (p("assets", "icon-256.png"), "assets"),
        (p("assets", "favicon-32.png"), "assets"),
        (p("migrations"), "migrations"),
        (p("alembic.ini"), "."),
        (p("docs", "help"), "docs/help"),
        (p("PT_Sans-Narrow-Web-Bold.ttf"), "."),
        (p("PT_Sans-Narrow-Web-Regular.ttf"), "."),
        (p("LICENSE"), "."),
    ],
    hiddenimports=(
        [
            "sqlalchemy.dialects.sqlite",
            "import_emails_from_xlsx",  # scripts/, подгружается динамически
            "logging.config",
        ]
        # Alembic грузит миграции из файлов — их импорты PyInstaller не видит
        + collect_submodules("alembic")
        + collect_submodules("core")
        + collect_submodules("ui")
        + collect_submodules("modules")
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cerastilo",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=p("assets", "icon.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="cerastilo")
