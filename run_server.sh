#!/bin/bash

# Activate your virtual environment (if using one)
source /home/qcadmin/py310/bin/activate

# Navigate to your dashboard directory
cd /home/qcadmin/dashboard2

# Run the Dash app (adjust the port as needed)
exec python dashboard_webapp.py
