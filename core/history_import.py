import csv
import sqlite3
import os
from datetime import datetime

from core.config import DB_PATH

# Маппинг типов заданий NWS на наши номера/коды
TYPE_MAP = {
    "Chairman": "chairman",
    "TreasuresTalk": "1",
    "SpiritualGems": "2",
    "BibleReading": "3",
    "Apply1": "4",
    "Apply2": "5",
    "Apply3": "6",
    "Apply4": "7",  # Иногда бывает 4-е задание
    "LivingPart1": "8",
    "LivingPart2": "9",
    "CBS": "10",
}


def import_history_from_csv(csv_path):
    """
    Импортирует историю назначений из CSV файла NW Scheduler.
    """
    if not os.path.exists(csv_path):
        return {"success": False, "error": f"Файл {csv_path} не найден"}

    stats = {"weeks": 0, "assignments": 0, "skipped": 0}

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 1. Загружаем маппинг участников (имя -> id)
        cursor.execute("SELECT id, name FROM participants")
        participants = {row[1]: row[0] for row in cursor.fetchall()}

        # 2. Читаем CSV
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            # Временное хранилище заданий по датам для поиска напарников
            # {date_str: {part_type: participant_id}}
            daily_data = {}

            for row in reader:
                date_str = row["Date"]  # YYYY.MM.DD
                person_name = row["Person"]
                part_type = row["PartType"]

                p_id = participants.get(person_name)
                if not p_id:
                    stats["skipped"] += 1
                    continue

                if date_str not in daily_data:
                    daily_data[date_str] = {}

                daily_data[date_str][part_type] = p_id

            # 3. Обрабатываем собранные данные
            for date_str, parts in daily_data.items():
                # Находим или создаем неделю
                # Конвертируем YYYY.MM.DD в DD.MM.YYYY
                dt = datetime.strptime(date_str, "%Y.%m.%d")
                fmt_date = dt.strftime("%Y-%m-%d")

                # Ищем неделю по дате
                cursor.execute("SELECT id FROM weeks WHERE start_date = ?", (fmt_date,))
                week_row = cursor.fetchone()

                if week_row:
                    week_id = week_row[0]
                else:
                    # Создаем техническую неделю для истории
                    month_num = dt.month
                    year = dt.year
                    # Пример заголовка: "1 сентября"
                    week_title = (
                        f"{dt.day} "
                        + [
                            "",
                            "января",
                            "февраля",
                            "марта",
                            "апреля",
                            "мая",
                            "июня",
                            "июля",
                            "августа",
                            "сентября",
                            "октября",
                            "ноября",
                            "декабря",
                        ][month_num]
                    )

                    cursor.execute(
                        """
                        INSERT INTO weeks (week_title, start_date, month, year, workbook_source)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (week_title, fmt_date, month_num, year, "NWS_HISTORY"),
                    )
                    week_id = cursor.lastrowid
                    stats["weeks"] += 1

                # 4. Создаем задания
                for p_type, p_id in parts.items():
                    # Пропускаем напарников здесь, они будут обработаны вместе с основными
                    if "Assistant" in p_type:
                        continue

                    # Маппим тип на номер задания
                    num = TYPE_MAP.get(p_type)
                    if not num:
                        continue

                    # Ищем напарника
                    asst_type = p_type + "Assistant"
                    asst_id = parts.get(asst_type)

                    # Для CBS (10) напарник это CBSReader
                    if p_type == "CBS":
                        asst_id = parts.get("CBSReader")

                    # Проверяем, нет ли уже такого задания
                    cursor.execute(
                        """
                        SELECT id FROM assignments 
                        WHERE week_id = ? AND assignment_number = ?
                    """,
                        (week_id, num),
                    )
                    existing = cursor.fetchone()

                    if existing:
                        # Обновляем существующее
                        cursor.execute(
                            """
                            UPDATE assignments 
                            SET participant_id = ?, assistant_id = ?, status = 'assigned',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """,
                            (p_id, asst_id, existing[0]),
                        )
                    else:
                        # Создаем новое
                        assignment_text = "История (Импорт)"
                        cursor.execute(
                            """
                            INSERT INTO assignments (week_id, assignment_text, assignment_number, participant_id, assistant_id, status, updated_at)
                            VALUES (?, ?, ?, ?, ?, 'assigned', CURRENT_TIMESTAMP)
                        """,
                            (week_id, assignment_text, num, p_id, asst_id),
                        )

                    stats["assignments"] += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

    return {"success": True, "stats": stats}
