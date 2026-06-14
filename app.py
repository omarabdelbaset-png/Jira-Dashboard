import pandas as pd
import streamlit as st
from jira import JIRA
import os

# =====================================================================
# 1. PAGE CONFIGURATION
# =====================================================================
st.set_page_config(
    page_title="Facilities Jira Live Dashboard",
    page_icon="📊",
    layout="wide"
)

# =====================================================================
# 2. JIRA CREDENTIALS & CONNECTION SETUP
# =====================================================================
JIRA_SERVER = "https://your-domain.atlassian.net"
JIRA_EMAIL = "your-email@domain.com"
JIRA_API_TOKEN = "YOUR_API_TOKEN"

@st.cache_resource
def get_jira_client():
    options = {'server': JIRA_SERVER}
    try:
        return JIRA(options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    except Exception as e:
        st.error(f"Failed to connect to Jira: {e}")
        return None

jira_client = get_jira_client()

# =====================================================================
# 3. DATA FETCHING & SYNC ENGINE
# =====================================================================
@st.cache_data(ttl=300) # Caches data for 5 minutes so it stays fast
def sync_jira_data(local_data_path="jira_export (9).csv"):
    # Load your historical CSV data
    if os.path.exists(local_data_path):
        try:
            local_df = pd.read_csv(local_data_path)
        except Exception:
            local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])
    else:
        local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])

    # Ensure 'Created' is a proper datetime format for the date filter to work
    if 'Created' in local_df.columns:
        local_df['Created'] = pd.to_datetime(local_df['Created'], errors='coerce')

    if jira_client is None:
        return local_df

    with st.spinner("Fetching the latest fast updates..."):
        try:
            # Fetch recent updates (Last 7 days)
            jql_query = 'project = "SVF" AND updated >= "-7d"'
            updated_issues = jira_client.search_issues(jql_query, maxResults=500)
            
            if not updated_issues:
                return local_df

            # Parse new incoming tickets
            new_records = []
            for issue in updated_issues:
                new_records.append({
                    'Issue key': issue.key,
                    'Summary': issue.fields.summary,
                    'Status': issue.fields.status.name,
                    'Priority': issue.fields.priority.name,
                    'Created': issue.fields.created,
                    'Resolution': issue.fields.resolution.name if issue.fields.resolution else 'Unresolved'
                })
            new_df = pd.DataFrame(new_records)
            new_df['Created'] = pd.to_datetime(new_df['Created'], errors='coerce')

            # Safely overwrite your CSV with any brand new updates
            local_df.set_index('Issue key', inplace=True)
            new_df.set_index('Issue key', inplace=True)

            synchronized_master = new_df.combine_first(local_df).reset_index()

            # Save the new master data back to your CSV
            synchronized_master.to_csv(local_data_path, index=False)
            
            return synchronized_master

        except Exception as api_error:
            st.error(f"Sync error: {api_error}. Displaying local data instead.")
            if 'Issue key' in local_df.index.names:
                local_df = local_df.reset_index()
            return local_df

# =====================================================================
# 4. MAIN DASHBOARD UI
# =====================================================================
def main():
    st.title("🏢 Facilities Operational Jira Analytics")
    st.markdown("---")

    # 1. Fetch the RAW, unfiltered data
    raw_df = sync_jira_data()

    # 2. CALCULATE ALL-TIME SATISFACTION FIRST (Before any filters are applied!)
    satisfaction_col_name = None
    for col in raw_df.columns:
        if 'satisfaction' in col.lower() or 'csat' in col.lower() or 'rating' in col.lower():
            satisfaction_col_name = col
            break

    if satisfaction_col_name:
        all_time_satisfaction = raw_df[satisfaction_col_name].notna().sum()
    else:
        all_time_satisfaction = 0

    # 3. Setup Sidebar & Date Filter
    st.sidebar.header("Filters")
    
    # Get min and max dates for the calendar default
    min_date = raw_df['Created'].min()
    max_date = raw_df['Created'].max()
    
    # Make sure we have valid dates
    if pd.isna(min_date) or pd.isna(max_date):
        date_range = st.sidebar.date_input("Select Date Range", [])
    else:
        date_range = st.sidebar.date_input("Select Date Range", [min_date.date(), max_date.date()])

    # Apply Date Filter to make our active dataframe (df)
    df = raw_df.copy() 
    if len(date_range) == 2:
        start_date = pd.to_datetime(date_range[0])
        # Add 1 day to end_date to include the full end day up to midnight
        end_date = pd.to_datetime(date_range[1]) + pd.Timedelta(days=1) 
        df = df[(df['Created'] >= start_date) & (df['Created'] < end_date)]

    # 4. Calculate metrics using the FILTERED data (df)
    total_tickets = len(df)
    open_tickets = len(df[df['Status'].isin(['Open', 'In Progress', 'Reopened', 'Waiting for customer'])])
    resolved_tickets = len(df[df['Status'].isin(['Resolved', 'Closed', 'Canceled', 'Done'])])

    # 5. Display the Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total tickets", total_tickets)
    with col2:
        st.metric("Open tickets", open_tickets, delta_color="inverse")
    with col3:
        st.metric("Resolved tickets", resolved_tickets)
    with col4:
        # Notice we pass the all_time_satisfaction here, so it never shrinks!
        if satisfaction_col_name:
            st.metric("Number of satisfaction", int(all_time_satisfaction))
        else:
            st.metric("Number of satisfaction", "No CSAT Data")

    st.markdown("---")

    # 6. Visual Charts
    left_chart_col, right_chart_col = st.columns(2)

    with left_chart_col:
        st.subheader("Ticket Stratification by Current Status")
        status_distribution = df['Status'].value_counts()
        st.bar_chart(status_distribution, color="#00d4ff")

    with right_chart_col:
        st.subheader("Priority Distribution Breakdown")
        priority_distribution = df['Priority'].value_counts()
        st.area_chart(priority_distribution, color="#daffde")

    # 7. Data Table
    st.subheader("📋 Unified Master Records Audit Logging")
    st.dataframe(
        df,
        column_config={
            "Issue key": st.column_config.TextColumn("Jira Key", help="Unique Identifier"),
            "Summary": st.column_config.TextColumn("Issue Description", width="large"),
            "Status": st.column_config.TextColumn("State"),
            "Priority": st.column_config.TextColumn("Severity Rating")
        },
        use_container_width=True,
        hide_index=True
    )

if __name__ == "__main__":
    main()
