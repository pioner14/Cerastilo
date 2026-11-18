#!/usr/bin/env python3
"""
Скрипт импорта email и телефонов из Excel в базу данных.

Читает «Список возвещателей.xlsx», сопоставляет имена с участниками
в БД и обновляет поля email и phone.

Использование:
    python scripts/import_emails_from_xlsx.py [путь_к_файлу.xlsx]

Если путь не указан — ищет «Список возвещателей.xlsx» в корне проекта.
"""

import os
import sys
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def import_emails_from_xlsx(
    xlsx_path: str,
    db_path: str = "scheduler.db",
    dry_run: bool = False,
) -> dict:
    """
    Импортирует email и телефоны из Excel в БД.

    Args:
        xlsx_path: Путь к XLSX-файлу со списком возвещателей.
        db_path: Путь к базе данных SQLite.
        dry_run: Если True — только показывает что будет сделано, не пишет в БД.

    Returns:
        Словарь со статистикой: updated, not_found, no_email, errors.
    """
    try:
        import openpyxl
    except ImportError:
        return {"success": False, "error": "Требуется библиотека openpyxl: pip install openpyxl"}

    if not os.path.exists(xlsx_path):
        return {"success": False, "error": f"Файл не найден: {xlsx_path}"}

    if not os.path.exists(db_path):
        return {"success": False, "error": f"БД не найдена: {db_path}"}

    # --- Читаем Excel ---
    try:
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
    except Exception as e:
        return {"success": False, "error": f"Ошибка чтения Excel: {e}"}

    # Ожидаемые столбцы (0-based индексы из ws.iter_rows):
    # A=0 ФИО, B=1 Группа, C=2 Адрес, D=3 Телефон, E=4 Email
    xlsx_data = {}  # name -> {email, phone}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = row[0]
        phone = row[3]
        email = row[4]
        if not name:
            continue
        name = str(name).strip()
        xlsx_data[name] = {
            "email": str(email).strip() if email else None,
            "phone": str(phone).strip() if phone else None,
        }

    # --- Читаем участников из БД ---
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("SELECT id, name FROM participants")
        db_participants = {row[1]: row[0] for row in cur.fetchall()}
    except sqlite3.Error as e:
        conn.close()
        return {"success": False, "error": f"Ошибка чтения БД: {e}"}

    # --- Сопоставление и обновление ---
    stats = {
        "updated": [],
        "not_found_in_db": [],
        "not_found_in_xlsx": [],
        "no_email": [],
        "already_has_email": [],
    }

    updates = []
    for name, data in xlsx_data.items():
        if name not in db_participants:
            stats["not_found_in_db"].append(name)
            continue

        p_id = db_participants[name]
        email = data["email"]
        phone = data["phone"]

        if not email:
            stats["no_email"].append(name)

        updates.append((email, phone, p_id, name))
        stats["updated"].append({"name": name, "email": email, "phone": phone})

    # Участники в БД, которых нет в Excel
    for name in db_participants:
        if name not in xlsx_data:
            stats["not_found_in_xlsx"].append(name)

    if not dry_run and updates:
        try:
            cur.executemany(
                "UPDATE participants SET email=?, phone=? WHERE id=?",
                [(e, p, pid) for e, p, pid, _ in updates],
            )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            conn.close()
            return {"success": False, "error": f"Ошибка записи в БД: {e}"}

    conn.close()

    return {
        "success": True,
        "dry_run": dry_run,
        "stats": {
            "updated": len(stats["updated"]),
            "no_email": len(stats["no_email"]),
            "not_found_in_db": len(stats["not_found_in_db"]),
            "not_found_in_xlsx": len(stats["not_found_in_xlsx"]),
        },
        "details": stats,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Определяем пути
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    xlsx_path = sys.argv[1] if len(sys.argv) > 1 else str(project_root / "Список возвещателей.xlsx")
    db_path = str(project_root / "scheduler.db")
    dry_run = "--dry-run" in sys.argv

    print(f"📂 Excel: {xlsx_path}")
    print(f"🗄️  БД:   {db_path}")
    if dry_run:
        print("🔍 Режим просмотра (dry-run) — БД не изменяется")
    print()

    result = import_emails_from_xlsx(xlsx_path, db_path, dry_run=dry_run)

    if not result["success"]:
        print(f"❌ Ошибка: {result['error']}")
        sys.exit(1)

    s = result["stats"]
    print(f"✅ Обновлено участников: {s['updated']}")
    print(f"📧 Без email в Excel:   {s['no_email']}")
    print(f"❓ Не найдены в БД:     {s['not_found_in_db']}")
    print(f"❓ Нет в Excel:         {s['not_found_in_xlsx']}")

    if result["details"]["not_found_in_db"]:
        print("\nНе найдены в БД (проверьте написание имён):")
        for name in result["details"]["not_found_in_db"]:
            print(f"  • {name}")

    if result["details"]["not_found_in_xlsx"]:
        print("\nУчастники БД без записи в Excel:")
        for name in result["details"]["not_found_in_xlsx"]:
            print(f"  • {name}")

    if dry_run:
        print("\nЗапустите без --dry-run для применения изменений.")
