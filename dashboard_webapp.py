import dash
from dash import dcc, html, Input, Output, dash_table
import plotly.graph_objs as go
import pandas as pd
import sqlite3
from datetime import datetime, timezone
import os

EXTERNAL_STYLESHEETS = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

DB_PATH = os.path.join(os.path.dirname(__file__), "db", "dashboard.db")

# === DB Helpers ===

def get_allocations():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT project_id, start, end, hours
        FROM allocation
        ORDER BY project_id, start
    """, conn)
    conn.close()
    return df

def get_latest_fairshare(project_id):
    conn = sqlite3.connect(DB_PATH)
    row = pd.read_sql_query(f"""
        SELECT fairshare_score, cpu_core_hours, mem_gb_hours
        FROM fairshare_status
        WHERE project_id = ?
        ORDER BY day DESC
        LIMIT 1
    """, conn, params=(project_id,)).squeeze()
    conn.close()

    if row.empty:
        return (None, None, None)
    else:
        return row["fairshare_score"], row["cpu_core_hours"], row["mem_gb_hours"]

def interpret_fairshare(fairshare_score):
    if fairshare_score is None:
        return "(unknown)"
    if fairshare_score <= 0.05:
        return "(Excellent priority)"
    elif fairshare_score <= 0.10:
        return "(High priority)"
    elif fairshare_score <= 0.25:
        return "(Normal priority)"
    elif fairshare_score <= 0.50:
        return "(Low priority)"
    else:
        return "(Very low priority)"

def get_daily_user_usage(project_id, alloc_start, alloc_end):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"""
        SELECT day, username, SUM(core_hours_used) AS core_hours
        FROM user_core_hours
        WHERE project_id = ?
        AND day BETWEEN ? AND ?
        GROUP BY day, username
        ORDER BY day, username
    """, conn, params=(project_id, alloc_start, alloc_end))
    conn.close()
    return df

def get_user_total_usage(project_id, alloc_start, alloc_end):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"""
        SELECT username, SUM(core_hours_used) AS total_usage
        FROM user_core_hours
        WHERE project_id = ?
        AND day BETWEEN ? AND ?
        GROUP BY username
        ORDER BY total_usage DESC
    """, conn, params=(project_id, alloc_start, alloc_end))
    conn.close()
    return df

def get_alloc_used_sum():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"""
        SELECT project_id, day, SUM(core_hours_used) AS core_hours
        FROM user_core_hours
        GROUP BY project_id, day
    """, conn)

    # Now sum per allocation window
    alloc_df = get_allocations()

    result = {}
    for _, row in alloc_df.iterrows():
        mask = (df["project_id"] == row["project_id"]) & \
               (df["day"] >= row["start"]) & (df["day"] <= row["end"])
        used_sum = df[mask]["core_hours"].sum()
        result[(row["project_id"], row["start"], row["end"])] = used_sum

    conn.close()
    return result

# === DB "data freshness" time ===

def get_latest_update_time():
    conn = sqlite3.connect(DB_PATH)
    row = pd.read_sql_query("""
        SELECT MAX(update_time) AS latest_update_time
        FROM daily_usage
    """, conn).squeeze()
    conn.close()

    # row will be a string like '2025-06-12 21:20:06'
    if pd.isna(row):
        return None  # fallback case if DB is empty

    latest_dt = pd.to_datetime(row).tz_localize("UTC")
    return latest_dt


# === Load Allocation Info ===
alloc_df = get_allocations()
project_ids = alloc_df["project_id"].unique().tolist()

# Dropdown options + default latest per project
dropdown_options = {}
latest_alloc = {}

for project_id in project_ids:
    proj_df = alloc_df[alloc_df["project_id"] == project_id].copy()
    proj_df["label"] = proj_df.apply(
        lambda row: f"{row['start']} ~ {row['end']} ({row['hours']:,} core hours)", axis=1
    )
    proj_df["value"] = proj_df.apply(
        lambda row: f"{row['start']}|{row['end']}|{row['hours']}", axis=1
    )
    dropdown_options[project_id] = proj_df[["label", "value"]].to_dict("records")

    latest_row = proj_df.sort_values("start").iloc[-1]
    latest_alloc[project_id] = latest_row["value"]

# Precompute alloc used sum
alloc_used_sum = get_alloc_used_sum()
today_str = datetime.utcnow().strftime("%Y-%m-%d")
today = pd.to_datetime(today_str)

active_alloc_df = alloc_df[
    (pd.to_datetime(alloc_df["start"]) <= today) &
    (pd.to_datetime(alloc_df["end"]) >= today)
]
# --- FairShare Priority Ranking ---

def get_fairshare_priority_text():
    project_priority = []
    for project_id in project_ids:
        fairshare_score, _, _ = get_latest_fairshare(project_id)
        if fairshare_score is not None:
            project_priority.append((project_id, fairshare_score))
        else:
            project_priority.append((project_id, 1.0))  # fallback for missing

    project_priority_sorted = sorted(project_priority, key=lambda x: x[1])
    return " > ".join(f"{pid} ({score:.2%})" for pid, score in project_priority_sorted)



# === Dash App ===
app = dash.Dash(
    __name__,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    requests_pathname_prefix="/dashboard2/",
    routes_pathname_prefix="/dashboard2/",
)

# === Layout ===
app.layout = html.Div([
    html.H1("UC Earthquake Engineering Research HPC Utilization", style={"textAlign": "center"}),

    html.Div(id="last-updated-text", style={"textAlign": "right", "color": "gray", "fontSize": "14px"}),
    # force periodic callback to refresh the Last Updated line
    dcc.Interval(id="refresh-interval", interval=5*60*1000, n_intervals=0),  # every 5 min

    html.H3("Allocations Overview"),
    html.Ul(id="alloc-overview"),
       

    # Add section:
    html.H4("Project Priority based on FairShare Effective Usage"),
    html.Div("(lower % = higher priority)", style={"fontSize": "12px", "color": "gray", "marginBottom": "5px"}),
    html.Div(id="fairshare-priority-text", style={"fontSize": "18px", "fontWeight": "bold", "marginBottom": "20px"}),

    html.Hr(),

    # Sections for each project_id dynamically
    *[
        html.Div([
            html.H4(f"{project_id}"),
            html.Div([
                html.Label("Select Allocation:"),
                dcc.Dropdown(
                    id=f"dropdown-{project_id}",
                    options=dropdown_options[project_id],
                    value=latest_alloc[project_id]
                ),
            ], style={"width": "50%", "marginBottom": "20px"}),

            html.Div(id=f"fairshare-{project_id}", style={"marginBottom": "10px"}),

            dcc.Graph(id=f"plot-{project_id}"),

            html.H4("User Table"),
            dash_table.DataTable(
                id=f"table-{project_id}",
                columns=[
                    {"name": "Username", "id": "username"},
                    {"name": "Total Usage (core hours)", "id": "total_usage", "type": "numeric", "format": {"specifier": ",.0f"}},
                ],
                style_table={"width": "50%"},
                style_cell={"textAlign": "left"},
                style_header={"backgroundColor": "lightgrey", "fontWeight": "bold"},
            ),
            html.Hr(),
        ])
        for project_id in project_ids
    ]
])

# === Callbacks ===
for project_id in project_ids:
    @app.callback(
        [Output(f"plot-{project_id}", "figure"),
         Output(f"table-{project_id}", "data"),
         Output(f"fairshare-{project_id}", "children")],
        [Input(f"dropdown-{project_id}", "value")]
    )
    def update_project_view(selected_value, project_id=project_id):
        start_date, end_date, hours = selected_value.split("|")
        hours = int(hours)

        # === Cumulative usage plot ===
        daily_df = get_daily_user_usage(project_id, start_date, end_date)

        if daily_df.empty:
            cumulative_df = pd.DataFrame(columns=["day", "username", "cumulative_core_hours"])
        else:
            # Full date range
            today_date = datetime.utcnow().date()
            effective_end_date = min(datetime.strptime(end_date, "%Y-%m-%d").date(), today_date)
            full_days = pd.date_range(start=start_date, end=effective_end_date, freq="D")

            # All users present
            all_users = daily_df["username"].unique().tolist()

            # Prepare full grid DataFrame
            full_grid = pd.MultiIndex.from_product(
                [full_days, all_users], names=["day", "username"]
            ).to_frame(index=False)

            # Merge with actual data
            daily_df["day"] = pd.to_datetime(daily_df["day"])
            merged_df = pd.merge(
                full_grid,
                daily_df,
                how="left",
                on=["day", "username"]
            )
            merged_df["core_hours"] = merged_df["core_hours"].fillna(0)

            # Cumulative sum per user
            merged_df = merged_df.sort_values(["username", "day"])
            merged_df["cumulative_core_hours"] = merged_df.groupby("username")["core_hours"].cumsum()

            cumulative_df = merged_df
        
        fig = go.Figure()
        for username in cumulative_df["username"].unique():
            user_df = cumulative_df[cumulative_df["username"] == username]
            fig.add_trace(go.Scatter(
                x=user_df["day"],
                y=user_df["cumulative_core_hours"],
                mode="lines",
                name=username,
                stackgroup="one",
            ))
        fig.update_layout(
            title="Cumulative Usage",
            xaxis_title="Date",
            yaxis_title="Cumulative Core Hours",
            showlegend=True,
            height=500
        )

        # === User Table ===
        user_df = get_user_total_usage(project_id, start_date, end_date)
        user_table_data = user_df.to_dict("records")

        # === Fairshare
        fairshare_score, cpu_hours, mem_hours = get_latest_fairshare(project_id) 
        if fairshare_score is None:
            fairshare_text = "FairShare Effective Usage: N/A"
        else:
            fairshare_text = f"FairShare Effective Usage: {fairshare_score:.2%} {interpret_fairshare(fairshare_score)} | CPU Core Hours: {cpu_hours:,.0f} | MEM GB Hours: {mem_hours:,.0f}"

        return fig, user_table_data, fairshare_text

@app.callback(
    Output("last-updated-text", "children"),
    Input("refresh-interval", "n_intervals"),
)
def update_last_updated_text(n):
    mod_time = get_latest_update_time()
    if mod_time is None:
        mod_time_str = "N/A"
        age_hours = float("nan")
    else:
        mod_time_str = mod_time.strftime("%Y-%m-%d %H:%M:%S")
        age_hours = (datetime.now(timezone.utc) - mod_time).total_seconds() / 3600

    return f"Last Updated: {mod_time_str} (UTC) (≈ {age_hours:.1f} hours ago)"

@app.callback(
    Output("fairshare-priority-text", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_priority_text(n):
    return get_fairshare_priority_text()

@app.callback(
    Output("alloc-overview", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_alloc_overview(n):
    alloc_used_sum = get_alloc_used_sum()
    today = pd.to_datetime(datetime.utcnow().strftime("%Y-%m-%d"))
    active_alloc_df = get_allocations()
    active_alloc_df = active_alloc_df[
        (pd.to_datetime(active_alloc_df["start"]) <= today) &
        (pd.to_datetime(active_alloc_df["end"]) >= today)
    ]

    return [
        html.Li(
            f"{row['project_id']}: ({row['start']} ~ {row['end']}) "
            f"{int(alloc_used_sum[row['project_id'], row['start'], row['end']]):,} used / {row['hours']:,} core hours "
            f"({alloc_used_sum[row['project_id'], row['start'], row['end']] / row['hours']:.1%})"
        )
        for _, row in active_alloc_df.iterrows()
    ]

# === Run Server ===
if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=5092, debug=False)

