from datetime import date, timedelta, datetime
from typing import List, Union, Iterable
import subprocess
from dashboard_constant import HPC
from DashboardDB import DashboardDB, UserChEntry, QuotaEntry
from constants import nesi_db_path

class DataCollector:
    def __init__(self, date: str,  debug: bool = False):
        self.hpc = HPC.hpc
        self.date = datetime.strptime(date, "%Y-%m-%d").date()
        self.dashboard_db = DashboardDB(nesi_db_path)
        self.project_ids = self.dashboard_db.get_all_project_ids()
        self.users = self.dashboard_db.get_all_users()
        self.debug = debug

    def run(self, upload: bool = False):
        self.collect_core_hours()
        self.collect_user_core_hours()
        if self.date == datetime.utcnow().date():
            self.collect_squeue()
            self.collect_quota()
            self.collect_fairshare()

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

    def collect_fairshare(self):
        for project_id in self.project_ids:
            fairshare_cmd = f"sshare --json -A {project_id}"
            lines = self.run_cmd(fairshare_cmd)
            json_text = "\n".join(lines)

            try:
                import json
                data = json.loads(json_text)
                entries = data.get("shares", {}).get("shares", [])
                assoc_entry = next((e for e in entries if "ASSOCIATION" in e.get("type", []) and e.get("name") == project_id), None)

                if assoc_entry:
                    fairshare_score = assoc_entry.get("effective_usage", {}).get("number", None)

                    # Extract CPU and MEM usage
                    usage_list = assoc_entry.get("tres", {}).get("usage", [])
                    cpu_usage = next((item["value"] for item in usage_list if item["name"] == "cpu"), 0.0)
                    mem_usage = next((item["value"] for item in usage_list if item["name"] == "mem"), 0.0)

                    if self.debug:
                        print(f"[DEBUG] FairShare for {project_id}: fairshare={fairshare_score}, cpu={cpu_usage}, mem={mem_usage}")

                    # Now insert this into your DB (you will need to create this method in DashboardDB):
                    cpu_core_hours = cpu_usage / 3600
                    mem_gb_hours = mem_usage / (1024**3) / 3600

                    self.dashboard_db.update_fairshare_status(
                        hpc=self.hpc,
                        project_id=project_id,
                        day=self.date,
                        fairshare_score=fairshare_score,
                        cpu_core_hours=cpu_core_hours,
                        mem_gb_hours=mem_gb_hours,
                    )
                else:
                    if self.debug:
                        print(f"[WARN] ASSOCIATION entry not found for project {project_id} in sshare output.")

            except Exception as e:
                if self.debug:
                    print(f"[ERROR] Failed to parse sshare output for project {project_id}: {e}")


    def upload_db(self):
        dropbox_path = "dropbox:/QuakeCoRE/Public/dashboard"
        local_db = nesi_db_path
        rclone_cmd = f"rclone copy {local_db} {dropbox_path} --progress"
        self.run_cmd(rclone_cmd)
