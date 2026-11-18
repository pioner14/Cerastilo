# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

# Windows requires .ico; Linux/macOS can use .png
if sys.platform.startswith('win'):
    icon_path = 'assets/icon.ico'
elif os.path.exists('assets/icon.png'):
    icon_path = 'assets/icon.png'
else:
    icon_path = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/styles/*.qss', 'assets/styles'),
        ('migrations/', 'migrations'),
        ('alembic.ini', '.'),
        ('*.ttf', '.'),
    ],
    hiddenimports=[
        'sqlalchemy.ext.declarative',
        'sqlalchemy.orm',
        'sqlite_utils',
        'bs4',
        'logging.config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NHJS_N',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
