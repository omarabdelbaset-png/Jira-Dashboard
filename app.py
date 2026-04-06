import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from jira import JIRA

st.set_page_config(page_title="Jira Service Desk Dashboard", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
st.markdown('<style>.stMetric { background-color: #f8f9fa; border-radius: 8px; padding: 12px; } div[data-testid="metric-container"] { background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 16px; }</style>', unsafe_allow_html=True)

# ==========================================
# --- CONFIGURATION & SECRETS ---
# ==========================================
JIRA_SERVER = "https://itsupportsivision.atlassian.net"
FILE_NAME = "Jira Service Desk (8).csv"

try:
    JIRA_EMAIL, JIRA_TOKEN = st.secrets["JIRA_EMAIL"], st.secrets["JIRA_API_TOKEN"]
except:
    JIRA_EMAIL, JIRA_TOKEN = None, None

def parse_hhmm(val):
    try:
        parts = str(val).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except: return np.nan

def parse_sla_to_hhmm(sla_obj):
    if not sla_obj: return ""
    if isinstance(sla_obj, str) and ":" in sla_obj: return sla_obj
    try:
        cycle = sla_obj.get('completedCycles', [{}])[-1] if isinstance(sla_obj, dict) and 'completedCycles' in sla_obj and sla_obj['completedCycles'] else sla_obj.get('ongoingCycle', {})
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
    if not req_obj: return "Unknown"
    return req_obj.get('requestType', {}).get('name', req_obj.get('name', 'Unknown')) if isinstance(req_obj, dict) else str(req_obj)

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
            def get_id(names): return next((f['id'] for f in all_fields if f['name'].lower() in names), None)
                
            tfr_id = get_id(['time to first response'])
            ttr_id = get_id(['time to resolution'])
            sat_id = get_id(['satisfaction', 'satisfaction rating'])
            req_id = get_id(['request type'])

            fetch_fields = ['status', 'priority', 'assignee', 'created', 'resolutiondate', 'updated', 'issuetype', 'resolution', 'reporter', 'summary'] + [cid for cid in [tfr_id, ttr_id, sat_id, req_id] if cid]
            
            data = []
            for issue in jira.enhanced_search_issues('project = SVF ORDER BY created DESC', maxResults=False, fields=','.join(fetch_fields)):
                raw = issue.raw['fields']
                data.append({
                    'Issue key': issue.key, 'Summary': issue.fields.summary, 'Status': str(issue.fields.status),
                    'Status Category': 'Done' if 'Done' in str(issue.fields.status) or 'Resolved' in str(issue.fields.status) else ('In Progress' if 'Progress' in str(issue.fields.status) else 'To Do'),
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
                    'Custom field (Request Type).1': parse_req(raw.get(req_id)) if req_id else str(issue.fields.issuetype),
                    'Custom field ([CHART] Date of First Response)': pd.to_datetime(issue.fields.created).strftime("%d/%b/%y %I:%M %p") if issue.fields.created else None
                })
            df_raw, is_live = pd.DataFrame(data), True
        except Exception as e: error_msg = str(e)
            
    if not is_live:
        if os.path.exists(FILE_NAME): df_raw = pd.read_csv(FILE_NAME, low_memory=False)
        else: return pd.DataFrame(), False, "No Secrets and No CSV found."

    if not df_raw.empty:
        df = df_raw.copy()
        for col in ["Created", "Resolved", "Updated"]: df[f"{col}_dt"] = pd.to_datetime(df[col], format="%d/%b/%y %I:%M %p", errors="coerce")
        df["YearMonth"] = df["Created_dt"].dt.to_period("M").astype(str)
        df["Week"] = df["Created_dt"].dt.to_period("W").astype(str)
        df["DayOfWeek"] = df["Created_dt"].dt.day_name()
        df["Hour"], df["Year"], df["Month"] = df["Created_dt"].dt.hour, df["Created_dt"].dt.year, df["Created_dt"].dt.month_name()
        
        df["TFR_remaining_min"], df["TTR_remaining_min"] = df["Custom field (Time to first response)"].apply(parse_hhmm), df["Custom field (Time to resolution)"].apply(parse_hhmm)
        df["TFR_remaining_hrs"], df["TTR_remaining_hrs"] = df["TFR_remaining_min"] / 60, df["TTR_remaining_min"] / 60
        df["Time to First Response (min)"], df["Time to Resolution (min)"] = df["TFR_remaining_min"], df["TTR_remaining_min"]
        df["Resolution Hours"], df["FirstResponse Hours"] = df["TTR_remaining_hrs"], df["TFR_remaining_hrs"]

        df["TFR_met"] = df["TFR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["TTR_met"] = df["TTR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))

        if df["Resolved_dt"].notna().any() and df["Created_dt"].notna().any(): df["Actual Resolution Hours"] = (df["Resolved_dt"] - df["Created_dt"]).dt.total_seconds() / 3600
        if "Custom field ([CHART] Date of First Response)" in df.columns: df["Actual TFR Hours"] = (pd.to_datetime(df["Custom field ([CHART] Date of First Response)"], errors="coerce") - df["Created_dt"]).dt.total_seconds() / 3600
        df["Request Type"] = df["Custom field (Request Type).1"].fillna("Unknown") if "Custom field (Request Type).1" in df.columns else "Unknown"
        df["Satisfaction"] = pd.to_numeric(df["Satisfaction rating"], errors="coerce") if "Satisfaction rating" in df.columns else np.nan
        return df, is_live, error_msg
    return df_raw, is_live, error_msg

