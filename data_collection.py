#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
from dashboard_constant import HPC
from DataCollector import DataCollector
from DashboardDB import DashboardDB
from constants import nesi_db_path

TIME_FORMAT_DATEONLY = "%Y-%m-%d"

def get_today_str():
    return datetime.now(timezone.utc).strftime(TIME_FORMAT_DATEONLY)

def main():
    parser = argparse.ArgumentParser(prog="data_collection")

    parser.add_argument(
        "--date",
        type=str,
        help="Date of interest, format YYYY-MM-DD. Defaults to today.",
        default=get_today_str(),
    )

    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload dashboard DB to Dropbox after update.",
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the dashboard database before collecting.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output (e.g., print internal logs and command results)",
    )

    args = parser.parse_args()

    if args.reset:
        import os
        if os.path.exists(nesi_db_path):
            os.remove(nesi_db_path)
        DashboardDB.create_db(nesi_db_path)

    else:
        collector = DataCollector(date=args.date, debug=args.debug)
        collector.run(upload=args.upload)

if __name__ == "__main__":
    main()
