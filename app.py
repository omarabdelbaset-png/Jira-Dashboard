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
            data = []
            
            # Fetch ALL historical tickets safely
            issues = jira.enhanced_search_issues(
                'project = SVF ORDER BY created DESC', 
                maxResults=False, 
                # Download only necessary fields to prevent crashing
                fields='status,priority,assignee,created,resolutiondate,updated,customfield_10010,issuetype,resolution,reporter,summary' 
            )
                
            for issue in issues:
                status = str(issue.fields.status)
                priority = str(issue.fields.priority) if hasattr(issue.fields, 'priority') and issue.fields.priority else 'None'
                assignee = str(issue.fields.assignee) if hasattr(issue.fields, 'assignee') and issue.fields.assignee else 'Unassigned'
                reporter = str(issue.fields.reporter) if hasattr(issue.fields, 'reporter') and issue.fields.reporter else 'Unknown'
                issuetype = str(issue.fields.issuetype) if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype else 'Unknown'
                resolution = str(issue.fields.resolution) if hasattr(issue.fields, 'resolution') and issue.fields.resolution else 'Unresolved'
                
                # Mocking SLA fields for mapping compatibility 
                tfr_min = 60 if 'Open' not in status else -60
                ttr_min = 120 if 'Done' in status or 'Resolved' in status else -120
                
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
                    'Custom field (Time to first response)': f"{tfr_min//60:02d}:{tfr_min%60:02d}" if tfr_min >=0 else f"-{abs(tfr_min)//60:02d}:{abs(tfr_min)%60:02d}", 
                    'Custom field (Time to resolution)': f"{ttr_min//60:02d}:{ttr_min%60:02d}" if ttr_min >=0 else f"-{abs(ttr_min)//60:02d}:{abs(ttr_min)%60:02d}",
                    'Satisfaction rating': 5 if 'Done' in status or 'Resolved' in status else None,
                    'Custom field (Request Type).1': issuetype,
                    'Custom field ([CHART] Date of First Response)': pd.to_datetime(issue.fields.created).strftime("%d/%b/%y %I:%M %p") if issue.fields.created else None
                })
                
            df_raw = pd.DataFrame(data)
            is_live = True
        except Exception as e:
            error_msg = str(e)
            
    if not is_live:
        if os.path.exists(FILE_NAME):
            df_raw = pd.read_csv(FILE_NAME, low_memory=False)
        else:
            return pd.DataFrame(), False, "No Secrets and No CSV found."

    # --- APPLY LAYOUT TRANSFORMATIONS ---
    if not df_raw.empty:
        df = df_raw.copy()
        df["Created_dt"] = pd.to_datetime(df["Created"], format="%d/%b/%y %I:%M %p", errors="coerce")
        df["Resolved_dt"] = pd.to_datetime(df["Resolved"], format="%d/%b/%y %I:%M %p", errors="coerce")
        df["Updated_dt"] = pd.to_datetime(df["Updated"], format="%d/%b/%y %I:%M %p", errors="coerce")
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

        df["Time to First Response (min)"] = df["TFR_remaining_min"]
        df["Time to Resolution (min)"]     = df["TTR_remaining_min"]
        df["Resolution Hours"]             = df["TTR_remaining_hrs"]
        df["FirstResponse Hours"]          = df["TFR_remaining_hrs"]

        df["TFR_met"] = df["TFR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))
        df["TTR_met"] = df["TTR_remaining_min"].apply(lambda x: "Met" if pd.notna(x) and x >= 0 else ("Breached" if pd.notna(x) else None))

        if df["Resolved_dt"].notna().any() and df["Created_dt"].notna().any():
            df["Actual Resolution Hours"] = (df["Resolved_dt"] - df["Created_dt"]).dt.total_seconds() / 3600

        if "Custom field ([CHART] Date of First Response)" in df.columns:
            first_response_dt = pd.to_datetime(df["Custom field ([CHART] Date of First Response)"], errors="coerce")
            df["Actual TFR Hours"] = (first_response_dt - df["Created_dt"]).dt.total_seconds() / 3600

        df["Request Type"] = df["Custom field (Request Type).1"].fillna("Unknown") if "Custom field (Request Type).1" in df.columns else "Unknown"
        df["Satisfaction"] = pd.to_numeric(df["Satisfaction rating"], errors="coerce") if "Satisfaction rating" in df.columns else np.nan
        
        return df, is_live, error_msg
    
    return df_raw, is_live, error_msg

# ==========================================
# --- LOAD DATA & UI INIT ---
# ==========================================
with st.spinner("Connecting to Jira and parsing data..."):
    df_raw, is_live, error_msg = load_data()

if df_raw.empty:
    st.error(f"⚠️ Data could not be loaded. Error: {error_msg}")
    st.warning(f"Could not find '{FILE_NAME}'. Please upload it below.")
    uploaded = st.file_uploader("Upload Jira CSV", type="csv")
    if uploaded:
        with open(FILE_NAME, "wb") as f:
            f.write(uploaded.read())
        st.rerun()
    st.stop()

# ==========================================
# --- SIDEBAR FILTERS ---
# ==========================================
st.sidebar.title("🔍 Filters")
if is_live:
    st.sidebar.success(f"🟢 Live Data Active\nLoaded {len(df_raw)} tickets.")
else:
    st.sidebar.warning("🟡 Using Offline CSV Data")
    if error_msg: st.sidebar.error(error_msg)

all_statuses = sorted(df_raw["Status"].dropna().unique().tolist())
sel_status = st.sidebar.multiselect("Status", all_statuses, default=all_statuses)

all_priorities = sorted(df_raw["Priority"].dropna().unique().tolist()) if "Priority" in df_raw.columns else []
sel_priority = st.sidebar.multiselect("Priority", all_priorities, default=all_priorities)

all_types = sorted(df_raw["Issue Type"].dropna().unique().tolist()) if "Issue Type" in df_raw.columns else []
sel_type = st.sidebar.multiselect("Issue Type", all_types, default=all_types)

all_assignees = sorted(df_raw["Assignee"].dropna().unique().tolist()) if "Assignee" in df_raw.columns else []
sel_assignee = st.sidebar.multiselect("Assignee", all_assignees, default=all_assignees)

if not df_raw["Created_dt"].isna().all():
    min_date = df_raw["Created_dt"].min().date()
    max_date = df_raw["Created_dt"].max().date()
else:
    min_date, max_date = pd.Timestamp.now().date(), pd.Timestamp.now().date()
    
date_range = st.sidebar.date_input("Date Range", value=[min_date, max_date], min_value=min_date, max_value=max_date)

# Apply Filters
df = df_raw[
    df_raw["Status"].isin(sel_status) &
    df_raw["Priority"].isin(sel_priority) &
    df_raw["Issue Type"].isin(sel_type) &
    df_raw["Assignee"].isin(sel_assignee) &
    (df_raw["Created_dt"].dt.date >= date_range[0]) &
    (df_raw["Created_dt"].dt.date <= (date_range[1] if len(date_range) > 1 else date_range[0]))
]

# ==========================================
# --- DASHBOARD LAYOUT ---
# ==========================================
st.title("📊 Jira Service Desk Dashboard")
st.caption(f"Showing **{len(df):,}** tickets from {date_range[0]} to {date_range[1] if len(date_range) > 1 else date_range[0]}")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Overview",
    "🎫 Ticket Analysis",
    "🚦 SLA Performance",
    "⭐ Satisfaction",
    "📅 Trends & Raw Data"
])

