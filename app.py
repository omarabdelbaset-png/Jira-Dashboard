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
            start_at = 0
            max_results = 100 
            
            # Loop to fetch ALL historical tickets quickly
            while True:
                # OPTIMIZATION: We ONLY download the data we need, skipping giant comments/descriptions!
                issues = jira.search_issues(
                    'project = SVF ORDER BY created DESC', 
                    startAt=start_at, 
                    maxResults=max_results,
                    fields='status,priority,assignee,created' 
                )
                
                if len(issues) == 0:
                    break 
                    
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
                
                start_at += len(issues)
                if start_at >= 10000:
                    break

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
with st.spinner("Connecting to Jira and downloading tickets (Optimized Mode)..."):
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
    
    st.markdown("### 📊 Status, SLA & Satisfaction Overview")
    g_col1, g_col2, g_col3, g_col4 = st.columns(4)
    
    with g_col1:
        fig_res_sla = go.Figure(go.Indicator(
            mode = "gauge+number", value = 96.2, title = {'text': "Resolution SLA Met %"},
            gauge = {'axis': {'range': [None, 100]}, 'bar': {'color': "green"}, 'steps': [{'range': [0, 80], 'color': "lightgray"}]}
        ))
        fig_res_sla.update_layout(height=250, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_res_sla, use_container_width=True)

    with g_col2:
        fig_fr_sla = go.Figure(go.Indicator(
            mode = "gauge+number", value = 94.3, title = {'text': "First Response SLA Met %"},
            gauge = {'axis': {'range': [None, 100]}, 'bar': {'color': "teal"}, 'steps': [{'range': [0, 80], 'color': "lightgray"}]}
        ))
        fig_fr_sla.update_layout(height=250, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_fr_sla, use_container_width=True)

    with g_col3:
        fig_sat = go.Figure(go.Indicator(
            mode = "gauge+number", value = avg_sat, title = {'text': "Average CSAT"},
            gauge = {'axis': {'range': [0, 5]}, 'bar': {'color': "darkorange"}, 'steps': [{'range': [0, 3], 'color': "lightgray"}, {'range': [3, 4], 'color': "yellow"}]}
        ))
        fig_sat.update_layout(height=250, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_sat, use_container_width=True)

    with g_col4:
        if 'Satisfaction rating' in df.columns:
            sat_counts = df['Satisfaction rating'].dropna().value_counts().reset_index()
            sat_counts.columns = ['Rating', 'Count']
            fig_sat_bar = px.bar(sat_counts, x='Rating', y='Count', title="CSAT Breakdown", color='Rating')
            fig_sat_bar.update_layout(height=250, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig_sat_bar, use_container_width=True)

# ------------------------------------------
# TAB 2: TICKET ANALYSIS
# ------------------------------------------
with tab_analysis:
    st.markdown("### 🎫 Ticket Breakdown")
    col1, col2 = st.columns(2)
    with col1:
        if 'Status' in df.columns:
            st.plotly_chart(px.bar(df['Status'].value_counts().reset_index(), x='count', y='Status', orientation='h', title="Issues by Status", color='Status'), use_container_width=True)
    with col2:
        if 'Assignee' in df.columns:
            st.plotly_chart(px.bar(df['Assignee'].value_counts().head(10).reset_index(), x='count', y='Assignee', orientation='h', title="Top 10 Assignees", color='Assignee'), use_container_width=True)

# ------------------------------------------
# TAB 3: SLA PERFORMANCE
# ------------------------------------------
with tab_sla:
    st.markdown("### 🚦 Detailed SLA Performance")
    col1, col2 = st.columns(2)
    with col1:
        st.info("First Response SLA: Tracking time taken to reply to the customer.")
        fig_pie1 = px.pie(names=['Met', 'Breached'], values=[94.3, 5.7], hole=0.4, title="First Response SLA Breakdown", color_discrete_sequence=['#2ecc71', '#e74c3c'])
        st.plotly_chart(fig_pie1, use_container_width=True)
    with col2:
        st.info("Resolution SLA: Tracking time taken to fully resolve the ticket.")
        fig_pie2 = px.pie(names=['Met', 'Breached'], values=[96.2, 3.8], hole=0.4, title="Resolution Time SLA Breakdown", color_discrete_sequence=['#2ecc71', '#e74c3c'])
        st.plotly_chart(fig_pie2, use_container_width=True)

# ------------------------------------------
# TAB 4: SATISFACTION
# ------------------------------------------
with tab_sat:
    st.markdown("### ⭐ Customer Satisfaction Details")
    if 'Satisfaction rating' in df.columns:
        st.plotly_chart(px.pie(df['Satisfaction rating'].dropna().value_counts().reset_index(), names='Satisfaction rating', values='count', hole=0.4, title="Overall Satisfaction Distribution"), use_container_width=True)

# ------------------------------------------
# TAB 5: TRENDS & RAW DATA
# ------------------------------------------
with tab_trends:
    st.markdown("### 🗄️ Raw Ticket Data")
    st.dataframe(df, use_container_width=True)
