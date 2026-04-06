import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from jira import JIRA

st.set_page_config(
    page_title="Jira Service Desk Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stMetric { background-color: #f8f9fa; border-radius: 8px; padding: 12px; }
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 16px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# --- CONFIGURATION & SECRETS ---
# ==========================================
JIRA_SERVER = "https://itsupportsivision.atlassian.net"
FILE_NAME = "Jira Service Desk (8).csv"

try:
    JIRA_EMAIL = st.secrets["JIRA_EMAIL"]
    JIRA_TOKEN = st.secrets["JIRA_API_TOKEN"]
except Exception:
    JIRA_EMAIL = None
    JIRA_TOKEN = None

def parse_hhmm(val):
    try:
        parts = str(val).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return np.nan

# --- HELPER FUNCTIONS FOR RAW JIRA DATA ---
def parse_sla_to_hhmm(sla_obj):
    if not sla_obj: return ""
    if isinstance(sla_obj, str) and ":" in sla_obj: return sla_obj
    try:
        cycle = None
        if isinstance(sla_obj, dict):
            if 'completedCycles' in sla_obj and sla_obj['completedCycles']:
                cycle = sla_obj['completedCycles'][-1]
            elif 'ongoingCycle' in sla_obj:
                cycle = sla_obj['ongoingCycle']
        if cycle:
            millis = cycle.get('remainingTime', {}).get('millis', 0)
            breached = cycle.get('breached', False)
            mins = millis / 60000.0
            
            if breached and mins > 0: mins = -mins
            is_neg = mins < 0
            mins = abs(int(mins))
            res = f"{mins // 60:02d}:{mins % 60:02d}"
            return f"-{res}" if is_neg else res
    except: pass
    return ""

def parse_sat(sat_obj):
    if not sat_obj: return None
    if isinstance(sat_obj, dict): return sat_obj.get('rating', None)
    try: return float(sat_obj)
    except: return None
    
def parse_req(req_obj):
    if not req_obj: return "Unknown"
    if isinstance(req_obj, dict): 
        return req_obj.get('requestType', {}).get('name', req_obj.get('name', 'Unknown'))
    return str(req_obj)

# ==========================================
# --- DATA FETCHER (LIVE OR CSV) ---
# ==========================================
@st.cache_data(ttl=600)
def load_data():
    df_raw = pd.DataFrame()
    is_live = False
    error_msg = None

    if JIRA_EMAIL and JIRA_TOKEN:
        try:
            jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
            
            # 1. DYNAMIC FIELD SCANNER: Find the hidden Custom IDs automatically
            all_fields = jira.fields()
            def get_id(names):
                for f in all_fields:
                    if f['name'].lower() in [n.lower() for n in names]: return f['id']
                return None
                
            tfr_id = get_id(['time to first response'])
            ttr_id = get_id(['time to resolution'])
            sat_id = get_id(['satisfaction', 'satisfaction rating'])
            req_id = get_id(['request type'])

            fetch_fields = ['status', 'priority', 'assignee', 'created', 'resolutiondate', 'updated', 'issuetype', 'resolution', 'reporter', 'summary']
            for cid in [tfr_id, ttr_id, sat_id, req_id]:
                if cid: fetch_fields.append(cid)

            # 2. FETCH DATA
            data = []
            issues = jira.enhanced_search_issues(
                'project = SVF ORDER BY created DESC', 
                maxResults=False, 
                fields=','.join(fetch_fields)
            )
                
            for issue in issues:
                raw_dict = issue.raw['fields'] # Access raw JSON to safely pull complex SLA objects
                
                status = str(issue.fields.status)
                priority = str(issue.fields.priority) if hasattr(issue.fields, 'priority') and issue.fields.priority else 'None'
                assignee = str(issue.fields.assignee) if hasattr(issue.fields, 'assignee') and issue.fields.assignee else 'Unassigned'
                reporter = str(issue.fields.reporter) if hasattr(issue.fields, 'reporter') and issue.fields.reporter else 'Unknown'
                issuetype = str(issue.fields.issuetype) if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype else 'Unknown'
                resolution = str(issue.fields.resolution) if hasattr(issue.fields, 'resolution') and issue.fields.resolution else 'Unresolved'
                
                data.append({
                    'Issue key': issue.key,
                    'Summary': issue.fields.summary,
                    'Status': status,
                    'Status Category': 'Done' if 'Done' in status or 'Resolved' in status else ('In Progress' if 'Progress' in status else 'To Do'),
                    'Priority': priority,
                    'Assignee': assignee,
                    'Reporter': reporter,
                    'Issue Type': issuetype,
                    'Resolution': resolution,
                    'Created': pd.to_datetime(issue.fields.created).strftime("%d/%b/%y %I:%M %p") if issue.fields.created else None,
                    'Resolved': pd.to_datetime(issue.fields.resolutiondate).strftime("%d/%b/%y %I:%M %p") if hasattr(issue.fields, 'resolutiondate') and issue.fields.resolutiondate else None,
                    'Updated': pd.to_datetime(issue.fields.updated).strftime("%d/%b/%y %I:%M %p") if hasattr(issue.fields, 'updated') and issue.fields.updated else None,
                    
                    # 3. APPLY REAL DATA
                    'Custom field (Time to first response)': parse_sla_to_hhmm(raw_dict.get(tfr_id)) if tfr_id else "", 
                    'Custom
