# Changelog

Все заметные изменения в Cerastilo. / All notable changes to Cerastilo.

Формат основан на [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), версии — по [Semantic Versioning](https://semver.org/).
The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] — 2026-11-24

### Добавлено / Added

- Проверка обновлений: в «⚙️ Настройки» → «⬆️ Обновления» видна версия программы, есть кнопка «Проверить обновления» и галочка автопроверки при запуске (не чаще раза в день). Программа только сообщает о новой версии и даёт ссылку, сама ничего не устанавливает. В пакете AUR автопроверка по умолчанию выключена.
- Update check: “⚙️ Settings” → “⬆️ Updates” shows the app version, a “Check for updates” button, and an option to check automatically at startup (at most once a day). The app only tells you about a new version and links to it; it does not install anything. In the AUR package the automatic check is off by default.
- Синхронизация ПК ↔ планшет по Wi-Fi теперь зашифрована: TLS 1.3, ключ получается из кода подключения, сам код по сети не передаётся; код теперь 12 символов (ABCD-EFGH-JKMN), запоминается на обоих устройствах, на планшете есть кнопка «Новый код». Старые и новые версии не синхронизируются друг с другом — обновите оба устройства.
- PC ↔ tablet Wi-Fi sync is now encrypted: TLS 1.3 with a key derived from the connection code, which is never sent over the network; the code is now 12 characters (ABCD-EFGH-JKMN), remembered on both devices, and the tablet has a “New code” button. Old and new versions will not sync with each other — update both devices.

### Изменено / Changed

- Справка переписана: проще и короче, исправлены устаревшие места (планшет стартует без базы, пароль почты не входит в резервную копию, PDF и TXT на узком экране — в меню «⋯ Ещё»). Та же справка теперь на сайте: https://cerastilo.com/docs/
- The built-in help has been rewritten to be simpler and shorter, and outdated passages are fixed (the tablet starts without a database, the email password is not included in backups, PDF and TXT are under "⋯ More" on narrow screens). The same help is now on the website: https://cerastilo.com/docs/en/
- Новый README (RU/EN: установка из готовых сборок, архитектура для разработчиков).
- New README (RU/EN: installation from ready builds, architecture for developers).
- Сборка для Windows теперь на Python 3.14 (нужен для шифрованной синхронизации).
- The Windows build now uses Python 3.14 (required for encrypted sync).

### Исправлено / Fixed

- Пакет AUR: зависимость hicolor-icon-theme, контрольная сумма архива.
- AUR package: hicolor-icon-theme dependency, archive checksum.
- Синхронизация: сканеры сети и случайные подключения больше не блокируют её — в лимит 5 неверных кодов идут только подключения Cerastilo.
- Sync: network scanners and stray connections no longer lock it — only Cerastilo connections count towards the limit of 5 wrong codes.

## [0.1.0] — 2026-11-19

### Русский

Первый публичный релиз Cerastilo — планировщика встреч «Жизнь и служение» для ПК и Android-планшетов.

#### Добавлено
- База возвещателей, квалификации, отпуска.
- Импорт тетради (EPUB, русский и английский).
- Авто-распределение недели и месяца, доска месяца, ручные правки с откатом.
- Письма участникам, .ics, разбор ответов по IMAP.
- Экспорт PDF/TXT/DOCX, бланк S-89, печать.
- Синхронизация ПК ↔ планшет по Wi-Fi.
- Интерфейс и справка на русском и английском.

#### Скачать
- **Arch Linux:** `yay -S cerastilo` (AUR).
- **Linux:** `Cerastilo-0.1.0-x86_64.AppImage`.
- **Windows:** `Cerastilo-0.1.0-windows-x64.zip` — распакуйте и запускайте `cerastilo.exe`, папку рядом не трогайте и не удаляйте.
- **Android (планшеты arm64):** `Cerastilo-0.1.0-arm64-v8a.apk` — первая версия для Android.

#### Важно
- Синхронизация ПК ↔ планшет идёт без шифрования — только в доверенной домашней сети.
- Данные: Linux — `~/.local/share/cerastilo`, Windows — `%LOCALAPPDATA%\Cerastilo`.
- Лицензия: source-available, см. `LICENSE`.

### English

First public release of Cerastilo, a "Life and Ministry" meeting scheduler for PC and Android tablets.

#### Added
- Publishers database, qualifications, absences.
- Workbook import (EPUB, Russian and English).
- Automatic assignment for a week or a month, month board, manual edits with undo.
- Emails to participants, .ics files, reading replies over IMAP.
- Export to PDF/TXT/DOCX, S-89 slips, printing.
- PC ↔ tablet sync over Wi-Fi.
- Interface and help in Russian and English.

#### Downloads
- **Arch Linux:** `yay -S cerastilo` (AUR).
- **Linux:** `Cerastilo-0.1.0-x86_64.AppImage`.
- **Windows:** `Cerastilo-0.1.0-windows-x64.zip` — unzip and run `cerastilo.exe`; keep the folder next to it intact.
- **Android (arm64 tablets):** `Cerastilo-0.1.0-arm64-v8a.apk` — first Android version.

#### Notes
- PC ↔ tablet sync is unencrypted: use it only on a trusted home network.
- Data: Linux — `~/.local/share/cerastilo`, Windows — `%LOCALAPPDATA%\Cerastilo`.
- License: source-available, see `LICENSE`.

[Unreleased]: https://github.com/pioner14/Cerastilo/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/pioner14/Cerastilo/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/pioner14/Cerastilo/releases/tag/v0.1.0