# ==========================================
# --- LOAD DATA & UI INIT ---
# ==========================================
with st.spinner("Connecting to Jira and extracting true SLAs..."):
    df_raw, is_live, error_msg = load_data()

if df_raw.empty:
    st.error(f"⚠️ Data could not be loaded. Error: {error_msg}")
    if st.file_uploader("Upload Jira CSV", type="csv", key="up") is not None:
        with open(FILE_NAME, "wb") as f: f.write(st.session_state.up.read())
        st.rerun()
    st.stop()

st.sidebar.title("🔍 Filters")
if is_live: st.sidebar.success(f"🟢 Live Data Active\nLoaded {len(df_raw)} tickets.")
else: st.sidebar.warning(f"🟡 Using Offline CSV Data\n{error_msg or ''}")

sel_status = st.sidebar.multiselect("Status", sorted(df_raw["Status"].dropna().unique()), default=sorted(df_raw["Status"].dropna().unique()))
sel_priority = st.sidebar.multiselect("Priority", sorted(df_raw["Priority"].dropna().unique()), default=sorted(df_raw["Priority"].dropna().unique()))
sel_type = st.sidebar.multiselect("Issue Type", sorted(df_raw["Issue Type"].dropna().unique()), default=sorted(df_raw["Issue Type"].dropna().unique()))
sel_assignee = st.sidebar.multiselect("Assignee", sorted(df_raw["Assignee"].dropna().unique()), default=sorted(df_raw["Assignee"].dropna().unique()))
min_d, max_d = (df_raw["Created_dt"].min().date(), df_raw["Created_dt"].max().date()) if not df_raw["Created_dt"].isna().all() else (pd.Timestamp.now().date(), pd.Timestamp.now().date())
date_range = st.sidebar.date_input("Date Range", value=[min_d, max_d], min_value=min_d, max_value=max_d)

df = df_raw[df_raw["Status"].isin(sel_status) & df_raw["Priority"].isin(sel_priority) & df_raw["Issue Type"].isin(sel_type) & df_raw["Assignee"].isin(sel_assignee) & (df_raw["Created_dt"].dt.date >= date_range[0]) & (df_raw["Created_dt"].dt.date <= (date_range[1] if len(date_range) > 1 else date_range[0]))]

st.title("📊 Jira Service Desk Dashboard")
st.caption(f"Showing **{len(df):,}** tickets from {date_range[0]} to {date_range[1] if len(date_range) > 1 else date_range[0]}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Overview", "🎫 Ticket Analysis", "🚦 SLA Performance", "⭐ Satisfaction", "📅 Trends & Raw Data"])
PCOLOR = {"Critical": "#EF553B", "High": "#FFA15A", "Medium": "#636EFA", "Low": "#00CC96"}

