import os
import dash
from dash import dcc, html, Input, Output, dash_table
import plotly.graph_objs as go
import pandas as pd
import sqlite3
from datetime import datetime, timezone

EXTERNAL_STYLESHEETS = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "dashboard.db")

def get_all_allocations(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Access columns by name
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, project_id, start, end FROM allocation ORDER BY start DESC, id DESC")
        allocations = cursor.fetchall()
        options = [{'label': f"{row['project_id']} ({row['start']} - {row['end']})", 'value': row['id']} for row in allocations]
    except sqlite3.OperationalError as e:
        print(f"Database error fetching all allocations: {e}")
        options = []
    conn.close()
    return options

def get_allocation_details(db_path, allocation_id=None):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    result = None
    try:
        if allocation_id is not None:
            cursor.execute("SELECT id, project_id, hours, start, end FROM allocation WHERE id = ?", (allocation_id,))
        else: # Get latest
            cursor.execute("SELECT id, project_id, hours, start, end FROM allocation ORDER BY start DESC, id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            result = {
                "id": row[0],
                "project_id": row[1],
                "hours": row[2],
                "start_date": row[3],
                "end_date": row[4]
            }
    except sqlite3.OperationalError as e:
        print(f"Database error fetching allocation details: {e}")
        # Fallthrough to return None
    conn.close()
    return result

def get_data(db_path, start_date=None, end_date=None):
    conn = sqlite3.connect(db_path)
    params_daily = []
    params_totals = []
    
    daily_query = """
        SELECT day, username, SUM(core_hours_used) as usage
        FROM user_core_hours
    """
    user_totals_query = """
        SELECT username, SUM(core_hours_used) as total_usage
        FROM user_core_hours
    """

    where_clauses = []
    if start_date:
        where_clauses.append("day >= ?")
        params_daily.append(start_date)
        params_totals.append(start_date)
    if end_date:
        where_clauses.append("day <= ?")
        params_daily.append(end_date)
        params_totals.append(end_date)

    if where_clauses:
        filter_condition = " WHERE " + " AND ".join(where_clauses)
        daily_query += filter_condition
        user_totals_query += filter_condition
    
    daily_query += " GROUP BY day, username ORDER BY day"
    user_totals_query += " GROUP BY username ORDER BY total_usage DESC"

    try:
        daily = pd.read_sql_query(daily_query, conn, params=params_daily if params_daily else None)
        user_totals = pd.read_sql_query(user_totals_query, conn, params=params_totals if params_totals else None)
    except pd.io.sql.DatabaseError as e:
        print(f"Database error in get_data: {e}. Returning empty DataFrames.")
        daily = pd.DataFrame(columns=['day', 'username', 'usage'])
        user_totals = pd.DataFrame(columns=['username', 'total_usage'])
    finally:
        if conn:
            conn.close()
    
    # Ensure empty dataframes if no date range and we want to enforce filtering
    if not (start_date and end_date) and not (daily.empty and user_totals.empty): # if no valid range, but data was fetched (e.g. no WHERE clause)
        # This logic might need adjustment based on desired behavior for "no allocation selected"
        # For now, if start_date or end_date is None, we assume data should be filtered to empty
        # unless the query itself returned empty due to no data in the full table.
        # The current SQL structure will fetch all if no dates.
        # Let's enforce empty if dates are not set, meaning an allocation period is required.
        if start_date is None or end_date is None:
             daily = pd.DataFrame(columns=['day', 'username', 'usage'])
             user_totals = pd.DataFrame(columns=['username', 'total_usage'])


    return daily, user_totals


def get_modification_time(db_path):
    try:
        mod_time_stamp = os.path.getmtime(db_path)
        mod_time = datetime.utcfromtimestamp(mod_time_stamp)
        age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - mod_time).total_seconds() / 3600
        return mod_time.strftime("%Y-%m-%d %H:%M:%S"), age_hours
    except FileNotFoundError:
        return "N/A", float('inf')


app = dash.Dash(
    __name__,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    requests_pathname_prefix="/dashboard2/",
    routes_pathname_prefix="/dashboard2/",
)
server = app.server # For Gunicorn

