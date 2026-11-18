import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Settings:
    """
    Centralized configuration for the application.
    Loaded from environment variables, database 'settings' table, and defaults.
    """

    db_path: str = os.getenv("DB_PATH", "scheduler.db")
    min_assignment_gap: int = int(os.getenv("MIN_GAP", "2"))
    ms_assignment_gap: int = int(os.getenv("MS_GAP", "2"))  # Gap для служебных помощников
    backup_dir: str = os.getenv("BACKUP_DIR", "./backups")

    # UI Settings
    theme: str = os.getenv("THEME", "system")  # 'system', 'light', or 'dark'

    # Database settings (loaded from table)
    cong_name: str = ""
    meeting_day: str = ""
    meeting_time: str = ""
    last_selected_week: int = 0

    # Email notification settings
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender_name: str = ""  # Имя отправителя в письме

    # Cache of all raw settings from DB
    _raw_db_settings: Dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls) -> "Settings":
        """
        Loads settings from environment and database table.
        """
        settings = cls()
        settings._load_from_db()
        return settings

    def _load_from_db(self) -> None:
        """
        Load settings from the database 'settings' table and populate fields.
        """
        if not os.path.exists(self.db_path):
            # Database may not exist yet (first run)
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT key, value FROM settings")
            rows = cursor.fetchall()
            self._raw_db_settings = {k: v for k, v in rows}

            # Map known keys to fields
            mapping = {
                "cong_name": "cong_name",
                "meeting_day": "meeting_day",
                "meeting_time": "meeting_time",
                "last_selected_week": "last_selected_week",
                "min_assignment_gap": "min_assignment_gap",
                "ms_assignment_gap": "ms_assignment_gap",
                "theme": "theme",
                "backup_dir": "backup_dir",
                # db_path здесь нет: путь к базе не берём из самой базы — у копии
                # там записан путь рабочей scheduler.db, и копия писала бы в неё
                "smtp_host": "smtp_host",
                "smtp_port": "smtp_port",
                "smtp_user": "smtp_user",
                "smtp_sender_name": "smtp_sender_name",
            }

            for db_key, attr in mapping.items():
                if db_key in self._raw_db_settings:
                    value = self._raw_db_settings[db_key]
                    # Type conversion
                    if attr in ("min_assignment_gap", "ms_assignment_gap", "smtp_port"):
                        try:
                            setattr(self, attr, int(value))
                        except (ValueError, TypeError):
                            pass
                    elif attr == "last_selected_week":
                        try:
                            setattr(self, attr, int(value))
                        except (ValueError, TypeError):
                            pass
                    else:
                        setattr(self, attr, value)
        except sqlite3.Error as e:
            # If table doesn't exist or other error, just keep defaults
            pass
        finally:
            conn.close()

    def save_to_db(self) -> None:
        """
        Persist current settings to database table.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Ensure table exists
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )

            # Prepare data
            data = [
                ("cong_name", self.cong_name),
                ("meeting_day", self.meeting_day),
                ("meeting_time", self.meeting_time),
                ("last_selected_week", str(self.last_selected_week)),
                ("min_assignment_gap", str(self.min_assignment_gap)),
                ("ms_assignment_gap", str(self.ms_assignment_gap)),
                ("theme", self.theme),
                ("backup_dir", self.backup_dir),
                ("smtp_host", self.smtp_host),
                ("smtp_port", str(self.smtp_port)),
                ("smtp_user", self.smtp_user),
                ("smtp_sender_name", self.smtp_sender_name),
            ]

            for key, value in data:
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
                )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise
        finally:
            conn.close()
