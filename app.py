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

JIRA_SERVER = "https://itsupportsivision.atlassian.net"
FILE_NAME = "Jira Service Desk (8).csv"
PCOLOR = {"Critical": "#EF553B", "High": "#FFA15A", "Medium": "#636EFA", "Low": "#00CC96"}

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
    if not req_obj: return ""
    if isinstance(req_obj, str): 
        if '/' in req_obj: return req_obj.split('/')[-1].replace('-', ' ').title()
        return req_obj
    if isinstance(req_obj, dict):
        if 'requestType' in req_obj and isinstance(req_obj['requestType'], dict): return req_obj['requestType'].get('name', "")
        return req_obj.get('name', req_obj.get('value', req_obj.get('currentValue', "")))
    if isinstance(req_obj, list) and len(req_obj) > 0: return parse_req(req_obj[0])
    return str(req_obj)

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
                
            tfr_id, ttr_id, sat_id = get_id(['time to first response']), get_id(['time to resolution']), get_id(['satisfaction', 'satisfaction rating'])
            req_id = get_id(['customer request type', 'request type', 'portal request type'])

            fetch_fields = ['status', 'priority', 'assignee', 'created', 'resolutiondate', 'updated', 'issuetype', 'resolution', 'reporter', 'summary', 'customfield_10010']
            for cid in [tfr_id, ttr_id, sat_id, req_id]:
                if cid and cid not in fetch_fields: fetch_fields.append(cid)
            
            data = []
            for issue in jira.enhanced_search_issues('project = SVF ORDER BY created DESC', maxResults=False, fields=','.join(fetch_fields)):
                raw = issue.raw['fields']
                status_str = str(issue.fields.status)
                stat_cat = 'Done' if 'Done' in status_str or 'Resolved' in status_str else ('In Progress' if 'Progress' in status_str else 'To Do')
                    
                req_val = raw.get(req_id) if req_id else None
                if not req_val: req_val = raw.get('customfield_10010')
                extracted_req = parse_req(req_val)
                if not extracted_req or extracted_req.lower() == "unknown": extracted_req = str(issue.fields.issuetype) if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype else "Unknown"

                data.append({
                    'Issue key': issue.key, 'Summary': issue.fields.summary, 'Status': status_str, 'Status Category': stat_cat,
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
        if "Custom field (Request Type).1" in df.columns and "Request Type" not in df.columns: df["Request Type"] = df["Custom field (Request Type).1"].fillna("Unknown")
        for col in ["Created", "Resolved", "Updated"]: df[f"{col}_dt"] = pd.to_datetime(df[col], format="%d/%b/%y %I:%M %p", errors="coerce")
        df["YearMonth"] = df["Created_dt"].dt.to_period("M").astype(str)
        df["Week"] = df["Created_dt"].dt.to_period("W").astype(str)
        df["DayOfWeek"] = df["Created_dt"].dt.day_name()
        df["Hour"], df["Year"], df["Month"] = df["Created_dt"].dt.hour, df["Created_dt"].dt.year, df["Created_dt"].dt.month_name()
        df["TFR_remaining_min"] = df["Custom field (Time to first response)"].apply(parse_hhmm)
        df["TTR_remaining_min"] = df["Custom field (Time to resolution)"].apply(parse_hhmm)
        df["TFR_remaining_hrs"], df["TTR_remaining_hrs"] = df["TFR_remaining_min"] / 60, df["TTR_remaining_min"] / 60
        df["TFR_met"] = df["TFR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["TTR_met"] = df["TTR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["Satisfaction"] = pd.to_numeric(df["Satisfaction rating"], errors="coerce") if "Satisfaction rating" in df.columns else np.nan
        if df["Resolved_dt"].notna().any() and df["Created_dt"].notna().any(): df["Actual Resolution Hours"] = (df["Resolved_dt"] - df["Created_dt"]).dt.total_seconds() / 3600
        if "Custom field ([CHART] Date of First Response)" in df.columns: df["Actual TFR Hours"] = (pd.to_datetime(df["Custom field ([CHART] Date of First Response)"], errors="coerce") - df["Created_dt"]).dt.total_seconds() / 3600
        return df, is_live, error_msg
    return df_raw, is_live, error_msg

with st.spinner("Connecting to Jira and loading dashboard..."):
    df_raw, is_live, error_msg = load_data()

if df_raw.empty:
    st.error(f"⚠️ Data could not be loaded. Error: {error_msg}")
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
if len(date_range) == 1: date_range = (date_range[0], date_range[0])

df = df_raw[df_raw["Status"].isin(sel_status) & df_raw["Priority"].isin(sel_priority) & df_raw["Issue Type"].isin(sel_type) & df_raw["Assignee"].isin(sel_assignee) & (df_raw["Created_dt"].dt.date >= date_range[0]) & (df_raw["Created_dt"].dt.date <= date_range[1])]

st.title("📊 Jira Service Desk Dashboard")
st.caption(f"Showing **{len(df):,}** tickets from {date_range[0]} to {date_range[1]}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Overview", "🎫 Ticket Analysis", "🚦 SLA Performance", "⭐ Satisfaction", "📅 Trends & Raw Data"])

# === TAB 1: OVERVIEW ===
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
        st.plotly_chart(fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10)), use_container_width=True)
    with ov2: 
        fig = go.Figure(go.Indicator(mode="gauge+number+delta", value=tfr_met_pct, title={"text": "FR SLA Met %"}, gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96"}, "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}}))
        st.plotly_chart(fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10)), use_container_width=True)
    with ov3: 
        fig = go.Figure(go.Indicator(mode="gauge+number", value=avg_sat, title={"text": "Avg Score"}, gauge={"axis": {"range": [1, 5]}, "bar": {"color": "#636EFA"}}))
        st.plotly_chart(fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10)), use_container_width=True)
    with ov4:
        if len(_sat) > 0:
            sd = _sat["Satisfaction"].value_counts().sort_index().reset_index()
            sd.columns = ["Score", "Count"]
            sd["Label"] = sd["Score"].astype(int).astype(str) + " ⭐"
            fig = px.bar(sd, x="Label", y="Count", color="Score", color_continuous_scale=[[0, "#EF553B"], [0.5, "#FECB52"], [1.0, "#00CC96"]])
            st.plotly_chart(fig.update_layout(coloraxis_showscale=False, showlegend=False, margin=dict(l=0, r=0, t=30, b=0), height=220), use_container_width=True)

    st.divider()
    col1, col2 = st.columns(2)
    with col1: 
        sc = df["Status"].value_counts().reset_index()
        sc.columns = ["Status", "Count"]
        fig = px.bar(sc, x="Count", y="Status", orientation="h", color="Status", color_discrete_map={"Open": "#EF553B", "In Progress": "#FFA15A", "Resolved": "#00CC96", "Closed": "#636EFA", "Canceled": "#AB63FA"}, text="Count", title="Tickets by Status")
        st.plotly_chart(fig.update_traces(textposition="outside").update_layout(showlegend=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)
    with col2: 
        pc = df["Priority"].value_counts().reset_index()
        pc.columns = ["Priority", "Count"]
        fig = px.pie(pc, names="Priority", values="Count", hole=0.45, color="Priority", color_discrete_map=PCOLOR, title="Tickets by Priority")
        st.plotly_chart(fig.update_traces(textinfo="label+percent+value").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

    rc1, rc2 = st.columns(2)
    with rc1: 
        rc = df["Resolution"].fillna("Unresolved").value_counts().reset_index()
        rc.columns = ["Resolution", "Count"]
        fig = px.pie(rc, names="Resolution", values="Count", hole=0.45, title="Resolution Breakdown")
        st.plotly_chart(fig.update_traces(textinfo="label+percent+value").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with rc2:
        m_cr = df.groupby("YearMonth").size().reset_index(name="Tickets")
        m_res = df[df["Resolved_dt"].notna()].copy()
        m_res["RM"] = m_res["Resolved_dt"].dt.to_period("M").astype(str)
        comb = m_cr.merge(m_res.groupby("RM").size().reset_index(name="Resolved"), left_on="YearMonth", right_on="RM", how="left").fillna(0)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=comb["YearMonth"], y=comb["Tickets"], mode="lines+markers", name="Created", line=dict(color="#636EFA", width=2)))
        fig.add_trace(go.Scatter(x=comb["YearMonth"], y=comb["Resolved"], mode="lines+markers", name="Resolved", line=dict(color="#00CC96", width=2)))
        st.plotly_chart(fig.update_layout(title="Monthly Ticket Volume", xaxis_tickangle=-45, margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=1.1)), use_container_width=True)

