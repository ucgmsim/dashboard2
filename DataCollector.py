from datetime import date, timedelta, datetime
from typing import List, Union, Iterable
import subprocess
from dashboard_constant import HPC
from DashboardDB import DashboardDB, UserChEntry, QuotaEntry

class DataCollector:
    def __init__(self, date: str,  debug: bool = False):
        self.hpc = HPC.hpc
        self.date = datetime.strptime(date, "%Y-%m-%d").date()
        self.dashboard_db = DashboardDB("/home/baes/dashboard2/db/dashboard.db")
        self.project_ids = self.dashboard_db.get_all_project_ids()
        self.users = self.dashboard_db.get_all_users()
        self.debug = debug

    def run(self, upload: bool = False):
        self.collect_core_hours()
        self.collect_user_core_hours()
        if self.date == datetime.today().date():
            self.collect_squeue()
            self.collect_quota()

        if upload:
            self.upload_db()

    def run_cmd(self, cmd: str) -> List[str]:
        if self.debug:
            print(f"[DEBUG] Running command: {cmd}")
        try:
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
            lines = output.decode("utf-8").strip().splitlines()
            if self.debug:
                print(f"[DEBUG] Output:\n" + "\n".join(lines))
            return lines
        except subprocess.CalledProcessError as e:
            if self.debug:
                print(f"[ERROR] Command failed: {e.output.decode('utf-8')}")
            return []

    def collect_core_hours(self):
        for project_id in self.project_ids:
            date_str = self.date.strftime("%Y-%m-%d")
            start_time = f"{date_str}T00:00:00"
            end_time = f"{date_str}T23:59:59"

            # Daily core hours
            daily_cmd = (
                f"/usr/bin/sreport -M {self.hpc.value} -n -t Hours "
                f"cluster AccountUtilizationByUser Accounts={project_id} "
                f"start={start_time} end={end_time} format=Cluster,Accounts,Login%30,Proper,Used"
            )
            daily_lines = self.run_cmd(daily_cmd)

            daily_ch = 0.0
            for line in daily_lines:
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        username = parts[2]
                        used = float(parts[-1])
                        if username:  # If user exists in line
                            self.dashboard_db.ensure_user_exists(username, project_id)
                        daily_ch += used
                    except ValueError:
                        continue

            # Total core hours
            period_start = self.dashboard_db.get_allocation_start(project_id, self.hpc.value)
            total_cmd = (
                f"/usr/bin/sreport -M {self.hpc.value} -n -t Hours "
                f"cluster AccountUtilizationByUser Accounts={project_id} "
                f"start={period_start} end={end_time} format=Cluster,Accounts,Login%30,Proper,Used"
            )
            total_lines = self.run_cmd(total_cmd)

            total_ch = 0.0
            for line in total_lines:
                parts = line.split()
                if len(parts) >= 5 and not parts[2]:  # project summary
                    try:
                        total_ch = float(parts[-1])
                    except ValueError:
                        continue

            self.dashboard_db.update_chours_usage(
                daily_ch=daily_ch,
                total_ch=total_ch,
                hpc=self.hpc,
                project_id=project_id,
                day=self.date,
            )

    def collect_user_core_hours(self):
        for project_id in self.project_ids:
            users = self.dashboard_db.get_users_for_project(project_id)
            date_str = self.date.strftime("%Y-%m-%d")
            start_time = f"{date_str}T00:00:00"
            end_time = f"{date_str}T23:59:59"

            user_cmd = (
                f"/usr/bin/sreport -M {self.hpc.value} -t Hours cluster "
                f"AccountUtilizationByUser Accounts={project_id} "
                f"Users={' '.join(users)} start={start_time} end={end_time} "
                f"-n format=Cluster,Account,Login%30,Proper,Used"
            )
            lines = self.run_cmd(user_cmd)

            entries = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        username = parts[2]
                        used = float(parts[-1])
                        entries.append(UserChEntry(day=self.date, username=username, core_hours_used=used))
                        self.dashboard_db.ensure_user_exists(username, project_id)
                    except ValueError:
                        continue

            self.dashboard_db.update_user_chours(self.hpc, project_id, entries, self.date)

    def collect_squeue(self):
        lines = self.run_cmd("squeue -h -o '%T'")
        total = len(lines)
        running = sum(1 for l in lines if l.strip() == 'RUNNING')
        pending = sum(1 for l in lines if l.strip() == 'PENDING')
        self.dashboard_db.update_squeue_status(self.hpc, self.date, total, running, pending)

    def collect_quota(self):
        lines = self.run_cmd("/opt/nesi/bin/nn_storage_quota")
        if self.debug:
            print("Quota lines:")
            print("\n".join(lines))
        entries = []
        for line in lines:
            if line.startswith("Quota_Location") or not line.strip():
                continue  # skip header or empty lines
            parts = line.split()
            if len(parts) >= 4:
                try:
                    entries.append(
                        QuotaEntry(
                            file_system=parts[0],
                            available_gib=int(parts[1]),
                            used_gib=int(parts[2]),
                            used_percent=int(parts[3]),
                            day=self.date,
                            machine=self.hpc.value,
                        )
                    )
                except ValueError:
                    if self.debug:
                        print(f"[WARN] Failed to parse quota line: {line}")
                    continue
        self.dashboard_db.update_daily_quota(entries, self.hpc)

    def upload_db(self):
        dropbox_path = "dropbox:/QuakeCoRE/Public/dashboard"
        local_db = "/home/baes/dashboard2/db/dashboard.db"
        rclone_cmd = f"rclone copy {local_db} {dropbox_path} --progress"
        self.run_cmd(rclone_cmd)