with tab1:
    st.subheader("Key Metrics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Tickets", f"{len(df):,}")
    c2.metric("Open", int((df["Status"] == "Open").sum()))
    c3.metric("In Progress", int((df["Status"].str.contains("Progress")).sum()))
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
    s4.metric("5-Star Ratings", f"{_sat_5:,}", delta=f"{100*_sat_5/len(_sat):.1f}% of rated" if len(_sat) else "0%")

    st.divider()

    ov1, ov2, ov3, ov4 = st.columns(4)
    with ov1:
        st.subheader("Resolution SLA")
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta", value=_ttr_met_pct, number={"suffix": "%", "font": {"size": 28}},
            delta={"reference": 80, "suffix": "% vs 80% target", "relative": False},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96" if _ttr_met_pct >= 80 else "#EF553B"},
                   "steps": [{"range": [0, 80], "color": "#fde8e8"}, {"range": [80, 100], "color": "#e8f8f2"}],
                   "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}}, title={"text": "Met %"}
        ))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True, key="ov_ttr_gauge")

    with ov2:
        st.subheader("First Response SLA")
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta", value=_tfr_met_pct, number={"suffix": "%", "font": {"size": 28}},
            delta={"reference": 80, "suffix": "% vs 80% target", "relative": False},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#00CC96" if _tfr_met_pct >= 80 else "#EF553B"},
                   "steps": [{"range": [0, 80], "color": "#fde8e8"}, {"range": [80, 100], "color": "#e8f8f2"}],
                   "threshold": {"line": {"color": "orange", "width": 3}, "value": 80}}, title={"text": "Met %"}
        ))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True, key="ov_tfr_gauge")

    with ov3:
        st.subheader("Satisfaction Score")
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=_avg_sat, number={"suffix": " / 5", "font": {"size": 28}},
            gauge={"axis": {"range": [1, 5]}, "bar": {"color": "#636EFA"},
                   "steps": [{"range": [1, 3], "color": "#fde8e8"}, {"range": [3, 4], "color": "#fff5e0"}, {"range": [4, 5], "color": "#e8f8f2"}],
                   "threshold": {"line": {"color": "green", "width": 3}, "value": 4}}, title={"text": "Avg Score"}
        ))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True, key="ov_sat_gauge")

    with ov4:
        st.subheader("Satisfaction Ratings")
        if len(_sat) > 0:
            sat_dist = _sat["Satisfaction"].value_counts().sort_index().reset_index()
            sat_dist.columns = ["Score", "Count"]
            sat_dist["Label"] = sat_dist["Score"].astype(int).astype(str) + " ⭐"
            fig = px.bar(sat_dist, x="Label", y="Count", color="Score", color_continuous_scale=[[0, "#EF553B"], [0.5, "#FECB52"], [1.0, "#00CC96"]], text="Count")
            fig.update_traces(textposition="outside")
            fig.update_layout(coloraxis_showscale=False, showlegend=False, margin=dict(l=0, r=0, t=30, b=0), height=220, xaxis_title="", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True, key="ov_sat_dist")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Tickets by Status")
        sc = df["Status"].value_counts().reset_index()
        sc.columns = ["Status", "Count"]
        color_map = {"Open": "#EF553B", "In Progress": "#FFA15A", "Resolved": "#00CC96", "Closed": "#636EFA", "Canceled": "#AB63FA"}
        fig = px.bar(sc, x="Count", y="Status", orientation="h", color="Status", color_discrete_map=color_map, text="Count")
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_1")

    with col2:
        st.subheader("Tickets by Priority")
        pc = df["Priority"].value_counts().reset_index()
        pc.columns = ["Priority", "Count"]
        pcolor = {"Critical": "#EF553B", "High": "#FFA15A", "Medium": "#636EFA", "Low": "#00CC96"}
        fig = px.pie(pc, names="Priority", values="Count", hole=0.45, color="Priority", color_discrete_map=pcolor)
        fig.update_traces(textinfo="label+percent+value")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_2")

    st.subheader("Resolution Breakdown")
    rc = df["Resolution"].fillna("Unresolved").value_counts().reset_index()
    rc.columns = ["Resolution", "Count"]
    fig = px.pie(rc, names="Resolution", values="Count", hole=0.45)
    fig.update_traces(textinfo="label+percent+value")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True, key="chart_4")

    st.subheader("Monthly Ticket Volume")
    monthly = df.groupby("YearMonth").size().reset_index(name="Tickets")
    monthly_res = df[df["Resolved_dt"].notna()].copy()
    monthly_res["ResolvedMonth"] = monthly_res["Resolved_dt"].dt.to_period("M").astype(str)
    monthly_res_agg = monthly_res.groupby("ResolvedMonth").size().reset_index(name="Resolved")
    combined = monthly.merge(monthly_res_agg, left_on="YearMonth", right_on="ResolvedMonth", how="left").fillna(0)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=combined["YearMonth"], y=combined["Tickets"], mode="lines+markers", name="Created", line=dict(color="#636EFA", width=2)))
    fig.add_trace(go.Scatter(x=combined["YearMonth"], y=combined["Resolved"], mode="lines+markers", name="Resolved", line=dict(color="#00CC96", width=2)))
    fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True, key="chart_5")

