#!/bin/bash
#SBATCH --job-name=dashboard_upload
#SBATCH --account=nesi00213
#SBATCH --ntasks=1
#SBATCH --time=00:01:00
#SBATCH --output=/home/baes/dashboard2/logs/upload_%j.log

# Initialize module system for cron jobs
echo "$(date): Starting data collection job"

export PATH=$PATH:/opt/nesi/CS400_centos7_bdw/rclone/1.62.2/bin:/opt/nesi/CS400_centos7_bdw/Python/3.11.6-foss-2023a/bin
echo "data collection"
python /home/baes/dashboard2/data_collection.py --upload 
echo "upload completed"
rclone lsjson dropbox:/QuakeCoRE/Public/dashboard/dashboard.db

echo "$(date): Job completed successfully"
