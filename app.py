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
# 3. SELF-HEALING DELTA SYNC ENGINE
# =====================================================================
def sync_jira_data(local_data_path="jira_local_data.csv"):
    # Load the local dataset
    if os.path.exists(local_data_path):
        try:
            local_df = pd.read_csv(local_data_path)
        except Exception:
            local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])
    else:
        local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])

    if jira_client is None:
        st.warning("Running dashboard in OFFLINE mode using cached historical data.")
        return local_df

    with st.spinner("Synchronizing with Jira Cloud API (Running Self-Healing Check)..."):
        try:
            # 1. Identify tickets the dashboard CURRENTLY thinks are Open/In Progress
            active_tickets = local_df[local_df['Status'].isin(['Open', 'In Progress', 'Reopened'])]['Issue key'].tolist()
            
            # 2. Build a query to get recent updates (expanded to 14 days for safety)
            jql_query = 'project = "SVF" AND updated >= "-14d"'
            
            # 3. SELF-HEALING: Explicitly force Jira to re-check the tickets we think are open
            # We cap it at 200 keys so the query string doesn't get too long for the Jira API
            if active_tickets:
                keys_to_check = ",".join(active_tickets[:200])
                jql_query = f'project = "SVF" AND (updated >= "-14d" OR issueKey in ({keys_to_check}))'

            # maxResults=False forces automatic, safe pagination. It will NEVER crash Jira!
            updated_issues = jira_client.search_issues(jql_query, maxResults=False)
            
            if not updated_issues:
                st.sidebar.success("⚡ Dashboard is perfectly synced.")
                return local_df

            # Parse the fresh data
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

            # Overwrite old records with the new correct statuses
            local_df.set_index('Issue key', inplace=True)
            new_df.set_index('Issue key', inplace=True)

            # combine_first automatically forces new_df values to overwrite local_df values
            synchronized_master = new_df.combine_first(local_df).reset_index()

            # Save corrected data back to disk
            synchronized_master.to_csv(local_data_path, index=False)
            st.sidebar.success(f"🔄 Sync successful! Checked and updated {len(new_df)} issues.")
            return synchronized_master

        except Exception as api_error:
            st.error(f"Sync error: {api_error}. Displaying local data instead.")
            if 'Issue key' in local_df.index.names:
                local_df = local_df.reset_index()
            return local_df

master_df = sync_jira_data()

# =====================================================================
# 4. DATA VISUALIZATION
# =====================================================================
st.title("🏢 Facilities Operational Jira Analytics")
st.caption("Real-Time Incident Management Optimization - Self-Healing Enabled")
st.markdown("---")

total_tickets = len(master_df)
open_tickets = len(master_df[master_df['Status'].isin(['Open', 'In Progress', 'Reopened'])])
resolved_tickets = len(master_df[master_df['Status'].isin(['Resolved', 'Closed', 'Canceled'])])

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Total Tickets Monitored", value=total_tickets)
with col2:
    st.metric(label="Active Backlog (Open / In Progress)", value=open_tickets, delta_color="inverse")
with col3:
    st.metric(label="Completed Operational Inquiries", value=resolved_tickets)

st.markdown("---")

left_chart_col, right_chart_col = st.columns(2)

with left_chart_col:
    st.subheader("Ticket Stratification by Current Status")
    status_distribution = master_df['Status'].value_counts()
    st.bar_chart(status_distribution, color="#00d4ff")

with right_chart_col:
    st.subheader("Priority Distribution Breakdown")
    priority_distribution = master_df['Priority'].value_counts()
    st.area_chart(priority_distribution, color="#daffde")

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