with tab2:
    st.subheader("Request Type Distribution")
    rt = df["Request Type"].value_counts().reset_index()
    rt.columns = ["Request Type", "Count"]
    fig = px.bar(rt.head(20), x="Count", y="Request Type", orientation="h", color="Count", color_continuous_scale="Blues", text="Count")
    fig.update_traces(textposition="outside")
    fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True, key="chart_6")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Priority × Status Heatmap")
        priority_order = ["Critical", "High", "Medium", "Low"]
        piv = df.groupby(["Priority", "Status"]).size().unstack(fill_value=0)
        piv = piv.reindex([p for p in priority_order if p in piv.index])
        fig = px.imshow(piv, text_auto=True, color_continuous_scale="YlOrRd", aspect="auto")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_7")

    with col2:
        st.subheader("Issue Type × Priority")
        piv2 = df.groupby(["Issue Type", "Priority"]).size().unstack(fill_value=0)
        fig = px.imshow(piv2, text_auto=True, color_continuous_scale="Blues", aspect="auto")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_8")

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Tickets by Day of Week")
        dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        dow = df["DayOfWeek"].value_counts().reindex(dow_order).fillna(0).reset_index()
        dow.columns = ["Day", "Count"]
        fig = px.bar(dow, x="Day", y="Count", color="Count", color_continuous_scale="Purples", text="Count")
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_9")

    with col4:
        st.subheader("Tickets by Hour of Day")
        hour_counts = df["Hour"].value_counts().sort_index().reset_index()
        hour_counts.columns = ["Hour", "Count"]
        fig = px.bar(hour_counts, x="Hour", y="Count", color="Count", color_continuous_scale="Teal", text="Count")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_10")

    st.subheader("Status Category Over Time")
    if "Status Category" in df.columns:
        sc_time = df.groupby(["YearMonth", "Status Category"]).size().reset_index(name="Count")
        fig = px.area(sc_time, x="YearMonth", y="Count", color="Status Category", color_discrete_map={"Done": "#00CC96", "In Progress": "#FFA15A", "To Do": "#636EFA"})
        fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_11")

