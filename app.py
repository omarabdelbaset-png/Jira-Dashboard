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
except:
    JIRA_EMAIL, JIRA_TOKEN = None, None

def parse_hhmm(val):
    try:
        parts = str(val).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except: 
        return np.nan

def parse_sla_to_hhmm(sla_obj):
    if not sla_obj: return ""
    if isinstance(sla_obj, str) and ":" in sla_obj: return sla_obj
    try:
        if isinstance(sla_obj, dict) and 'completedCycles' in sla_obj and sla_obj['completedCycles']:
            cycle = sla_obj['completedCycles'][-1]
        else:
            cycle = sla_obj.get('ongoingCycle', {})
            
        if cycle:
            mins = cycle.get('remainingTime', {}).get('millis', 0) / 60000.0
            if cycle.get('breached', False) and mins > 0: 
                mins = -mins
            res = f"{abs(int(mins)) // 60:02d}:{abs(int(mins)) % 60:02d}"
            return f"-{res}" if mins < 0 else res
    except: pass
    return ""

def parse_sat(sat_obj):
    if not sat_obj: return None
    if isinstance(sat_obj, dict): return sat_obj.get('rating', None)
    try: return float(sat_obj)
    except: return None
    
def parse_req(req_obj):
    # Aggressive unpacking for Jira Service Management Request Types
    if not req_obj: return ""
    
    if isinstance(req_obj, str): 
        # Clean up internal JSM strings (e.g. "svf/power-strip" -> "Power Strip")
        if '/' in req_obj: 
            return req_obj.split('/')[-1].replace('-', ' ').title()
        return req_obj
        
    if isinstance(req_obj, dict):
        if 'requestType' in req_obj and isinstance(req_obj['requestType'], dict):
            return req_obj['requestType'].get('name', "")
        return req_obj.get('name', req_obj.get('value', req_obj.get('currentValue', "")))
        
    if isinstance(req_obj, list) and len(req_obj) > 0:
        return parse_req(req_obj[0])
        
    return str(req_obj)

