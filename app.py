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
    except: 
        pass
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
    df_raw, is_live, error_msg = pd.DataFrame(), False, None
    if JIRA_EMAIL and JIRA_TOKEN:
        try:
            jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))
            all_fields = jira.fields()
            
            def get_id(names): 
                for f in all_fields:
                    if f['name'].lower() in names: return f['id']
                return None
                
            tfr_id = get_id(['time to first response'])
            ttr_id = get_id(['time to resolution'])
            sat_id = get_id(['satisfaction', 'satisfaction rating'])
            req_id = get_id(['request type'])

            fetch_fields = [
                'status', 'priority', 'assignee', 'created', 
                'resolutiondate', 'updated', 'issuetype', 
                'resolution', 'reporter', 'summary'
            ]
            for cid in [tfr_id, ttr_id, sat_id, req_id]:
                if cid: fetch_fields.append(cid)
            
            data = []
            issues = jira.enhanced_search_issues(
                'project = SVF ORDER BY created DESC', 
                maxResults=False, 
                fields=','.join(fetch_fields)
            )
            
            for issue in issues:
                raw = issue.raw['fields']
                status_str = str(issue.fields.status)
                
                # Status Category Logic
                if 'Done' in status_str or 'Resolved' in status_str:
                    stat_cat = 'Done'
                elif 'Progress' in status_str:
                    stat_cat = 'In Progress'
                else:
                    stat_cat = 'To Do'

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
                    'Custom field (Request Type).1': parse_req(raw.get(req_id)) if req_id else str(issue.fields.issuetype),
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
    st.stop()

# ==========================================
# --- SIDEBAR FILTERS ---
# ==========================================
st.sidebar.title("🔍 Filters")
if is_live: 
    st.sidebar.success(f"🟢 Live Data Active\nLoaded {len(df_raw)} tickets.")
else: 
    st.sidebar.warning(f"🟡 Using Offline CSV Data\n{error_msg or ''}")

sel_status = st.sidebar.multiselect(
    "Status", 
    sorted(df_raw["Status"].dropna().unique()), 
    default=sorted(df_raw["Status"].dropna().unique())
)
sel_priority = st.sidebar.multiselect(
    "Priority", 
    sorted(df_raw["Priority"].dropna().unique()), 
    default=sorted(df_raw["Priority"].dropna().unique())
)
sel_type = st.sidebar.multiselect(
    "Issue Type", 
    sorted(df_raw["Issue Type"].dropna().unique()), 
    default=sorted(df_raw["Issue Type"].dropna().unique())
)
sel_assignee = st.sidebar.multiselect(
    "Assignee", 
    sorted(df_raw["Assignee"].dropna().unique()), 
    default=sorted(df_raw["Assignee"].dropna().unique())
)

if not df_raw["Created_dt"].isna().all():
    min_d = df_raw["Created_dt"].min().date()
    max_d = df_raw["Created_dt"].max().date()
else:
    min_d = pd.Timestamp.now().date()
    max_d = pd.Timestamp.now().date()
    
