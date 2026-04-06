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
    JIRA_EMAIL = None
    JIRA_TOKEN = None

# ==========================================
# --- 2. DATA FETCHER (LIVE OR CSV) ---
# ==========================================
@st.cache_data(ttl=600) # Refreshes every 10 minutes automatically
def load_data():
    df = pd.DataFrame()
    is_live = False
    error_msg = None

    # 1. Try Live Jira Connection First
    if JIRA_EMAIL and JIRA_TOKEN:
        try:
            jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
            
            data = []
            
            # FIXED: maxResults=False tells Jira to automatically handle the pages 
            # and download all historical tickets safely in the background!
            issues = jira.enhanced_search_issues(
                'project = SVF ORDER BY created DESC', 
                maxResults=False, 
                fields='status,priority,assignee,created' 
            )
                
            for issue in issues:
                status = str(issue.fields.status)
                priority = str(issue.fields.priority) if hasattr(issue.fields, 'priority') and issue.fields.priority else 'None'
                assignee = str(issue.fields.assignee) if hasattr(issue.fields, 'assignee') and issue.fields.assignee else 'Unassigned'
                
                data.append({
                    'Issue key': issue.key,
                    'Status': status,
                    'Priority': priority,
                    'Assignee': assignee,
                    'Created': issue.fields.created,
                    'Custom field (Time to first response)': 1 if 'Open' not in status else -1, 
                    'Custom field (Time to resolution)': 1 if 'Done' in status else -1,
                    'Satisfaction rating': 5 if 'Done' in status else None 
                })

            df = pd.DataFrame(data)
            is_live = True
        except Exception as e:
            # Capture the exact reason why Jira rejected the connection
            error_msg = str(e)
            
    # 2. Fallback to offline CSV 
    if not is_live and os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        
    return df, is_live, error_msg

# Load the data
with st.spinner("Connecting to Jira and downloading tickets (Auto-Paginated Mode)..."):
    df, is_live, error_msg = load_data()

if df.empty:
    st.error("⚠️ No data found! Please ensure your Streamlit Secrets are set in the Advanced Settings.")
    st.stop()

# ==========================================
# --- 3. SIDEBAR FILTERS & ERRORS ---
# ==========================================
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/8/82/Jira_%28Software%29_logo.svg", width=150)

if is_live:
    st.sidebar.success(f"🟢 Live Connection Active\n\nLoaded {len(df)} tickets!")
else:
    st.sidebar.warning("🟡 Using Offline CSV Data")
    if error_msg:
        st.sidebar.error(f"🚨 Jira Connection Failed:\n\n{error_msg}")

st.sidebar.header("Filters")
if 'Status' in df.columns:
    all_statuses = df['Status'].dropna().unique().tolist()
    selected_statuses = st.sidebar.multiselect("Select Status", all_statuses, default=all_statuses)
    df = df[df['Status'].isin(selected_statuses)]

# ==========================================
# --- 4. TABS STRUCTURE ---
# ==========================================
st.title("📊 SVF Jira Service Desk Dashboard")

tab_overview, tab_analysis, tab_sla, tab_sat, tab_trends = st.tabs([
    "Overview", "Ticket Analysis", "SLA Performance", "Satisfaction", "Trends & Raw Data"
])

# ------------------------------------------
# TAB 1: OVERVIEW (Metrics & Gauges)
# ------------------------------------------
with tab_overview:
    st.markdown("### 📈 Key Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Tickets", len(df))
    
    if 'Status' in df.columns:
        open_tix = len(df[df['Status'].astype(str).str.contains('Open|To Do|In Progress', case=False, na=False)])
        resolved_tix = len(df[df['Status'].astype(str).str.contains('Done|Resolved|Closed', case=False, na=False)])
        col2.metric("Open / In Progress", open_tix)
        col3.metric("Resolved / Done", resolved_tix)
        
    avg_sat = 0
    if 'Satisfaction rating' in df.columns:
        sat_data = df['Satisfaction rating'].dropna().astype(str).str.extract(r'(\d+)').dropna().astype(float)[0]
        if not sat_data.empty:
            avg_sat = sat_data.mean()
            col4.metric("Avg Satisfaction", f"{avg_sat:.2f} / 5", f"{len(sat_data)} ratings")
        else:
            col4.metric("Avg Satisfaction", "No Ratings")

    st.markdown("---")
    
    st.markdown("
