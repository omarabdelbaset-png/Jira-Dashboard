import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
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
        background-color: #f8f9fa; border: 1px solid #e9ecef;
        border-radius: 8px; padding: 16px;
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

# ==========================================
# --- HELPER FUNCTIONS ---
# ==========================================
def parse_hhmm(val):
    try:
        parts = str(val).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except: return np.nan

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
            if cycle.get('breached', False) and mins > 0: mins = -mins
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
    if not req_obj: return ""
    if isinstance(req_obj, str): 
        if '/' in req_obj: return req_obj.split('/')[-1].replace('-', ' ').title()
        return req_obj
    if isinstance(req_obj, dict):
        if 'requestType' in req_obj and isinstance(req_obj['requestType'], dict): 
            return req_obj['requestType'].get('name', "")
        return req_obj.get('name', req_obj.get('value', req_obj.get('currentValue', "")))
    if isinstance(req_obj, list) and len(req_obj) > 0: return parse_req(req_obj[0])
    return str(req_obj)

# ==========================================
# --- DATA FETCHER ---
# ==========================================
@st.cache_data(ttl=600)
def load_data():
    df_raw, is_live, error_msg = pd.DataFrame(), False, None
    if JIRA_EMAIL and JIRA_TOKEN:
        try:
            jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
            all_fields = jira.fields()
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
                'status', 'priority', 'assignee', 'created', 'resolutiondate', 
                'updated', 'issuetype', 'resolution', 'reporter', 'summary', 'customfield_10010'
            ]
            for cid in [tfr_id, ttr_id, sat_id, req_id]:
                if cid and cid not in fetch_fields: fetch_fields.append(cid)
            
            data = []
            issues = jira.enhanced_search_issues(
                'project = SVF ORDER BY created DESC', maxResults=False, fields=','.join(fetch_fields)
            )
            
            for issue in issues:
                raw = issue.raw['fields']
                status_str = str(issue.fields.status)
                
                if 'Done' in status_str or 'Resolved' in status_str: stat_cat = 'Done'
                elif 'Progress' in status_str: stat_cat = 'In Progress'
                else: stat_cat = 'To Do'
                    
                req_val = raw.get(req_id) if req_id else None
                if not req_val: req_val = raw.get('customfield_10010')
                extracted_req = parse_req(req_val)
                if not extracted_req or extracted_req.lower() == "unknown": 
                    extracted_req = str(issue.fields.issuetype) if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype else "Unknown"

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
                    'Request Type': extracted_req,
                    'Custom field ([CHART] Date of First Response)': pd.to_datetime(issue.fields.created).strftime("%d/%b/%y %I:%M %p") if issue.fields.created else None
                })
            df_raw, is_live = pd.DataFrame(data), True
        except Exception as e: error_msg = str(e)
            
    if not is_live:
        if os.path.exists(FILE_NAME): df_raw = pd.read_csv(FILE_NAME, low_memory=False)
        else: return pd.DataFrame(), False, "No Secrets and No CSV found."

    if not df_raw.empty:
        df = df_raw.copy()
        if "Custom field (Request Type).1" in df.columns and "Request Type" not in df.columns:
            df["Request Type"] = df["Custom field (Request Type).1"].fillna("Unknown")
            
        for col in ["Created", "Resolved", "Updated"]: 
            df[f"{col}_dt"] = pd.to_datetime(df[col], format="%d/%b/%y %I:%M %p", errors="coerce")
            
        df["YearMonth"] = df["Created_dt"].dt.to_period("M").astype(str)
        df["Week"] = df["Created_dt"].dt.to_period("W").astype(str)
        df["DayOfWeek"] = df["Created_dt"].dt.day_name()
        df["Hour"], df["Year"], df["Month"] = df["Created_dt"].dt.hour, df["Created_dt"].dt.year, df["Created_dt"].dt.month_name()
        df["TFR_remaining_min"] = df["Custom field (Time to first response)"].apply(parse_hhmm)
        df["TTR_remaining_min"] = df["Custom field (Time to resolution)"].apply(parse_hhmm)
        df["TFR_met"] = df["TFR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["TTR_met"] = df["TTR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["Satisfaction"] = pd.to_numeric(df["Satisfaction rating"], errors="coerce") if "Satisfaction rating" in df.columns else np.nan
        
        return df, is_live, error_msg
    return df_raw, is_live, error_msg

# ==========================================
# --- APP INIT ---
# ==========================================
with st.spinner("Connecting to Jira and loading dashboard..."):
    df_raw, is_live, error_msg = load_data()

if df_raw.empty:
    st.error(f"⚠️ Data could not be loaded. Error: {error_msg}")
    st.stop()

# ==========================================
# --- SIDEBAR FILTERS ---
# ==========================================
st.sidebar.title("🔍 Filters")
if is_live: 
    st.sidebar.success(f"🟢 Live Data Active\nLoaded {len(df_raw)} tickets.")
else: 
    st.sidebar.warning(f"🟡 Using Offline CSV Data\n{error_msg or ''}")

sel_status = st.sidebar.multiselect("Status", sorted(df_raw["Status"].dropna().unique()), default=sorted(df_raw["Status"].dropna().unique()))
sel_priority = st.sidebar.multiselect("Priority", sorted(df_raw["Priority"].dropna().unique()), default=sorted(df_raw["Priority"].dropna().unique()))
sel_type = st.sidebar.multiselect("Issue Type", sorted(df_raw["Issue Type"].dropna().unique()), default=sorted(df_raw["Issue Type"].dropna().unique()))
sel_assignee = st.sidebar.multiselect("Assignee", sorted(df_raw["Assignee"].dropna().unique()), default=sorted(df_raw["Assignee"].dropna().unique()))

if not df_raw["Created_dt"].isna().all():
    min_d, max_d = df_raw["Created_dt"].min().date(), df_raw["Created_dt"].max().date()
else:
    min_d, max_d = pd.Timestamp.now().date(), pd.Timestamp.now().date()
    
date_range = st.sidebar.date_input("Date Range", value=[min_d, max_d], min_value=min_d, max_value=max_d)
if len(date_range) == 1: date_range = (date_range[0], date_range[0])

df = df_raw[
    df_raw["Status"].isin(sel_status) & 
    df_raw["Priority"].isin(sel_priority) & 
    df_raw["Issue Type"].isin(sel_type) & 
    df_raw["Assignee"].isin(sel_assignee) & 
    (df_raw["Created_dt"].dt.date >= date_range[0]) & 
    (df_raw["Created_dt"].dt.date <= date_range[1])
]

# ==========================================
# --- DASHBOARD LAYOUT ---
# ==========================================
st.title("📊 Jira Service Desk Dashboard")
st.caption(f"Showing **{len(df):,}** tickets from {date_range[0]} to {date_range[1]}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Overview", "🎫 Ticket Analysis", "🚦 SLA Performance", "⭐ Satisfaction", "📅 Trends & Raw Data"])
PCOLOR = {"Critical": "#EF553B", "High": "#FFA15A", "Medium": "#636EFA", "Low": "#00CC96"}

