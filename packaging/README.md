# Упаковка Cerastilo

## AppImage (сборка только вручную)

Сборка не запускается сама — ни при push, ни при PR, ни при теге.

- На GitHub: **Actions → AppImage → Run workflow**, поле «version» (например `0.1.0`).
- Или из терминала: `gh workflow run appimage.yml -f version=0.1.0`

Готовый `Cerastilo-<версия>-x86_64.AppImage` появится в «Artifacts» запуска.
Данные пользователя: `~/.local/share/cerastilo/`. Описание сборки —
`.github/workflows/appimage.yml`, `packaging/pyinstaller/cerastilo.spec`,
`packaging/appimage/`. Замечание про Qt (LGPL) — `packaging/THIRD_PARTY.md`.

## Пакет AUR `cerastilo`

Файл — `packaging/aur/PKGBUILD`. Выпуск новой версии:

1. Поднять `pkgver` в PKGBUILD, сделать тег `vX.Y.Z` и запушить его.
2. В папке с PKGBUILD: `updpkgsums` (заменит `SKIP` на сумму архива тега).
3. Проверить: `makepkg -f` (и `namcap PKGBUILD *.pkg.tar.zst`, если установлен).
4. `makepkg --printsrcinfo > .SRCINFO`
5. Клонировать `ssh://aur@aur.archlinux.org/cerastilo.git`, положить туда
   `PKGBUILD` и `.SRCINFO`, `git commit` и `git push`.
