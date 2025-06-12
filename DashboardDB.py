from pathlib import Path
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Union, Optional
from datetime import datetime, date, timezone
from contextlib import contextmanager

@dataclass
class SQueueEntry:
    job_id: str
    username: str
    account: str
    status: str
    name: str
    run_time: float
    est_run_time: float
    nodes: int
    cores: int

@dataclass
class StatusEntry:
    id: int
    name: str
    int_value_1: Optional[int]
    int_value_2: Optional[int]
    update_time: date

@dataclass
class QuotaEntry:
    file_system: str
    available_gib: int
    used_gib: int
    used_percent: int
    day: date
    machine: str

@dataclass
class UserChEntry:
    day: date
    username: str
    core_hours_used: float

class DashboardDB:
    def __init__(self, db_file: Union[str, Path]):
        self.db_file = Path(db_file)

    @staticmethod
    @contextmanager
    def get_cursor(db_file: Union[str, Path]):
        conn = sqlite3.connect(str(db_file))
        try:
            yield conn.cursor()
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def create_db(cls, db_file: Union[str, Path]):
        db_file = Path(db_file)
        with cls.get_cursor(db_file) as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_usage (
                    machine TEXT NOT NULL,
                    day DATE NOT NULL,
                    project_id TEXT NOT NULL,
                    core_hours_used FLOAT,
                    total_core_hours FLOAT,
                    update_time DATE NOT NULL,
                    PRIMARY KEY(machine, day, project_id)
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_core_hours (
                    machine TEXT NOT NULL,
                    day DATE NOT NULL,
                    username TEXT NOT NULL,
                    core_hours_used FLOAT,
                    update_time DATE NOT NULL,
                    project_id TEXT,
                    PRIMARY KEY(machine, day, username, project_id)
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_queue (
                    machine TEXT NOT NULL,
                    day DATE NOT NULL,
                    total_jobs INTEGER,
                    running_jobs INTEGER,
                    pending_jobs INTEGER,
                    PRIMARY KEY(machine, day)
                );
            """)

            cursor.execute("""
                CREATE TABLE quota (
                    machine TEXT NOT NULL,
                    file_system TEXT NOT NULL,
                    available_gib INTEGER NOT NULL,
                    used_gib INTEGER NOT NULL,
                    used_percent INTEGER NOT NULL,
                    day DATE NOT NULL,
                    PRIMARY KEY(machine, file_system, day)
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    PRIMARY KEY(username, project_id)
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS allocation (
                    id INTEGER PRIMARY KEY,
                    machine TEXT,
                    hours INTEGER,
                    start DATE,
                    end DATE,
                    project_id TEXT
                );
            """)

    def update_chours_usage(self, daily_ch, total_ch, hpc, project_id, day):
        update_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        with self.get_cursor(self.db_file) as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO daily_usage (machine, day, project_id, core_hours_used, total_core_hours, update_time) VALUES (?, ?, ?, ?, ?, ?)",
                (hpc.value, day, project_id, daily_ch, total_ch, update_time),
            )

    def update_user_chours(self, hpc, project_id, entries: Iterable[UserChEntry], day):
        update_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        with self.get_cursor(self.db_file) as cursor:
            for entry in entries:
                cursor.execute(
                    "INSERT OR REPLACE INTO user_core_hours (machine, day, username, core_hours_used, update_time, project_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (hpc.value, day, entry.username, entry.core_hours_used, update_time, project_id),
                )

    def update_squeue_status(self, hpc, day, total, running, pending):
        with self.get_cursor(self.db_file) as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO job_queue (machine, day, total_jobs, running_jobs, pending_jobs) VALUES (?, ?, ?, ?, ?)",
                (hpc.value, day, total, running, pending),
            )

    def update_daily_quota(self, entries: Iterable[QuotaEntry], hpc):
        with self.get_cursor(self.db_file) as cursor:
            for entry in entries:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO quota (
                        machine,
                        file_system,
                        available_gib,
                        used_gib,
                        used_percent,
                        day
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hpc.value,
                        entry.file_system,
                        entry.available_gib,
                        entry.used_gib,
                        entry.used_percent,
                        entry.day,
                    ),
                )

    def update_fairshare_status(self, hpc, project_id, day, fairshare_score, cpu_core_hours, mem_gb_hours):
        update_time = datetime.utcnow()
        with self.get_cursor(self.db_file) as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO fairshare_status
                (machine, day, project_id, fairshare_score, cpu_core_hours, mem_gb_hours, update_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (hpc.value, day.strftime("%Y-%m-%d"), project_id, fairshare_score, cpu_core_hours, mem_gb_hours, update_time))


    def ensure_user_exists(self, username: str, project_id: str):
        with self.get_cursor(self.db_file) as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO users (username, project_id) VALUES (?, ?)",
                (username, project_id),
            )

    def get_all_project_ids(self):
        with self.get_cursor(self.db_file) as cursor:
            result = cursor.execute("SELECT DISTINCT project_id FROM allocation").fetchall()
        return [r[0] for r in result]

    def get_all_users(self):
        with self.get_cursor(self.db_file) as cursor:
            result = cursor.execute("SELECT DISTINCT username FROM users").fetchall()
        return [r[0] for r in result]

    def insert_allocation(self, project_id: str, start: str, end: str, hours: int, machine: str = "hpc"):
        with self.get_cursor(self.db_file) as cursor:
            # Check for existing identical allocation
            existing = cursor.execute(
                """
                SELECT 1 FROM allocation
                WHERE project_id = ? AND start = ? AND end = ? AND hours = ? AND machine = ?
                """,
                (project_id, start, end, hours, machine),
            ).fetchone()

            if existing:
                print(f"⚠️ Allocation for project {project_id} already exists. Skipping insert.")
                return

            # Insert new allocation
            cursor.execute(
                """
                INSERT INTO allocation (project_id, start, end, hours, machine)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, start, end, hours, machine),
            )

    def get_allocation_start(self, project_id: str, machine: str) -> str:
        """Returns the earliest start date for the given project and machine."""
        with self.get_cursor(self.db_file) as cursor:
            result = cursor.execute(
                """
                SELECT MIN(start) FROM allocation
                WHERE project_id = ? AND machine = ?
                """,
                (project_id, machine),
            ).fetchone()
        return result[0] if result and result[0] else date.today().strftime("%Y-%m-%d")

    def get_users_for_project(self, project_id: str) -> list[str]:
        """Returns all usernames linked to the given project_id."""
        with self.get_cursor(self.db_file) as cursor:
            result = cursor.execute(
                """
                SELECT username FROM users
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
        return [row[0] for row in result]

