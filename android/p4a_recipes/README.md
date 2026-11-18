# Свои рецепты python-for-android

Подключаются только при `WITH_DOCX=1 bash android/build_apk.sh aarch64`
(см. `android/deploy_keep_cache.py`, строка `p4a.local_recipes`).
Нужны для DOCX/S-89 (python-docx) и импорта EPUB (zipfile + BeautifulSoup): lxml нужен DOCX (python-docx).

- `lxml` — 6.1.3 вместо 4.8.0 из p4a: Си-код lxml 4.8 сгенерирован Cython 2022 года
  и под Python 3.14 не собирается; в sdist 6.1.3 Си-код уже сгенерирован (Python 3.14 в списке).
- `libxml2` — 2.9.14 вместо 2.9.12: lxml 6 предупреждает, что с 2.9.11/2.9.12
  «лишнее содержимое при сериализации» (а DOCX — это сериализованный XML).
  Патч add-glob.c из p4a к 2.9.14 применяется (проверено `patch --dry-run` 29.10.2026).
- `libxslt` — штатный рецепт p4a (1.1.34), он берёт наш libxml2.

Сборка с этими рецептами ещё не проводилась (ей нужен сброс кэша p4a, ~40 минут).