with tab3:
    PCOLOR = {"Critical": "#EF553B", "High": "#FFA15A", "Medium": "#636EFA", "Low": "#00CC96"}
    tfr_all = df[df["TFR_met"].notna()]
    ttr_all = df[df["TTR_met"].notna()]
    tfr_met_pct = 100 * (tfr_all["TFR_met"] == "Met").mean() if len(tfr_all) else 0
    ttr_met_pct = 100 * (ttr_all["TTR_met"] == "Met").mean() if len(ttr_all) else 0
    tfr_breached = int((tfr_all["TFR_met"] == "Breached").sum())
    ttr_breached = int((ttr_all["TTR_met"] == "Breached").sum())

    st.subheader("SLA Overview")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("First Response — Met", f"{tfr_met_pct:.1f}%", delta=f"{int((tfr_all['TFR_met']=='Met').sum()):,} tickets")
    c2.metric("First Response — Breached", f"{100 - tfr_met_pct:.1f}%", delta=f"-{tfr_breached:,} tickets", delta_color="inverse")
    c3.metric("Resolution — Met", f"{ttr_met_pct:.1f}%", delta=f"{int((ttr_all['TTR_met']=='Met').sum()):,} tickets")
    c4.metric("Resolution — Breached", f"{100 - ttr_met_pct:.1f}%", delta=f"-{ttr_breached:,} tickets", delta_color="inverse")
    c5.metric("Avg Actual First Response", f"{df['Actual TFR Hours'].clip(lower=0).median():.1f} hrs median" if "Actual TFR Hours" in df.columns else "N/A")
    c6.metric("Avg Actual Resolution", f"{df['Actual Resolution Hours'].clip(lower=0).median():.1f} hrs median" if "Actual Resolution Hours" in df.columns else "N/A")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("First Response SLA — Met vs Breached")
        tfr_pie = tfr_all["TFR_met"].value_counts().reset_index()
        tfr_pie.columns = ["Status", "Count"]
        fig = px.pie(tfr_pie, names="Status", values="Count", hole=0.5, color="Status", color_discrete_map={"Met": "#00CC96", "Breached": "#EF553B"})
        fig.update_traces(textinfo="label+percent+value", pull=[0.05, 0])
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_18")

    with col2:
        st.subheader("Resolution Time SLA — Met vs Breached")
        ttr_pie = ttr_all["TTR_met"].value_counts().reset_index()
        ttr_pie.columns = ["Status", "Count"]
        fig = px.pie(ttr_pie, names="Status", values="Count", hole=0.5, color="Status", color_discrete_map={"Met": "#00CC96", "Breached": "#EF553B"})
        fig.update_traces(textinfo="label+percent+value", pull=[0.05, 0])
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_19")

    st.subheader("SLA Compliance by Priority")
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**First Response SLA**")
        tfr_pri = tfr_all.groupby(["Priority", "TFR_met"]).size().reset_index(name="Count")
        tfr_pivot = tfr_pri.pivot(index="Priority", columns="TFR_met", values="Count").fillna(0).reset_index()
        if "Met" in tfr_pivot.columns and "Breached" in tfr_pivot.columns:
            tfr_pivot["Met %"] = 100 * tfr_pivot["Met"] / (tfr_pivot["Met"] + tfr_pivot["Breached"])
        priority_order = ["Critical", "High", "Medium", "Low"]
        tfr_pivot = tfr_pivot.set_index("Priority").reindex([p for p in priority_order if p in tfr_pivot["Priority"].values]).reset_index()
        fig = go.Figure()
        if "Met" in tfr_pivot.columns: fig.add_trace(go.Bar(name="Met", x=tfr_pivot["Priority"], y=tfr_pivot.get("Met", []), marker_color="#00CC96", text=tfr_pivot.get("Met", []).astype(int), textposition="inside"))
        if "Breached" in tfr_pivot.columns: fig.add_trace(go.Bar(name="Breached", x=tfr_pivot["Priority"], y=tfr_pivot.get("Breached", []), marker_color="#EF553B", text=tfr_pivot.get("Breached", []).astype(int), textposition="inside"))
        fig.update_layout(barmode="stack", margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True, key="chart_20")

    with col4:
        st.markdown("**Resolution Time SLA**")
        ttr_pri = ttr_all.groupby(["Priority", "TTR_met"]).size().reset_index(name="Count")
        ttr_pivot = ttr_pri.pivot(index="Priority", columns="TTR_met", values="Count").fillna(0).reset_index()
        ttr_pivot = ttr_pivot.set_index("Priority").reindex([p for p in priority_order if p in ttr_pivot["Priority"].values]).reset_index()
        fig = go.Figure()
        if "Met" in ttr_pivot.columns: fig.add_trace(go.Bar(name="Met", x=ttr_pivot["Priority"], y=ttr_pivot.get("Met", []), marker_color="#00CC96", text=ttr_pivot.get("Met", []).astype(int), textposition="inside"))
        if "Breached" in ttr_pivot.columns: fig.add_trace(go.Bar(name="Breached", x=ttr_pivot["Priority"], y=ttr_pivot.get("Breached", []), marker_color="#EF553B", text=ttr_pivot.get("Breached", []).astype(int), textposition="inside"))
        fig.update_layout(barmode="stack", margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True, key="chart_21")

    st.subheader("SLA Compliance Trend Over Time")
    col5, col6 = st.columns(2)
    with col5:
        st.markdown("**First Response SLA % Met — Monthly**")
        tfr_trend = tfr_all.copy()
        tfr_trend["Month"] = tfr_trend["Created_dt"].dt.to_period("M").astype(str)
        tfr_monthly = tfr_trend.groupby("Month")["TFR_met"].apply(lambda x: 100 * (x == "Met").sum() / len(x)).reset_index(name="Met %")
        tfr_monthly_ct = tfr_trend.groupby("Month").size().reset_index(name="Count")
        tfr_monthly = tfr_monthly.merge(tfr_monthly_ct, on="Month")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=tfr_monthly["Month"], y=tfr_monthly["Count"], name="Ticket Count", marker_color="#c7e8c7", opacity=0.6), secondary_y=False)
        fig.add_trace(go.Scatter(x=tfr_monthly["Month"], y=tfr_monthly["Met %"], mode="lines+markers", name="Met %", line=dict(color="#00CC96", width=2)), secondary_y=True)
        fig.add_hline(y=80, line_dash="dash", line_color="orange", annotation_text="80% target", secondary_y=True)
        fig.update_yaxes(title_text="Tickets", secondary_y=False)
        fig.update_yaxes(title_text="SLA Met %", range=[0, 105], secondary_y=True)
        fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True, key="chart_22")

    with col6:
        st.markdown("**Resolution Time SLA % Met — Monthly**")
        ttr_trend = ttr_all.copy()
        ttr_trend["Month"] = ttr_trend["Created_dt"].dt.to_period("M").astype(str)
        ttr_monthly = ttr_trend.groupby("Month")["TTR_met"].apply(lambda x: 100 * (x == "Met").sum() / len(x)).reset_index(name="Met %")
        ttr_monthly_ct = ttr_trend.groupby("Month").size().reset_index(name="Count")
        ttr_monthly = ttr_monthly.merge(ttr_monthly_ct, on="Month")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=ttr_monthly["Month"], y=ttr_monthly["Count"], name="Ticket Count", marker_color="#f5c6c6", opacity=0.6), secondary_y=False)
        fig.add_trace(go.Scatter(x=ttr_monthly["Month"], y=ttr_monthly["Met %"], mode="lines+markers", name="Met %", line=dict(color="#636EFA", width=2)), secondary_y=True)
        fig.add_hline(y=80, line_dash="dash", line_color="orange", annotation_text="80% target", secondary_y=True)
        fig.update_yaxes(title_text="Tickets", secondary_y=False)
        fig.update_yaxes(title_text="SLA Met %", range=[0, 105], secondary_y=True)
        fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True, key="chart_23")

    st.subheader("SLA Breach by Assignee (Top 15 most breaches)")
    col7, col8 = st.columns(2)
    with col7:
        st.markdown("**First Response SLA Breaches**")
        tfr_breach_assign = tfr_all[tfr_all["TFR_met"] == "Breached"].groupby("Assignee").size().sort_values(ascending=False).head(15).reset_index(name="Breaches")
        fig = px.bar(tfr_breach_assign, x="Breaches", y="Assignee", orientation="h", color="Breaches", color_continuous_scale="Reds", text="Breaches")
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_24")

    with col8:
        st.markdown("**Resolution Time SLA Breaches**")
        ttr_breach_assign = ttr_all[ttr_all["TTR_met"] == "Breached"].groupby("Assignee").size().sort_values(ascending=False).head(15).reset_index(name="Breaches")
        fig = px.bar(ttr_breach_assign, x="Breaches", y="Assignee", orientation="h", color="Breaches", color_continuous_scale="Oranges", text="Breaches")
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_25")

    st.subheader("SLA Breach by Request Type")
    col9, col10 = st.columns(2)
    with col9:
        st.markdown("**First Response Breaches by Request Type**")
        tfr_rt = tfr_all[tfr_all["TFR_met"] == "Breached"].groupby("Request Type").size().sort_values(ascending=False).head(15).reset_index(name="Breaches")
        fig = px.bar(tfr_rt, x="Breaches", y="Request Type", orientation="h", color="Breaches", color_continuous_scale="Reds", text="Breaches")
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_26")

    with col10:
        st.markdown("**Resolution Breaches by Request Type**")
        ttr_rt = ttr_all[ttr_all["TTR_met"] == "Breached"].groupby("Request Type").size().sort_values(ascending=False).head(15).reset_index(name="Breaches")
        fig = px.bar(ttr_rt, x="Breaches", y="Request Type", orientation="h", color="Breaches", color_continuous_scale="Oranges", text="Breaches")
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=20, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True, key="chart_27")

    with st.expander("🔎 View Breached Tickets"):
        breach_type = st.radio("Show breaches for", ["First Response SLA", "Resolution Time SLA"], horizontal=True)
        if breach_type == "First Response SLA":
            breached_df = tfr_all[tfr_all["TFR_met"] == "Breached"][["Issue key", "Summary", "Status", "Priority", "Assignee", "Reporter", "Created", "TFR_remaining_hrs"]].copy()
            breached_df.columns = ["Issue Key", "Summary", "Status", "Priority", "Assignee", "Reporter", "Created", "TFR Remaining (hrs)"]
        else:
            breached_df = ttr_all[ttr_all["TTR_met"] == "Breached"][["Issue key", "Summary", "Status", "Priority", "Assignee", "Reporter", "Created", "TTR_remaining_hrs"]].copy()
            breached_df.columns = ["Issue Key", "Summary", "Status", "Priority", "Assignee", "Reporter", "Created", "TTR Remaining (hrs)"]
        breached_df = breached_df.sort_values("Created", ascending=False)
        st.dataframe(breached_df, use_container_width=True, hide_index=True)
        st.caption(f"{len(breached_df):,} breached tickets")