def create_app_layout():
    all_allocation_options = get_all_allocations(DB_PATH)
    initial_selected_value = None
    if all_allocation_options:
        # Try to get the ID of the latest allocation to pre-select it
        latest_alloc_details = get_allocation_details(DB_PATH, None) # None gets latest
        if latest_alloc_details:
            initial_selected_value = latest_alloc_details['id']
        else: # Fallback if latest couldn't be fetched but options exist
            initial_selected_value = all_allocation_options[0]['value']


    return html.Div([
        html.H1("UC Earthquake Engineering Research HPC Utilization", style={"textAlign": "center"}),
        dcc.Dropdown(
            id='allocation-dropdown',
            options=all_allocation_options,
            value=initial_selected_value,
            clearable=False,
            style={'width': '50%', 'margin': 'auto', 'marginBottom': '20px'}
        ),
        html.Div(id='page-content')
    ])

app.layout = create_app_layout()

@app.callback(
    Output('page-content', 'children'),
    Input('allocation-dropdown', 'value')
)
def render_allocation_data(selected_allocation_id):
    if selected_allocation_id is None:
        # This case should ideally not happen if dropdown is not clearable and has a value
        # Or handle by showing a "select an allocation" message
        latest_alloc = get_allocation_details(DB_PATH, None)
        if latest_alloc:
            selected_allocation_id = latest_alloc['id']
        else:
            return html.Div("No allocations available or selected.")

    project_info = get_allocation_details(DB_PATH, selected_allocation_id)
    
    start_date_filter, end_date_filter = None, None
    if project_info:
        start_date_filter = project_info.get('start_date')
        end_date_filter = project_info.get('end_date')
    else: # Default/fallback project_info if selected_allocation_id was invalid or db error
        project_info = {
            "project_id": "N/A", "hours": 0,
            "start_date": "N/A", "end_date": "N/A", "id": "N/A"
        }

    daily_df, user_totals_df = get_data(DB_PATH, start_date_filter, end_date_filter)
    mod_time_str, age_hours = get_modification_time(DB_PATH)

    total_daily_usage_sum = 0
    total_usage_x = []
    total_usage_y = []
    stacked_user_data = []

    if not daily_df.empty:
        # Ensure 'usage' column is numeric, coercing errors to NaN, then fillna(0)
        daily_df['usage'] = pd.to_numeric(daily_df['usage'], errors='coerce').fillna(0)
        total_daily_usage_sum = daily_df['usage'].sum()
        
        # Pivot table for stacked graph
        pivot_df = daily_df.pivot_table(index="day", columns="username", values="usage", fill_value=0).cumsum()
        
        total_usage_grouped_sum = daily_df.groupby("day")["usage"].sum().cumsum()
        total_usage_x = total_usage_grouped_sum.index
        total_usage_y = total_usage_grouped_sum.values
        
        stacked_user_data = [
            go.Scatter(
                x=pivot_df.index,
                y=pivot_df[user],
                stackgroup="one",
                name=user,
                mode="lines" # Changed from "none" to "lines" for visibility, or "area"
            ) for user in pivot_df.columns
        ]
    else: # daily_df is empty
        # Ensure pivot_df is an empty DataFrame with expected structure if needed downstream
        # For now, graph data lists will remain empty.
        pass

    return html.Div([
        html.H2("Selected Allocation Details"),
        html.Ul([
            html.Li(f"Project ({project_info.get('project_id', 'N/A')}) : "
                    f"{int(total_daily_usage_sum):,} used / {project_info.get('hours', 0):,} allocated core hours "
                    f"({project_info.get('start_date', 'N/A')} to {project_info.get('end_date', 'N/A')})", style={"fontSize": "14px"})
        ]),

        html.Div(f"Database Last Updated: {mod_time_str} (UTC) (≈ {age_hours:.1f} hours ago)",
                 style={"textAlign": "right", "color": "gray", "fontSize": "14px"}),

        html.H3("Cumulative Usage by All Users (for selected allocation)"),
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

        html.H3("Cumulative Usage by Each User (for selected allocation)"),
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

        html.H4("Total Core Hour Usage by User (for selected allocation)"),
        dash_table.DataTable(
            id="user-table",
            columns=[
                {"name": "Username", "id": "username"},
                {"name": "Total Usage (core hours)", "id": "total_usage", "type": "numeric", "format": {"specifier": ",.0f"}}
            ],
            data=user_totals_df.to_dict("records") if not user_totals_df.empty else [],
            style_table={'width': '50%'},
            style_cell={'textAlign': 'left'},
            style_header={'backgroundColor': 'lightgrey', 'fontWeight': 'bold'},
        )
    ])


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=5092, debug=True)
