#!/usr/bin/env python3
import argparse
from DashboardDB import DashboardDB
from constants import nesi_db_path
def main():
    parser = argparse.ArgumentParser(description="Insert a new allocation record.")
    parser.add_argument("--project_id", type=str, required=True, help="Project ID (e.g., nesi00213)")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--hours", type=int, default=1000000, help="Allocated hours (default: 1000000)")
    parser.add_argument("--machine", type=str, default="hpc", help="HPC machine name (default: hpc)")
    args = parser.parse_args()

    db = DashboardDB(nesi_db_path)
    db.insert_allocation(project_id=args.project_id, start=args.start, end=args.end, hours=args.hours, machine=args.machine)
    print(f"✅ Allocation inserted for project {args.project_id} from {args.start} to {args.end} with {args.hours} hours.")

if __name__ == "__main__":
    main()
