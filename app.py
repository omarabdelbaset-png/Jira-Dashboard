import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from jira import JIRA
import os

# Set up the page layout
st.set_page_config(page_title="Jira SVF Dashboard", layout="wide", page_icon="📊")

# ==========================================
# --- 1. CONFIGURATION & SECRETS ---
# ==========================================
JIRA_SERVER = "https://itsupportsivision.atlassian.net"
CSV_FILE = "Jira Service Desk (8).csv"

# Safely pull secrets from Streamlit Community Cloud
try:
    JIRA_EMAIL = st.secrets["JIRA_EMAIL"]
    JIRA_TOKEN = st.secrets["JIRA_API_TOKEN"]
except Exception:
    # Fallback if secrets are missing
    JIRA_EMAIL = None
    JIRA_TOKEN = None

# ==========================================
# --- 2. DATA FETCHER (LIVE OR CSV) ---
# ==========================================
@st.cache_data(ttl=600) # Refreshes every 10 minutes automatically
def load_data():
    df = pd.DataFrame()
    is_live = False

    # 1. Try Live Jira Connection First
    if JIRA_EMAIL and JIRA_TOKEN:
        try:
            jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
            
            data = []
            start_at = 0
            max_results = 100 # Jira's safe limit per page
            
            # Loop to fetch ALL historical tickets (Pagination)
            while True:
                issues = jira.search_issues('project = SVF ORDER BY created DESC', startAt=start_at, maxResults=max_results)
                
                if len(issues) == 0:
                    break # Stop when there are no more tickets left
                    
                for issue in issues:
                    # Safely extract Jira fields
                    status = str(issue.fields.status)
                    priority = str(issue.fields.priority) if hasattr(issue.fields, 'priority') and issue.fields.priority else 'None'
                    assignee = str(issue.fields.assignee) if hasattr(issue.fields, 'assignee') and issue.fields.assignee else 'Unassigned'
                    
                    data.append({
                        'Issue key': issue.key,
                        'Status': status,
                        'Priority': priority,
                        'Assignee': assignee,
                        'Created': issue.fields.created,
                        # Fallbacks for SLA/Satisfaction fields to map to CSV style
                        'Custom field (Time to first response)': 1 if 'Open' not in status else -1, 
                        'Custom field (Time to resolution)': 1 if 'Done' in status else -1,
                        'Satisfaction rating': 5 if 'Done' in status else None 
                    })
                
                start_at += len(issues)
                
                # Safety net to prevent infinite loops (stops at 10,000 tickets)
                if start_at >= 10000:
                    break

            df = pd.DataFrame(data)
            is_live = True
        except Exception as e:
            pass
