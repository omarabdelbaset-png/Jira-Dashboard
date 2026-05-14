import streamlit as st
import requests
import pandas as pd
from requests.auth import HTTPBasicAuth

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Facilities Jira Dashboard", layout="wide")
st.title("🏗️ Facilities Ongoing Projects Dashboard")

# --- 2. FETCH DATA FROM JIRA (WITH CACHING) ---
# ttl=3600 means the dashboard will hold the data for 1 hour before calling Jira again
@st.cache_data(ttl=3600)
def fetch_jira_data():
    # Get secure credentials from Streamlit Secrets
    JIRA_URL = st.secrets["JIRA_URL"]
    JIRA_EMAIL = st.secrets["JIRA_EMAIL"]
    JIRA_TOKEN = st.secrets["JIRA_TOKEN"]

    # The updated API endpoint and JQL query
    search_url = f"{JIRA_URL}/rest/api/2/search"
    
    # FIX: Dynamic date to include everything from start of year to today, newest first
    jql_query = 'project = "Facilities" AND created >= startOfYear() ORDER BY created DESC'
    
    params = {
        'jql': jql_query,
        'maxResults': 1000, # FIX: Increased limit so May tickets don't get cut off
        'fields': 'key,summary,status,created,assignee' # Add or remove fields as needed
    }

    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN)
    headers = {"Accept": "application/json"}

    response = requests.get(search_url, headers=headers, params=params, auth=auth)
    
    if response.status_code != 200:
        st.error(f"Error fetching data from Jira: {response.status_code}")
        return pd.DataFrame()

    data = response.json()
    issues = data.get('issues', [])

    # Process the JSON data into a clean list
    processed_issues = []
    for issue in issues:
        fields = issue['fields']
        processed_issues.append({
            "Ticket Key": issue['key'],
            "Summary": fields.get('summary', 'No Summary'),
            "Status": fields.get('status', {}).get('name', 'Unknown'),
            "Created Date": fields.get('created', '')[:10], # Truncate to just the date YYYY-MM-DD
            "Assignee": fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned'
        })
        
    return pd.DataFrame(processed_issues)

# --- 3. DISPLAY THE DASHBOARD ---
df = fetch_jira_data()

if not df.empty:
    # Top Metrics
    total_tickets = len(df)
    st.markdown(f"**Total Tickets (Year to Date):** {total_tickets}")
    
    # Display the table
    st.dataframe(df, use_container_width=True)
    
    # Optional: Add a simple bar chart of Statuses
    st.subheader("Tickets by Status")
    status_counts = df['Status'].value_counts()
    st.bar_chart(status_counts)
else:
    st.warning("No data found or failed to connect to Jira.")