with tab1:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Tickets", f"{len(df):,}")
    c2.metric("Open", int((df["Status"] == "Open").sum()))
    c3.metric("In Progress", int((df["Status"].str.contains("Progress", na=False)).sum()))
    c4.metric("Resolved", int((df["Status"] == "Resolved").sum()))
    c5.metric("Closed", int((df["Status"] == "Closed").sum()))
    c6.metric("Canceled", int((df["Status"] == "Canceled").sum()))

    s1, s2, s3, s4 = st.columns(4)
    _ttr, _tfr, _sat = df[df["TTR_met"].notna()], df[df["TFR_met"].notna()], df[df["Satisfaction"].notna()]
    s1.metric("Resolution SLA Met", f"{100 * (_ttr['TTR_met'] == 'Met').mean() if len(_ttr) else 0:.1f}%", delta=f"-{int((_ttr['TTR_met'] == 'Breached').sum()):,} breached", delta_color="inverse")
    s2.metric("First Response SLA Met", f"{100 * (_tfr['TFR_met'] == 'Met').mean() if len(_tfr) else 0:.1f}%", delta=f"-{int((_tfr['TFR_met'] == 'Breached').sum()):,} breached", delta_color="inverse")
    s3.metric("Avg Satisfaction", f"{_sat['Satisfaction'].mean() if len(_sat) else 0:.2f} / 5", delta=f"{len(_sat):,} ratings")
    s4.metric("5-Star Ratings", f"{int((_sat['Satisfaction'] == 5).sum()):,}", delta=f"{100*int((_sat['Satisfaction'] == 5).sum())/len(_sat):.1f}% of rated" if len(_sat) else "0%")

    st.divider()
    ov1, ov2, ov3, ov4 = st.columns(4)
    with ov1: st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number+delta", value=100 * (_ttr['TTR_met'] == 'Met').mean() if len(_ttr) else 0, title={"text": "Res SLA Met %"}, gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96"}, "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}})).update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10)), use_container_width=True)
    with ov2: st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number+delta", value=100 * (_tfr['TFR_met'] == 'Met').mean() if len(_tfr) else 0, title={"text": "FR SLA Met %"}, gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96"}, "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}})).update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10)), use_container_width=True)
    with ov3: st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number", value=_sat['Satisfaction'].mean() if len(_sat) else 0, title={"text": "Avg CSAT"}, gauge={"axis": {"range": [1, 5]}, "bar": {"color": "#636EFA"}})).update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10)), use_container_width=True)
    with ov4:
        if len(_sat) > 0:
            sd = _sat["Satisfaction"].value_counts().reset_index(); sd.columns = ["Score", "Count"]; sd["Label"] = sd["Score"].astype(int).astype(str) + " ⭐"
            st.plotly_chart(px.bar(sd, x="Label", y="Count", color="Score").update_layout(showlegend=False, margin=dict(l=0, r=0, t=30, b=0), height=220), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1: st.plotly_chart(px.bar(df["Status"].value_counts().reset_index(name="Count"), x="Count", y="Status", orientation="h", color="Status", text="Count", title="Tickets by Status").update_traces(textposition="outside").update_layout(showlegend=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)
    with c2: st.plotly_chart(px.pie(df["Priority"].value_counts().reset_index(name="Count"), names="Priority", values="Count", hole=0.45, color="Priority", color_discrete_map=PCOLOR, title="Tickets by Priority").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

with tab2:
    st.plotly_chart(px.bar(df["Request Type"].value_counts().reset_index(name="Count").head(20), x="Count", y="Request Type", orientation="h", color="Count", text="Count", title="Request Type Distribution").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)
    c1, c2 = st.columns(2)
    with c1: st.plotly_chart(px.imshow(df.groupby(["Priority", "Status"]).size().unstack(fill_value=0).reindex([p for p in ["Critical", "High", "Medium", "Low"] if p in df["Priority"].unique()]), text_auto=True, aspect="auto", title="Priority × Status Heatmap").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with c2: st.plotly_chart(px.imshow(df.groupby(["Issue Type", "Priority"]).size().unstack(fill_value=0), text_auto=True, color_continuous_scale="Blues", aspect="auto", title="Issue Type × Priority").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    c3, c4 = st.columns(2)
    with c3: st.plotly_chart(px.bar(df["DayOfWeek"].value_counts().reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]).fillna(0).reset_index(name="Count"), x="DayOfWeek", y="Count", text="Count", title="Tickets by Day").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with c4: st.plotly_chart(px.bar(df["Hour"].value_counts().sort_index().reset_index(name="Count"), x="Hour", y="Count", text="Count", title="Tickets by Hour").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

with tab3:
    tfr_all, ttr_all = df[df["TFR_met"].notna()], df[df["TTR_met"].notna()]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FR SLA Met", f"{100 * (tfr_all['TFR_met'] == 'Met').mean() if len(tfr_all) else 0:.1f}%")
    c2.metric("FR SLA Breached", f"{100 * (tfr_all['TFR_met'] == 'Breached').mean() if len(tfr_all) else 0:.1f}%")
    c3.metric("Res SLA Met", f"{100 * (ttr_all['TTR_met'] == 'Met').mean() if len(ttr_all) else 0:.1f}%")
    c4.metric("Res SLA Breached", f"{100 * (ttr_all['TTR_met'] == 'Breached').mean() if len(ttr_all) else 0:.1f}%")
    
    c5, c6 = st.columns(2)
    with c5: st.plotly_chart(px.pie(tfr_all["TFR_met"].value_counts().reset_index(name="Count"), names="TFR_met", values="Count", hole=0.5, color="TFR_met", color_discrete_map={"Met": "#00CC96", "Breached": "#EF553B"}, title="First Response SLA").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with c6: st.plotly_chart(px.pie(ttr_all["TTR_met"].value_counts().reset_index(name="Count"), names="TTR_met", values="Count", hole=0.5, color="TTR_met", color_discrete_map={"Met": "#00CC96", "Breached": "#EF553B"}, title="Resolution SLA").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

    with st.expander("🔎 View Breached Tickets"):
        breach_type = st.radio("Show breaches for", ["First Response SLA", "Resolution Time SLA"], horizontal=True)
        b_df = tfr_all[tfr_all["TFR_met"] == "Breached"] if breach_type == "First Response SLA" else ttr_all[ttr_all["TTR_met"] == "Breached"]
        st.dataframe(b_df[["Issue key", "Summary", "Status", "Priority", "Assignee", "Created"]].sort_values("Created", ascending=False), use_container_width=True, hide_index=True)

with tab4:
    if len(_sat) > 0:
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.bar(_sat["Satisfaction"].value_counts().sort_index().reset_index(name="Count"), x="Satisfaction", y="Count", text="Count", title="Score Distribution").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
        with c2: st.plotly_chart(px.bar(_sat.groupby("Priority")["Satisfaction"].mean().reset_index(name="Avg"), x="Priority", y="Avg", color="Priority", color_discrete_map=PCOLOR, text=np.round(_sat.groupby("Priority")["Satisfaction"].mean(), 2), title="CSAT by Priority").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
        st.plotly_chart(px.bar(_sat.groupby("Assignee")["Satisfaction"].agg(["mean", "count"]).reset_index().query("count>=3").sort_values("mean").tail(15), x="mean", y="Assignee", orientation="h", text=np.round(_sat.groupby("Assignee")["Satisfaction"].agg(["mean", "count"]).reset_index().query("count>=3").sort_values("mean").tail(15)["mean"], 2), title="Top Assignees by CSAT (min 3 ratings)").update_layout(margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)
    else: st.info("No satisfaction ratings available.")

with tab5:
    c1, c2 = st.columns(2)
    with c1: st.plotly_chart(px.area(df.groupby("Week").size().reset_index(name="Tickets"), x="Week", y="Tickets", title="Weekly Volume").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with c2: st.plotly_chart(px.bar(df.groupby("Year").size().reset_index(name="Tickets"), x="Year", y="Tickets", text="Tickets", title="Yearly Volume").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    
    st.subheader("📋 Raw Data Explorer")
    search = st.text_input("Search in Summary", "")
    disp = df[df["Summary"].fillna("").str.contains(search, case=False)] if search else df
    cols = st.multiselect("Columns", ["Issue key", "Summary", "Status", "Priority", "Assignee", "Created", "Resolution", "TTR_met", "TFR_met", "Satisfaction"], default=["Issue key", "Summary", "Status", "Priority", "Assignee", "Created"])
    st.dataframe(disp[cols].sort_values("Created", ascending=False).head(1000), use_container_width=True, hide_index=True)