# === TAB 2: TICKET ANALYSIS ===
with tab2:
    rt = df["Request Type"].value_counts().reset_index()
    rt.columns = ["Request Type", "Count"]
    fig = px.bar(rt.sort_values(by="Count", ascending=True).tail(20), x="Count", y="Request Type", orientation="h", color="Count", color_continuous_scale="Blues", text="Count", title="Request Type Distribution")
    st.plotly_chart(fig.update_traces(textposition="outside").update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1: 
        piv = df.groupby(["Priority", "Status"]).size().unstack(fill_value=0).reindex([p for p in ["Critical", "High", "Medium", "Low"] if p in df["Priority"].unique()])
        fig = px.imshow(piv, text_auto=True, color_continuous_scale="YlOrRd", aspect="auto", title="Priority × Status Heatmap")
        st.plotly_chart(fig.update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with c2: 
        fig = px.imshow(df.groupby(["Issue Type", "Priority"]).size().unstack(fill_value=0), text_auto=True, color_continuous_scale="Blues", aspect="auto", title="Issue Type × Priority")
        st.plotly_chart(fig.update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3: 
        dow = df["DayOfWeek"].value_counts().reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]).fillna(0).reset_index()
        dow.columns = ["DayOfWeek", "Count"]
        fig = px.bar(dow, x="DayOfWeek", y="Count", color="Count", color_continuous_scale="Purples", text="Count", title="Tickets by Day of Week")
        st.plotly_chart(fig.update_traces(textposition="outside").update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with c4: 
        hc = df["Hour"].value_counts().sort_index().reset_index()
        hc.columns = ["Hour", "Count"]
        fig = px.bar(hc, x="Hour", y="Count", color="Count", color_continuous_scale="Teal", text="Count", title="Tickets by Hour of Day")
        st.plotly_chart(fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

    if "Status Category" in df.columns:
        sc_time = df.groupby(["YearMonth", "Status Category"]).size().reset_index()
        sc_time.columns = ["YearMonth", "Status Category", "Count"]
        fig = px.area(sc_time, x="YearMonth", y="Count", color="Status Category", color_discrete_map={"Done": "#00CC96", "In Progress": "#FFA15A", "To Do": "#636EFA"}, title="Status Category Over Time")
        st.plotly_chart(fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

# === TAB 3: SLA PERFORMANCE ===
with tab3:
    tfr_all, ttr_all = df[df["TFR_met"].notna()], df[df["TTR_met"].notna()]
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("FR SLA Met", f"{100 * (tfr_all['TFR_met'] == 'Met').mean() if len(tfr_all) else 0:.1f}%")
    c2.metric("FR SLA Breached", f"{100 * (tfr_all['TFR_met'] == 'Breached').mean() if len(tfr_all) else 0:.1f}%", delta_color="inverse")
    c3.metric("Res SLA Met", f"{100 * (ttr_all['TTR_met'] == 'Met').mean() if len(ttr_all) else 0:.1f}%")
    c4.metric("Res SLA Breached", f"{100 * (ttr_all['TTR_met'] == 'Breached').mean() if len(ttr_all) else 0:.1f}%", delta_color="inverse")
    c5.metric("Avg Actual First Response", f"{df['Actual TFR Hours'].clip(lower=0).median():.1f} hrs median" if "Actual TFR Hours" in df.columns else "N/A")
    c6.metric("Avg Actual Resolution", f"{df['Actual Resolution Hours'].clip(lower=0).median():.1f} hrs median" if "Actual Resolution Hours" in df.columns else "N/A")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        fig = px.pie(tfr_all["TFR_met"].value_counts().reset_index(name="Count"), names="TFR_met", values="Count", hole=0.5, color="TFR_met", color_discrete_map={"Met": "#00CC96", "Breached": "#EF553B"}, title="First Response SLA — Met vs Breached")
        st.plotly_chart(fig.update_traces(textinfo="label+percent+value", pull=[0.05, 0]).update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    with col2:
        fig = px.pie(ttr_all["TTR_met"].value_counts().reset_index(name="Count"), names="TTR_met", values="Count", hole=0.5, color="TTR_met", color_discrete_map={"Met": "#00CC96", "Breached": "#EF553B"}, title="Resolution Time SLA — Met vs Breached")
        st.plotly_chart(fig.update_traces(textinfo="label+percent+value", pull=[0.05, 0]).update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        tfr_pivot = tfr_all.groupby(["Priority", "TFR_met"]).size().reset_index(name="Count").pivot(index="Priority", columns="TFR_met", values="Count").fillna(0).reset_index().set_index("Priority").reindex([p for p in ["Critical", "High", "Medium", "Low"] if p in tfr_all["Priority"].unique()]).reset_index()
        fig = go.Figure()
        if "Met" in tfr_pivot.columns: fig.add_trace(go.Bar(name="Met", x=tfr_pivot["Priority"], y=tfr_pivot.get("Met", []), marker_color="#00CC96", text=tfr_pivot.get("Met", []).astype(int), textposition="inside"))
        if "Breached" in tfr_pivot.columns: fig.add_trace(go.Bar(name="Breached", x=tfr_pivot["Priority"], y=tfr_pivot.get("Breached", []), marker_color="#EF553B", text=tfr_pivot.get("Breached", []).astype(int), textposition="inside"))
        st.plotly_chart(fig.update_layout(title="First Response SLA by Priority", barmode="stack", margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=1.1)), use_container_width=True)
    with col4:
        ttr_pivot = ttr_all.groupby(["Priority", "TTR_met"]).size().reset_index(name="Count").pivot(index="Priority", columns="TTR_met", values="Count").fillna(0).reset_index().set_index("Priority").reindex([p for p in ["Critical", "High", "Medium", "Low"] if p in ttr_all["Priority"].unique()]).reset_index()
        fig = go.Figure()
        if "Met" in ttr_pivot.columns: fig.add_trace(go.Bar(name="Met", x=ttr_pivot["Priority"], y=ttr_pivot.get("Met", []), marker_color="#00CC96", text=ttr_pivot.get("Met", []).astype(int), textposition="inside"))
        if "Breached" in ttr_pivot.columns: fig.add_trace(go.Bar(name="Breached", x=ttr_pivot["Priority"], y=ttr_pivot.get("Breached", []), marker_color="#EF553B", text=ttr_pivot.get("Breached", []).astype(int), textposition="inside"))
        st.plotly_chart(fig.update_layout(title="Resolution Time SLA by Priority", barmode="stack", margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=1.1)), use_container_width=True)

    col5, col6 = st.columns(2)
    with col5:
        tfr_trend = tfr_all.copy(); tfr_trend["Month"] = tfr_trend["Created_dt"].dt.to_period("M").astype(str)
        tfr_m = tfr_trend.groupby("Month")["TFR_met"].apply(lambda x: 100 * (x == "Met").sum() / len(x)).reset_index(name="Met %").merge(tfr_trend.groupby("Month").size().reset_index(name="Count"), on="Month")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=tfr_m["Month"], y=tfr_m["Count"], name="Ticket Count", marker_color="#c7e8c7", opacity=0.6), secondary_y=False)
        fig.add_trace(go.Scatter(x=tfr_m["Month"], y=tfr_m["Met %"], mode="lines+markers", name="Met %", line=dict(color="#00CC96", width=2)), secondary_y=True)
        fig.add_hline(y=80, line_dash="dash", line_color="orange", annotation_text="80% target", secondary_y=True)
        st.plotly_chart(fig.update_layout(title="First Response SLA % Met — Monthly", xaxis_tickangle=-45, margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=1.1)), use_container_width=True)
    with col6:
        ttr_trend = ttr_all.copy(); ttr_trend["Month"] = ttr_trend["Created_dt"].dt.to_period("M").astype(str)
        ttr_m = ttr_trend.groupby("Month")["TTR_met"].apply(lambda x: 100 * (x == "Met").sum() / len(x)).reset_index(name="Met %").merge(ttr_trend.groupby("Month").size().reset_index(name="Count"), on="Month")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=ttr_m["Month"], y=ttr_m["Count"], name="Ticket Count", marker_color="#f5c6c6", opacity=0.6), secondary_y=False)
        fig.add_trace(go.Scatter(x=ttr_m["Month"], y=ttr_m["Met %"], mode="lines+markers", name="Met %", line=dict(color="#636EFA", width=2)), secondary_y=True)
        fig.add_hline(y=80, line_dash="dash", line_color="orange", annotation_text="80% target", secondary_y=True)
        st.plotly_chart(fig.update_layout(title="Resolution Time SLA % Met — Monthly", xaxis_tickangle=-45, margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=1.1)), use_container_width=True)

    col7, col8 = st.columns(2)
    with col7:
        fig = px.bar(tfr_all[tfr_all["TFR_met"] == "Breached"].groupby("Assignee").size().sort_values(ascending=True).tail(15).reset_index(name="Breaches"), x="Breaches", y="Assignee", orientation="h", color="Breaches", color_continuous_scale="Reds", text="Breaches", title="First Response SLA Breaches (Assignee)")
        st.plotly_chart(fig.update_traces(textposition="outside").update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)
    with col8:
        fig = px.bar(ttr_all[ttr_all["TTR_met"] == "Breached"].groupby("Assignee").size().sort_values(ascending=True).tail(15).reset_index(name="Breaches"), x="Breaches", y="Assignee", orientation="h", color="Breaches", color_continuous_scale="Oranges", text="Breaches", title="Resolution SLA Breaches (Assignee)")
        st.plotly_chart(fig.update_traces(textposition="outside").update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)

    col9, col10 = st.columns(2)
    with col9:
        fig = px.bar(tfr_all[tfr_all["TFR_met"] == "Breached"].groupby("Request Type").size().sort_values(ascending=True).tail(15).reset_index(name="Breaches"), x="Breaches", y="Request Type", orientation="h", color="Breaches", color_continuous_scale="Reds", text="Breaches", title="First Response Breaches by Request Type")
        st.plotly_chart(fig.update_traces(textposition="outside").update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)
    with col10:
        fig = px.bar(ttr_all[ttr_all["TTR_met"] == "Breached"].groupby("Request Type").size().sort_values(ascending=True).tail(15).reset_index(name="Breaches"), x="Breaches", y="Request Type", orientation="h", color="Breaches", color_continuous_scale="Oranges", text="Breaches", title="Resolution Breaches by Request Type")
        st.plotly_chart(fig.update_traces(textposition="outside").update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=30, b=0)), use_container_width=True)

    if "Actual Resolution Hours" in df.columns:
        res_actual = df[df["Actual Resolution Hours"].notna() & (df["Actual Resolution Hours"] > 0)]
        if len(res_actual) > 0:
            res_capped = res_actual[res_actual["Actual Resolution Hours"] <= res_actual["Actual Resolution Hours"].quantile(0.95)]
            col11, col12 = st.columns(2)
            with col11: st.plotly_chart(px.histogram(res_capped, x="Actual Resolution Hours", nbins=50, color_discrete_sequence=["#636EFA"], title="Actual Resolution Time Distribution (hrs)").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
            with col12: st.plotly_chart(px.box(res_capped[res_capped["Priority"].notna()], x="Priority", y="Actual Resolution Hours", color="Priority", color_discrete_map=PCOLOR, title="Resolution Time by Priority").update_layout(showlegend=False, margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)

    with st.expander("🔎 View Breached Tickets"):
        b_df = tfr_all[tfr_all["TFR_met"] == "Breached"] if st.radio("Show breaches for", ["First Response SLA", "Resolution Time SLA"], horizontal=True) == "First Response SLA" else ttr_all[ttr_all["TTR_met"] == "Breached"]
        st.dataframe(b_df[["Issue key", "Summary", "Status", "Priority", "Assignee", "Created"]].sort_values("Created", ascending=False), use_container_width=True, hide_index=True)

# === TAB 4: SATISFACTION ===
with tab4:
    if len(_sat) > 0:
        c1, c2 = st.columns(2)
        with c1: 
            sd2 = _sat["Satisfaction"].value_counts().sort_index().reset_index()
            sd2.columns = ["Satisfaction", "Count"]
            st.plotly_chart(px.bar(sd2, x="Satisfaction", y="Count", text="Count", title="Score Distribution").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
        with c2: 
            sp = _sat.groupby("Priority")["Satisfaction"].mean().reset_index()
            sp.columns = ["Priority", "Avg"]
            st.plotly_chart(px.bar(sp, x="Priority", y="Avg", color="Priority", color_discrete_map=PCOLOR, text=np.round(sp["Avg"], 2), title="CSAT by Priority").update_traces(textposition="outside").update_layout(margin=dict(l=0, r=0, t=30, b=0)), use_container_width=True)
    else: st.info("No satisfaction ratings available.")

# === TAB 5: TRENDS & RAW DATA ===
with tab5:
    st.subheader("📋 Raw Data Explorer")
    search = st.text_input("Search in Summary", "")
    disp = df[df["Summary"].fillna("").str.contains(search, case=False)] if search else df
    cols = st.multiselect("Columns", ["Issue key", "Summary", "Status", "Priority", "Assignee", "Created", "Resolution", "TTR_met", "TFR_met", "Satisfaction", "Request Type"], default=["Issue key", "Summary", "Status", "Priority", "Assignee", "Created", "Request Type"])
    st.dataframe(disp[cols].sort_values("Created", ascending=False).head(1000), use_container_width=True, hide_index=True)
