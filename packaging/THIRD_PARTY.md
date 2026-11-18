# Сторонние компоненты (Third-party notices)

Cerastilo распространяется по лицензии из файла `LICENSE`.

## Qt / PySide6 (LGPL-3.0)

Сборка AppImage использует Qt 6 и PySide6 (The Qt Company / Qt Project),
лицензия GNU LGPL v3: https://www.gnu.org/licenses/lgpl-3.0.html
Исходный код: https://code.qt.io/ и https://code.qt.io/cgit/pyside/pyside-setup.git/

Библиотеки Qt лежат в AppImage отдельными файлами `.so` (каталог
`usr/lib/cerastilo/_internal/PySide6/`), а не вшиты в исполняемый файл. Их можно
заменить своей сборкой: распакуйте образ (`./Cerastilo-*.AppImage --appimage-extract`),
подмените нужные `.so` и соберите заново через `appimagetool`.

## Прочее

Python (PSF), SQLAlchemy (MIT), Alembic (MIT), Pillow (HPND), lxml (BSD),
python-docx (MIT), requests (Apache-2.0), beautifulsoup4 (MIT),
PyInstaller (GPL-2.0 с исключением для загрузчика). Тексты лицензий — в
каталогах `*.dist-info` внутри `usr/lib/cerastilo/_internal/`.
