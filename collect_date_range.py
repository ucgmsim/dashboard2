"""
Batch collect dashboard data across a range of dates.
python collect_date_range.py --start 2025-05-21 --end 2025-05-29

"""

import argparse
from datetime import datetime, timedelta
import subprocess

def run_collector(start_date: str, end_date: str, debug: bool = False):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        print(f"📆 Collecting data for: {date_str}")
        cmd = ["python3", "data_collection.py", "--date", date_str]
        if debug:
            cmd.append("--debug")
        result = subprocess.run(
            cmd,
            check=False,
        )
        if result.returncode != 0:
            print(f"❌ Error on {date_str}:\n{result.stderr}")
        else:
            print(f"✅ Done for {date_str}")
        current += timedelta(days=1)

def main():
    parser = argparse.ArgumentParser(description="Collect dashboard data for a range of dates.")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output (e.g., print internal logs and command results)",
    )
    args = parser.parse_args()
    run_collector(args.start, args.end, args.debug)

if __name__ == "__main__":
    main()