# ==========================================
# --- DATA FETCHER (LIVE OR CSV) ---
# ==========================================
@st.cache_data(ttl=600)
def load_data():
    df_raw, is_live, error_msg = pd.DataFrame(), False, None
    if JIRA_EMAIL and JIRA_TOKEN:
        try:
            jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
            all_fields = jira.fields()
            
            # Robust Field Finder (Exact match first, then partial match)
            def get_id(names): 
                for f in all_fields:
                    if f['name'].lower() in names: return f['id']
                for f in all_fields:
                    for n in names:
                        if n in f['name'].lower(): return f['id']
                return None
                
            tfr_id = get_id(['time to first response'])
            ttr_id = get_id(['time to resolution'])
            sat_id = get_id(['satisfaction', 'satisfaction rating'])
            req_id = get_id(['customer request type', 'request type', 'portal request type'])

            fetch_fields = [
                'status', 'priority', 'assignee', 'created', 
                'resolutiondate', 'updated', 'issuetype', 
                'resolution', 'reporter', 'summary', 
                'customfield_10010' # Universal JSM Request Type fallback field
            ]
            
            for cid in [tfr_id, ttr_id, sat_id, req_id]:
                if cid and cid not in fetch_fields: 
                    fetch_fields.append(cid)
            
            data = []
            issues = jira.enhanced_search_issues(
                'project = SVF ORDER BY created DESC', 
                maxResults=False, 
                fields=','.join(fetch_fields)
            )
            
            for issue in issues:
                raw = issue.raw['fields']
                status_str = str(issue.fields.status)
                
                if 'Done' in status_str or 'Resolved' in status_str: stat_cat = 'Done'
                elif 'Progress' in status_str: stat_cat = 'In Progress'
                else: stat_cat = 'To Do'
                    
                # 1. Try to get Request Type via discovered ID
                req_val = raw.get(req_id) if req_id else None
                # 2. If it fails, fallback to standard JSM field 10010
                if not req_val: req_val = raw.get('customfield_10010')
                
                extracted_req = parse_req(req_val)
                # 3. If STILL missing, fallback to generic Issue Type
                if not extracted_req or extracted_req.lower() == "unknown":
                    if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype:
                        extracted_req = str(issue.fields.issuetype)
                    else:
                        extracted_req = "Unknown"

                data.append({
                    'Issue key': issue.key, 
                    'Summary': issue.fields.summary, 
                    'Status': status_str,
                    'Status Category': stat_cat,
                    'Priority': str(issue.fields.priority) if hasattr(issue.fields, 'priority') and issue.fields.priority else 'None',
                    'Assignee': str(issue.fields.assignee) if hasattr(issue.fields, 'assignee') and issue.fields.assignee else 'Unassigned',
                    'Reporter': str(issue.fields.reporter) if hasattr(issue.fields, 'reporter') and issue.fields.reporter else 'Unknown',
                    'Issue Type': str(issue.fields.issuetype) if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype else 'Unknown',
                    'Resolution': str(issue.fields.resolution) if hasattr(issue.fields, 'resolution') and issue.fields.resolution else 'Unresolved',
                    'Created': pd.to_datetime(issue.fields.created).strftime("%d/%b/%y %I:%M %p") if issue.fields.created else None,
                    'Resolved': pd.to_datetime(issue.fields.resolutiondate).strftime("%d/%b/%y %I:%M %p") if hasattr(issue.fields, 'resolutiondate') and issue.fields.resolutiondate else None,
                    'Updated': pd.to_datetime(issue.fields.updated).strftime("%d/%b/%y %I:%M %p") if hasattr(issue.fields, 'updated') and issue.fields.updated else None,
                    'Custom field (Time to first response)': parse_sla_to_hhmm(raw.get(tfr_id)) if tfr_id else "", 
                    'Custom field (Time to resolution)': parse_sla_to_hhmm(raw.get(ttr_id)) if ttr_id else "",
                    'Satisfaction rating': parse_sat(raw.get(sat_id)) if sat_id else None,
                    'Custom field (Request Type).1': extracted_req,
                    'Custom field ([CHART] Date of First Response)': pd.to_datetime(issue.fields.created).strftime("%d/%b/%y %I:%M %p") if issue.fields.created else None
                })
            df_raw, is_live = pd.DataFrame(data), True
        except Exception as e: 
            error_msg = str(e)
            
    if not is_live:
        if os.path.exists(FILE_NAME): 
            df_raw = pd.read_csv(FILE_NAME, low_memory=False)
        else: 
            return pd.DataFrame(), False, "No Secrets and No CSV found."

    if not df_raw.empty:
        df = df_raw.copy()
        for col in ["Created", "Resolved", "Updated"]: 
            df[f"{col}_dt"] = pd.to_datetime(df[col], format="%d/%b/%y %I:%M %p", errors="coerce")
            
        df["YearMonth"] = df["Created_dt"].dt.to_period("M").astype(str)
        df["Week"] = df["Created_dt"].dt.to_period("W").astype(str)
        df["DayOfWeek"] = df["Created_dt"].dt.day_name()
        df["Hour"] = df["Created_dt"].dt.hour
        df["Year"] = df["Created_dt"].dt.year
        df["Month"] = df["Created_dt"].dt.month_name()
        
        df["TFR_remaining_min"] = df["Custom field (Time to first response)"].apply(parse_hhmm)
        df["TTR_remaining_min"] = df["Custom field (Time to resolution)"].apply(parse_hhmm)
        
        df["TFR_remaining_hrs"] = df["TFR_remaining_min"] / 60
        df["TTR_remaining_hrs"] = df["TTR_remaining_min"] / 60

        df["TFR_met"] = df["TFR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["TTR_met"] = df["TTR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))

        df["Satisfaction"] = pd.to_numeric(df["Satisfaction rating"], errors="coerce") if "Satisfaction rating" in df.columns else np.nan
        df["Request Type"] = df["Custom field (Request Type).1"].fillna("Unknown") if "Custom field (Request Type).1" in df.columns else "Unknown"
        return df, is_live, error_msg
        
    return df_raw, is_live, error_msg

# ==========================================
# --- APP INIT ---
# ==========================================
with st.spinner("Connecting to Jira and loading dashboard..."):
    df_raw, is_live, error_msg = load_data()

if df_raw.empty:
    st.error(f"⚠️ Data could not be loaded. Error: {error_msg}")
    st.
