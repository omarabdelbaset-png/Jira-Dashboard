import pandas as pd
import streamlit as st
from jira import JIRA
import os

# =====================================================================
# 1. PAGE CONFIGURATION & THEME SETUP
# =====================================================================
st.set_page_config(
    page_title="Facilities Jira Live Dashboard",
    page_icon="📊",
    layout="wide"
)

# =====================================================================
# 2. JIRA CREDENTIALS & CONNECTION SETUP
# =====================================================================
# For maximum security, replace these strings with st.secrets configurations 
# or set them as environment variables before running.
JIRA_SERVER = "https://your-domain.atlassian.net"
JIRA_EMAIL = "your-email@domain.com"
JIRA_API_TOKEN = "YOUR_API_TOKEN"

@st.cache_resource
def get_jira_client():
    """Establishes and caches the secure connection to Atlassian Jira API."""
    options = {'server': JIRA_SERVER}
    try:
        return JIRA(options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    except Exception as e:
        st.error(f"Failed to connect to Jira Instance: {e}")
        return None

# Initialize the cached connection instance
jira_client = get_jira_client()

# =====================================================================
# 3. DELTA SYNC ENGINE (SMART REFRESH WITH AUTO-OVERWRITE MECHANISM)
# =====================================================================
def sync_jira_data(local_data_path="jira_local_data.csv"):
    """
    Implements a Delta Sync framework to fetch only recently modified records.
    Merges updates into the local cache file, fixing status drift bugs.
    """
    # Step A: Load or initialize the local dataset cache
    if os.path.exists(local_data_path):
        try:
            local_df = pd.read_csv(local_data_path)
        except Exception:
            # Fallback if file corrupts
            local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])
    else:
        local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])

    # Verify if Jira client is alive before executing network fetch
    if jira_client is None:
        st.warning("Running dashboard in OFFLINE mode using cached historical data.")
        return local_df

    with st.spinner("Synchronizing with Jira Cloud API (Fetching recent modifications)..."):
        try:
            # FIXED JQL: Tracks 'updated' timestamp instead of 'created' timestamp
            # to intercept status transformations on older tickets without a full database download.
            jql_query = 'project = "SVF" AND updated >= "-7d"'
            
            # Fetch batch of altered issues (capped at 500 records per check to ensure rapid performance)
            updated_issues = jira_client.search_issues(jql_query, max_results=500)
            
            if not updated_issues:
                st.sidebar.success("⚡ Local sync database matches Jira Cloud live data.")
                return local_df

            # Step B: Parse incoming network objects into flat tabular structures
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

            # Step C: Execute structural overwrite via key alignments
            local_df.set_index('Issue key', inplace=True)
            new_df.set_index('Issue key', inplace=True)

            # Pandas index alignment ensures newest data overrides old data rows while keeping historical logs intact
            synchronized_master = new_df.combine_first(local_df).reset_index()

            # Step D: Save optimized schema changes back to disk
            synchronized_master.to_csv(local_data_path, index=False)
            st.sidebar.success(f"🔄 Delta Sync successful! Updated {len(new_df)} issues.")
            return synchronized_master

        except Exception as api_error:
            st.error(f"Sync engine pipeline error: {api_error}. Displaying local data instead.")
            if 'Issue key' in local_df.index.names:
                local_df = local_df.reset_index()
            return local_df

# Execute execution cycle
master_df = sync_jira_data()

# =====================================================================
# 4. DATA VISUALIZATION & KPI METRIC CARDS
# =====================================================================
st.title("🏢 Facilities Operational Jira Analytics")
st.caption("Real-Time Incident Management Optimization Powered by Gemini Delta Sync Engine v1.1")
st.markdown("---")

# Row 1: Primary Aggregate Quantifications
total_tickets = len(master_df)
open_tickets = len(master_df[master_df['Status'].isin(['Open', 'In Progress', 'Reopened'])])
resolved_tickets = len(master_df[master_df['Status'].isin(['Resolved', 'Closed'])])

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Total Tickets Monitored", value=total_tickets)
with col2:
    st.metric(label="Active Backlog (Open / In Progress)", value=open_tickets, delta_color="inverse")
with col3:
    st.metric(label="Completed Operational Inquiries", value=resolved_tickets)

st.markdown("---")

# Row 2: Visual Diagnostics
left_chart_col, right_chart_col = st.columns(2)

with left_chart_col:
    st.subheader("Ticket Stratification by Current Status")
    status_distribution = master_df['Status'].value_counts()
    st.bar_chart(status_distribution, color="#00d4ff")

with right_chart_col:
    st.subheader("Priority Distribution Breakdown")
    priority_distribution = master_df['Priority'].value_counts()
    st.area_chart(priority_distribution, color="#daffde")

# Row 3: Master Data Audit Spreadsheet
st.subheader("📋 Unified Master Records Audit Logging")
st.dataframe(
    master_df,
    column_config={
        "Issue key": st.column_config.TextColumn("Jira Key", help="Unique Identifier"),
        "Summary": st.column_config.TextColumn("Issue Description", width="large"),
        "Status": st.column_config.TextColumn("State"),
        "Priority": st.column_config.TextColumn("Severity Rating")
    },
    use_container_width=True,
    hide_index=True
)