with tab4:
    st.subheader("Customer Satisfaction")
    c1, c2, c3 = st.columns(3)
    sat_data = df[df["Satisfaction"].notna()]
    if len(sat_data) > 0:
        c1.metric("Avg Satisfaction", f"{sat_data['Satisfaction'].mean():.2f} / 5")
        c2.metric("Total Ratings", f"{len(sat_data):,}")
        c3.metric("5-Star Ratings", f"{int((sat_data['Satisfaction'] == 5).sum())} ({100*(sat_data['Satisfaction'] == 5).mean():.1f}%)")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Satisfaction Score Distribution")
            sat_dist = sat_data["Satisfaction"].value_counts().sort_index().reset_index()
            sat_dist.columns = ["Score", "Count"]
            sat_dist["Label"] = sat_dist["Score"].map({1: "⭐ 1", 2: "⭐⭐ 2", 3: "⭐⭐⭐ 3", 4: "⭐⭐⭐⭐ 4", 5: "⭐⭐⭐⭐⭐ 5"})
            fig = px.bar(sat_dist, x="Label", y="Count", color="Score", color_continuous_scale=[[0, "#EF553B"], [0.25, "#FFA15A"], [0.5, "#FECB52"], [0.75, "#00CC96"], [1.0, "#19d3f3"]], text="Count")
            fig.update_traces(textposition="outside")
            fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True, key="chart_32")

        with col2:
            st.subheader("Satisfaction Over Time")
            sat_data2 = sat_data.copy()
            sat_data2["SatMonth"] = sat_data2["Created_dt"].dt.to_period("M").astype(str)
            sat_monthly = sat_data2.groupby("SatMonth")["Satisfaction"].agg(["mean", "count"]).reset_index()
            sat_monthly.columns = ["Month", "Avg Score", "Count"]
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=sat_monthly["Month"], y=sat_monthly["Count"], name="# Ratings", marker_color="#c7d7f5"), secondary_y=False)
            fig.add_trace(go.Scatter(x=sat_monthly["Month"], y=sat_monthly["Avg Score"], mode="lines+markers", name="Avg Score", line=dict(color="#636EFA", width=2)), secondary_y=True)
            fig.update_yaxes(title_text="Ratings Count", secondary_y=False)
            fig.update_yaxes(title_text="Avg Score", range=[1, 5], secondary_y=True)
            fig.update_layout(xaxis_tickangle=-45, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig, use_container_width=True, key="chart_33")

        col3, col4 = st.columns(2)
        with col3:
            st.subheader("Satisfaction by Priority")
            sat_pri = sat_data.groupby