date_range = st.sidebar.date_input("Date Range", value=[min_d, max_d], min_value=min_d, max_value=max_d)
if len(date_range) == 1:
    date_range = (date_range[0], date_range[0])

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

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Overview", 
    "🎫 Ticket Analysis", 
    "🚦 SLA Performance", 
    "⭐ Satisfaction", 
    "📅 Trends & Raw Data"
])

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
    _ttr = df[df["TTR_met"].notna()]
    _ttr_met_pct = 100 * (_ttr["TTR_met"] == "Met").mean() if len(_ttr) else 0
    _ttr_breached = int((_ttr["TTR_met"] == "Breached").sum())
    
    _tfr = df[df["TFR_met"].notna()]
    _tfr_met_pct = 100 * (_tfr["TFR_met"] == "Met").mean() if len(_tfr) else 0
    _tfr_breached = int((_tfr["TFR_met"] == "Breached").sum())
    
    _sat = df[df["Satisfaction"].notna()]
    _avg_sat = _sat["Satisfaction"].mean() if len(_sat) else 0
    _sat_5 = int((_sat["Satisfaction"] == 5).sum()) if len(_sat) else 0

    s1.metric("Resolution SLA Met", f"{_ttr_met_pct:.1f}%", delta=f"-{_ttr_breached:,} breached", delta_color="inverse")
    s2.metric("First Response SLA Met", f"{_tfr_met_pct:.1f}%", delta=f"-{_tfr_breached:,} breached", delta_color="inverse")
    s3.metric("Avg Satisfaction", f"{_avg_sat:.2f} / 5", delta=f"{len(_sat):,} ratings")
    
    pct_5_star = f"{100*_sat_5/len(_sat):.1f}% of rated" if len(_sat) else "0%"
    s4.metric("5-Star Ratings", f"{_sat_5:,}", delta=pct_5_star)

    st.divider()

    ov1, ov2, ov3, ov4 = st.columns(4)
    with ov1:
        st.subheader("Resolution SLA")
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta", 
            value=_ttr_met_pct, 
            number={"suffix": "%", "font": {"size": 28}},
            delta={"reference": 80, "suffix": "% vs 80% target", "relative": False},
            gauge={
                "axis": {"range": [0, 100]}, 
                "bar": {"color": "#00CC96" if _ttr_met_pct >= 80 else "#EF553B"},
                "steps": [{"range": [0, 80], "color": "#fde8e8"}, {"range": [80, 100], "color": "#e8f8f2"}],
                "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}
            }, 
            title={"text": "Met %"}
        ))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with ov2:
        st.subheader("First Response SLA")
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta", 
            value=_tfr_met_pct, 
            number={"suffix": "%", "font": {"size": 28}},
            delta={"reference": 80, "suffix": "% vs 80% target", "relative": False},
            gauge={
                "axis": {"range": [0, 100]}, 
                "bar": {"color": "#00CC96" if _tfr_met_pct >= 80 else "#EF553B"},
                "steps": [{"range": [0, 80], "color": "#fde8e8"}, {"range": [80, 100], "color": "#e8f8f2"}],
                "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}
            }, 
            title={"text": "Met %"}
        ))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with ov3:
        st.subheader("Satisfaction Score")
        fig = go.Figure(go.Indicator(
            mode="gauge+number", 
            value=_avg_sat, 
            number={"suffix": " / 5", "font": {"size": 28}},
            gauge={
                "axis": {"range": [1, 5]}, 
                "bar": {"color": "#636EFA"},
                "steps": [
                    {"range": [1, 3], "color": "#fde8e8"}, 
                    {"range": [3, 4], "color": "#fff5e0"}, 
                    {"range": [4, 5], "color": "#e8f8f2"}
                ],
                "threshold": {"line": {"color": "green", "width": 3}, "value": 4}
            }, 
            title={"text": "Avg Score"}
        ))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with ov4:
        st.subheader("Satisfaction Ratings")
        if len(_sat) > 0:
            sat_dist = _sat["Satisfaction"].value_counts()
            sat_dist = sat_dist.sort_index().reset_index()
            sat_dist.columns = ["Score", "Count"]
            sat_dist["Label"] = sat_dist["Score"].astype(int).astype(str) + " ⭐"
            
            fig = px.bar(
                sat_dist, x="Label", y="Count", color="Score", 
                color_continuous_scale=[[0, "#EF553B"], [0.5, "#FECB52"], [1.0, "#00CC96"]], 
                text="Count"
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(
                coloraxis_showscale=False, showlegend=False, 
                margin=dict(l=0, r=0, t=30, b=0), height=220, 
                xaxis_title="", yaxis_title=""
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Tickets by Status")
        sc = df["Status"].value_counts().reset_index()
        sc.columns = ["Status", "Count"]
        color_map = {
            "Open": "#EF553B", "In Progress": "#FFA15A", 
            "Resolved": "#00CC96", "Closed": "#636EFA", "Canceled": "#AB63FA"
        }
        fig = px.bar(
            sc, x="Count", y="Status", orientation="h", 
            color="Status", color_discrete_map=color_map, text="Count"
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Tickets by Priority")
        pc = df["Priority"].value_counts().reset_index()
        pc.columns = ["Priority", "Count"]
        fig = px.pie(
            pc, names="Priority", values="Count", hole=0.45, 
            color="Priority", color_discrete_map=PCOLOR
        )
        fig.update_traces(textinfo="label+percent+value")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Resolution Breakdown")
    rc = df["Resolution"].fillna("Unresolved").value_counts().reset_index()
    rc.columns = ["Resolution", "Count"]
    fig = px.pie(rc, names="Resolution", values="Count", hole=0.45)
    fig.update_traces(textinfo="label+percent+value")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Monthly Ticket Volume")
    monthly = df.groupby("YearMonth").size().reset_index(name="Tickets")
    monthly_res = df[df["Resolved_dt"].notna()].copy()
    monthly_res["ResolvedMonth"] = monthly_res["Resolved_dt"].dt.to_period("M").astype(str)
    monthly_res_agg = monthly_res.groupby("ResolvedMonth").size().reset_index(name="Resolved")
    
    combined = monthly.merge(
        monthly_res_agg, left_on="YearMonth", right_on="ResolvedMonth", how="left"
    ).fillna(0)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=combined["YearMonth"], y=combined["Tickets"], 
        mode="lines+markers", name="Created", line=dict(color="#636EFA", width=2)
    ))
    fig.add_trace(go.Scatter(
        x=combined["YearMonth"], y=combined["Resolved"], 
        mode="lines+markers", name="Resolved", line=dict(color="#00CC96", width=2)
    ))
    fig.update_layout(
        xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0), 
        legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------
# TAB 2: TICKET ANALYSIS
# ------------------------------------------
with tab2:
    st.subheader("Request Type Distribution")
    rt = df["Request Type"].value_counts().reset_index()
    rt.columns = ["Request Type", "Count"]
    fig = px.bar(
        rt.head(20), x="Count", y="Request Type", orientation="h",
        color="Count", color_continuous_scale="Blues", text="Count"
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Priority × Status Heatmap")
        priority_order = ["Critical", "High", "Medium", "Low"]
        piv = df.groupby(["Priority", "Status"]).size().unstack(fill_value=0)
        piv = piv.reindex([p for p in priority_order if p in piv.index])
        fig = px.imshow(piv, text_auto=True, color_continuous_scale="YlOrRd", aspect="auto")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Issue Type × Priority")
        piv2 = df.groupby(["Issue Type", "Priority"]).size().unstack(fill_value=0)
        fig = px.imshow(piv2, text_auto=True, color_continuous_scale="Blues", aspect="auto")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Tickets by Day of Week")
        dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        dow = df["DayOfWeek"].value_counts().reindex(dow_order).fillna(0).reset_index()
        dow.columns = ["Day", "Count"]
        fig = px.bar(
            dow, x="Day", y="Count", color="Count", 
            color_continuous_scale="Purples", text="Count"
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col4:
        st.subheader("Tickets by Hour of Day")
        hour_counts = df["Hour"].value_counts().sort_index().reset_index()
        hour_counts.columns = ["Hour", "Count"]
        fig = px.bar(
            hour_counts, x="Hour", y="Count", color="Count", 
            color_continuous_scale="Teal", text="Count"
        )
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Status Category Over Time")
    if "Status Category" in df.columns:
        sc_time = df.groupby(["YearMonth", "Status Category"]).size().reset_index(name="Count")
        fig = px.area(
            sc_time, x="YearMonth", y="Count", color="Status Category", 
            color_discrete_map={"Done": "#00CC96", "In Progress": "#FFA15A", "To Do": "#636EFA"}
        )
        fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------
# TAB 3: SLA
# ------------------------------------------
with tab3:
    tfr_all = df[df["TFR_met"].notna()]
    ttr_all = df[df["TTR_met"].notna()]
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FR SLA Met", f"{100 * (tfr_all['TFR_met'] == 'Met').mean() if len(tfr_all) else 0:.1f}%")
    c2.metric("FR SLA Breached", f"{100 * (tfr_all['TFR_met'] == 'Breached').mean() if len(tfr_all) else 0:.1f}%")
    c3.metric("Res SLA Met", f"{100 * (ttr_all['TTR_met'] == 'Met').mean() if len(ttr_all) else 0:.1f}%")
    c4.metric("Res SLA Breached", f"{100 * (ttr_all['TTR_met'] == 'Breached').mean() if len(ttr_all) else 0:.1f}%")
    
    with st.expander("🔎 View Breached Tickets"):
        breach_type = st.radio("Show breaches for", ["First Response SLA", "Resolution Time SLA"], horizontal=True)
        if breach_type == "First Response SLA":
            b_df = tfr_all[tfr_all["TFR_met"] == "Breached"]
        else:
            b_df = ttr_all[ttr_all["TTR_met"] == "Breached"]
            
        disp_cols = ["Issue key", "Summary", "Status", "Priority", "Assignee", "Created"]
        st.dataframe(b_df[disp_cols].sort_values("Created", ascending=False), use_container_width=True, hide_index=True)

# ------------------------------------------
# TAB 4: SATISFACTION
# ------------------------------------------
with tab4:
    if len(_sat) > 0:
        c1, c2 = st.columns(2)
        with c1: 
            sat_dist_2 = _sat["Satisfaction"].value_counts().sort_index().reset_index()
            sat_dist_2.columns = ["Satisfaction", "Count"]
            fig = px.bar(
                sat_dist_2, x="Satisfaction", y="Count", text="Count", 
                title="Score Distribution"
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig, use_container_width=True)
            
        with c2: 
            sat_pri = _sat.groupby("Priority")["Satisfaction"].mean().reset_index()
            sat_pri.columns = ["Priority", "Avg"]
            fig = px.bar(
                sat_pri, x="Priority", y="Avg", color="Priority", 
                color_discrete_map=PCOLOR, text=np.round(sat_pri["Avg"], 2), 
                title="CSAT by Priority"
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig, use_container_width=True)
    else: 
        st.info("No satisfaction ratings available.")

# ------------------------------------------
# TAB 5: TRENDS & RAW DATA
# ------------------------------------------
with tab5:
    st.subheader("📋 Raw Data Explorer")
    search = st.text_input("Search in Summary", "")
    
    if search:
        disp = df[df["Summary"].fillna("").str.contains(search, case=False)]
    else:
        disp = df
        
    cols = st.multiselect(
        "Columns", 
        ["Issue key", "Summary", "Status", "Priority", "Assignee", "Created", "Resolution", "TTR_met", "TFR_met", "Satisfaction"], 
        default=["Issue key", "Summary", "Status", "Priority", "Assignee", "Created"]
    )
    
    st.dataframe(disp[cols].sort_values("Created", ascending=False).head(1000), use_container_width=True, hide_index=True)