# ------------------------------------------
# TAB 1: OVERVIEW
# ------------------------------------------
with tab1:
    st.subheader("Key Metrics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Tickets", f"{len(df):,}")
    c2.metric("Open", int((df["Status"] == "Open").sum()))
    c3.metric("In Progress", int((df["Status"].str.contains("Progress", na=False)).sum()))
    c4.metric("Resolved", int((df["Status"] == "Resolved").sum()))
    c5.metric("Closed", int((df["Status"] == "Closed").sum()))
    c6.metric("Canceled", int((df["Status"] == "Canceled").sum()))

    s1, s2, s3, s4 = st.columns(4)
    _ttr, _tfr, _sat = df[df["TTR_met"].notna()], df[df["TFR_met"].notna()], df[df["Satisfaction"].notna()]
    
    ttr_met_pct = 100 * (_ttr["TTR_met"] == "Met").mean() if len(_ttr) else 0
    tfr_met_pct = 100 * (_tfr["TFR_met"] == "Met").mean() if len(_tfr) else 0
    avg_sat = _sat["Satisfaction"].mean() if len(_sat) else 0
    
    s1.metric("Resolution SLA Met", f"{ttr_met_pct:.1f}%", delta=f"-{int((_ttr['TTR_met'] == 'Breached').sum()):,} breached", delta_color="inverse")
    s2.metric("First Response SLA Met", f"{tfr_met_pct:.1f}%", delta=f"-{int((_tfr['TFR_met'] == 'Breached').sum()):,} breached", delta_color="inverse")
    s3.metric("Avg Satisfaction", f"{avg_sat:.2f} / 5", delta=f"{len(_sat):,} ratings")
    s4.metric("5-Star Ratings", f"{int((_sat['Satisfaction'] == 5).sum()):,}", delta=f"{100*int((_sat['Satisfaction'] == 5).sum())/len(_sat):.1f}% of rated" if len(_sat) else "0%")

    st.divider()
    ov1, ov2, ov3, ov4 = st.columns(4)
    
    with ov1: 
        fig = go.Figure(go.Indicator(mode="gauge+number+delta", value=ttr_met_pct, title={"text": "Res SLA Met %"}, gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96"}, "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}}))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        
    with ov2: 
        fig = go.Figure(go.Indicator(mode="gauge+number+delta", value=tfr_met_pct, title={"text": "FR SLA Met %"}, gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96"}, "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}}))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        
    with ov3: 
        fig = go.Figure(go.Indicator(mode="gauge+number", value=avg_sat, title={"text": "Avg Score"}, gauge={"axis": {"range": [1, 5]}, "bar": {"color":
