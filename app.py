import pandas as pd
import streamlit as st
from jira import JIRA

# 1. Jira Connection Setup
@st.cache_resource
def get_jira_client():
    # Replace with your actual Jira URL and authentication (Token or Basic Auth)
    options = {'server': 'https://your-domain.atlassian.net'}
    return JIRA(options, basic_auth=('your-email@domain.com', 'YOUR_API_TOKEN'))

jira = get_jira_client()

# 2. Smart Update / Delta Sync Logic
def sync_jira_data(local_df_path="jira_local_data.csv"):
    # Load existing local data if it exists [cite: 21]
    try:
        local_df = pd.read_csv(local_df_path)
    except FileNotFoundError:
        local_df = pd.DataFrame(columns=['Issue key', 'Summary', 'Status', 'Priority', 'Created', 'Resolution'])

    st.info("Checking Jira for recent updates...")

    # FIX: Changed query from 'created' to 'updated' to catch status modifications on old tickets 
    jql_query = 'project = "SVF" AND updated >= "-7d"' 
    
    # Fetch recently updated tickets from Jira API [cite: 23]
    # (Using a max_results limit to keep payload small and avoid crashes) [cite: 16, 17]
    updated_issues = jira.search_issues(jql_query, max_results=500)
    
    if not updated_issues:
        st.success("Dashboard is already up to date!")
        return local_df

    # Parse incoming updated issues into a temporary DataFrame
    new_data = []
    for issue in updated_issues:
        new_data.append({
            'Issue key': issue.key,
            'Summary': issue.fields.summary,
            'Status': issue.fields.status.name,
            'Priority': issue.fields.priority.name,
            'Created': issue.fields.created,
            'Resolution': issue.fields.resolution.name if issue.fields.resolution else 'Unresolved'
        })
    new_df = pd.DataFrame(new_data)

    # 3. Overwrite & Merge Logic
    # Set 'Issue key' as index temporarily to cleanly overwrite old statuses with the new ones 
    local_df.set_index('Issue key', inplace=True)
    new_df.set_index('Issue key', inplace=True)

    # combine_first prioritize 'new_df' values and overwrites matching rows in 'local_df' 
    updated_master_df = new_df.combine_first(local_df).reset_index()

    # Save data back to disk [cite: 21]
    updated_master_df.to_csv(local_df_path, index=False)
    st.success(f"Successfully synchronized {len(new_df)} updated tickets!")
    
    return updated_master_df

# 4. Streamlit Dashboard View
st.title("Facilities Jira Live Dashboard") [cite: 1]

# Run the sync
df = sync_jira_data()

# Display total numbers [cite: 34]
st.metric("Total Tickets Tracked", len(df)) [cite: 29, 30]

# Render the updated statuses
st.subheader("Ticket Breakdown by Status") [cite: 10]
status_counts = df['Status'].value_counts()
st.bar_chart(status_counts) [cite: 11, 21]

st.dataframe(df)
