import os
import dash
from dash import dcc, html, Input, Output, dash_table
import plotly.graph_objs as go
import pandas as pd
import sqlite3
from datetime import datetime, timezone

EXTERNAL_STYLESHEETS = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "dashboard.db")

def get_project_allocation(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT project_id, hours, start, end FROM allocation ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    if result:
        project_id, hours, start_date, end_date = result
        return {
            "project_id": project_id,
            "hours": hours,
            "start_date": start_date,
            "end_date": end_date
        }
    raise ValueError("No allocation data found.")

def get_data():
    conn = sqlite3.connect(DB_PATH)
    daily = pd.read_sql_query("""
        SELECT day, username, SUM(core_hours_used) as usage
        FROM user_core_hours
        GROUP BY day, username
        ORDER BY day
    """, conn)

    user_totals = pd.read_sql_query("""
        SELECT username, SUM(core_hours_used) as total_usage
        FROM user_core_hours
        GROUP BY username
        ORDER BY total_usage DESC
    """, conn)

    conn.close()
    return daily, user_totals

def get_modification_time(db_path):
    mod_time = datetime.utcfromtimestamp(os.path.getmtime(db_path))
    age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - mod_time).total_seconds() / 3600
    return mod_time.strftime("%Y-%m-%d %H:%M:%S"), age_hours

# Create Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    requests_pathname_prefix="/dashboard2/",
    routes_pathname_prefix="/dashboard2/",
)

def serve_layout():
    try:
        project_info = get_project_allocation(DB_PATH)
    except ValueError:
        # Default values if allocation data is not found
        project_info = {
            "project_id": "N/A",
            "hours": 0,
            "start_date": "N/A",
            "end_date": "N/A"
        }
        # Consider logging this event
        
    daily_df, user_totals_df = get_data()
    mod_time_str, age_hours = get_modification_time(DB_PATH)

    total_daily_usage_sum = 0
    total_usage_x = []
    total_usage_y = []
    stacked_user_data = []

    if not daily_df.empty:
        pivot_df = daily_df.pivot(index="day", columns="username", values="usage").fillna(0).cumsum()
        total_daily_usage_sum = daily_df['usage'].sum()
        
        total_usage_grouped_sum = daily_df.groupby("day")["usage"].sum().cumsum()
        total_usage_x = total_usage_grouped_sum.index
        total_usage_y = total_usage_grouped_sum.values
        
        stacked_user_data = [
            go.Scatter(
                x=pivot_df.index,
                y=pivot_df[user],
                stackgroup="one",
                name=user,
                mode="none"
            ) for user in pivot_df.columns
        ]
    else:
        # If daily_df is empty, pivot_df will be empty, and graph data will be empty lists
        pass


    return html.Div([
        html.H1("UC Earthquake Engineering Research HPC Utilization", style={"textAlign": "center"}),

        html.H2("Current Allocation"),
        html.Ul([
            html.Li(f"NeSI ({project_info['project_id']}) : "
                    f"{int(total_daily_usage_sum):,} used / {project_info['hours']:,} allocated core hours "
                    f"{project_info['start_date']} to {project_info['end_date']}", style={"fontSize": "14px"})
        ]),

        html.Div(f"Last Updated: {mod_time_str} (UTC) (≈ {age_hours:.1f} hours ago)",
                 style={"textAlign": "right", "color": "gray", "fontSize": "14px"}),

        html.H3("Cumulative Usage by All Users"),
        dcc.Graph(
            id="total-usage-graph",
            figure={
                "data": [
                    go.Scatter(
                        x=total_usage_x,
                        y=total_usage_y,
                        mode="lines+markers",
                        name="Total Usage"
                    )
                ],
                "layout": go.Layout(
                    xaxis={"title": "Date"},
                    yaxis={"title": "Cumulative Core Hours"},
                    margin={"l": 40, "b": 40, "t": 10, "r": 10},
                )
            }
        ),

        html.H3("Cumulative Usage by Each User"),
        dcc.Graph(
            id="stacked-user-graph",
            figure={
                "data": stacked_user_data,
                "layout": go.Layout(
                    xaxis={"title": "Date"},
                    yaxis={"title": "Cumulative Core Hours"},
                    showlegend=True
                )
            }
        ),

        html.H4("Total Core Hour Usage by User"),
        dash_table.DataTable(
            id="user-table",
            columns=[
                {"name": "Username", "id": "username"},
                {"name": "Total Usage (core hours)", "id": "total_usage", "type": "numeric", "format": {"specifier": ",.0f"}}
            ],
            data=user_totals_df.to_dict("records"),
            style_table={'width': '50%'},
            style_cell={'textAlign': 'left'},
            style_header={'backgroundColor': 'lightgrey', 'fontWeight': 'bold'},
        )
    ])

app.layout = serve_layout

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=5092)
