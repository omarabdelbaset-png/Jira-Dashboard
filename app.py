import streamlit as st, pandas as pd, numpy as np, plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from jira import JIRA
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Facilities Team Dashboard", layout="wide")
st_autorefresh(interval=60000, key="j_ref")

# --- CUSTOM BACKGROUND AND STYLING ---
page_bg_img = '''
<style>
.stApp {
    /* Swapped to a permanent, public Unsplash image of a dark modern building */
    background-image: url("https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?q=80&w=2070&auto=format&fit=crop");
    background-size: cover;
    background-repeat: no-repeat;
    background-attachment: fixed;
    background-position: center;
}
.block-container {
    background-color: rgba(255, 255, 255, 0.95); 
    border-radius: 10px;
    padding: 2rem;
    margin-top: 2rem;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}
.stMetric {
    background-color: #f8f9fa;
    border-radius: 8px;
    padding: 12px;
} 
div[data-testid="metric-container"] {
    background-color: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 8px;
    padding: 16px;
}
</style>
'''
st.markdown(page_bg_img, unsafe_allow_html=True)

try: EM, TK = st.secrets["JIRA_EMAIL"], st.secrets["JIRA_API_TOKEN"]
except: EM, TK = None, None
PCOL = {"Critical":"#EF553B", "High":"#FFA15A", "Medium":"#636EFA", "Low":"#00CC96"}
C_MAP = {"Open":"#EF553B", "In Progress":"#FFA15A", "Resolved":"#00CC96", "Closed":"#636EFA", "Canceled":"#AB63FA"}

def p_hm(v):
    try: return int(v.split(":")[0])*60 + int(v.split(":")[1])
    except: return np.nan

def p_sla(s):
    if not s: return ""
    if type(s)==str and ":" in s: return s
    try:
        c = s.get('completedCycles',[{}])[-1] if type(s)==dict and s.get('completedCycles') else s.get('ongoingCycle',{})
        if c:
            m = c.get('remainingTime',{}).get('millis',0)/60000.0
            if c.get('breached') and m>0: m = -m
            return f"-{abs(int(m))//60:02d}:{abs(int(m))%60:02d}" if m<0 else f"{abs(int(m))//60:02d}:{abs(int(m))%60:02d}"
    except: pass
    return ""

def p_req(r):
    if not r: return "Unknown"
    if type(r)==str: return r.split('/')[-1].replace('-',' ').title() if '/' in r else r
    if type(r)==dict: return r.get('requestType',{}).get('name', r.get('name', r.get('value', r.get('currentValue', "Unknown"))))
    if type(r)==list and r: return p_req(r[0])
    return str(r)

def fetch_data(jql):
    df, err = pd.DataFrame(), None
    if EM and TK:
        try:
            j = JIRA("https://itsupportsivision.atlassian.net", basic_auth=(EM, TK))
            afs = j.fields()
            def gid(ns): return next((f['id'] for f in afs if any(n in f['name'].lower() for n in ns)), None)
            f_tfr, f_ttr, f_sat, f_req = gid(['time to first response']), gid(['time to resolution']), gid(['satisfaction rating','satisfaction']), gid(['customer request type','portal request type','request type'])
            flds = ['status','priority','assignee','created','resolutiondate','updated','issuetype','resolution','reporter','summary','customfield_10010'] + [x for x in [f_tfr,f_ttr,f_sat,f_req] if x]
            d = []
            
            # FIX 3: maxResults=False tells Jira to grab ALL 6,000+ tickets, fixing the hidden cutoff!
            for i in j.search_issues(jql, maxResults=False, fields=','.join(flds)):
                r = i.raw['fields']
                stt = str(i.fields.status)
                rq = p_req(r.get(f_req) or r.get('customfield_10010'))
                d.append({
                    'Issue key': i.key, 'Summary': i.fields.summary, 'Status': stt,
                    'Status Category': 'Done' if 'Done' in stt or 'Resolved' in stt else ('In Progress' if 'Progress' in stt else 'To Do'),
                    'Priority': str(i.fields.priority) if getattr(i.fields,'priority',None) else 'None',
                    'Assignee': str(i.fields.assignee) if getattr(i.fields,'assignee',None) else 'Unassigned',
                    'Reporter': str(i.fields.reporter) if getattr(i.fields,'reporter',None) else 'Unknown',
                    'Issue Type': str(i.fields.issuetype) if getattr(i.fields,'issuetype',None) else 'Unknown',
                    'Resolution': str(i.fields.resolution) if getattr(i.fields,'resolution',None) else 'Unresolved',
                    'Created': pd.to_datetime(i.fields.created).strftime("%d/%b/%y %I:%M %p") if i.fields.created else None,
                    'Resolved': pd.to_datetime(i.fields.resolutiondate).strftime("%d/%b/%y %I:%M %p") if getattr(i.fields,'resolutiondate',None) else None,
                    'TFR_raw': p_sla(r.get(f_tfr)) if f_tfr else "",
                    'TTR_raw': p_sla(r.get(f_ttr)) if f_ttr else "",
                    'Satisfaction': float(r.get(f_sat).get('rating') if type(r.get(f_sat))==dict else r.get(f_sat)) if f_sat and r.get(f_sat) else np.nan,
                    'Request Type': rq if rq!="Unknown" else (str(i.fields.issuetype) if getattr(i.fields,'issuetype',None) else "Unknown")
                })
            df = pd.DataFrame(d)
        except Exception as e: err = str(e)
    else:
        err = "Missing API Credentials."
    return df, err

@st.cache_data(ttl=86400)
def load_vault():
    if os.path.exists("jira_history.csv"): return pd.read_csv("jira_history.csv", low_memory=False), None
    return fetch_data('project=SVF ORDER BY created DESC')

@st.cache_data(ttl=55)
def load_live():
    # Adjusted to order by 'updated' so it never misses a status change
    return fetch_data('project=SVF AND updated >= -60d ORDER BY updated DESC')

with st.spinner("Accessing History Data (First run takes ~30 seconds)..."): df_v, err_v = load_vault()
with st.spinner("Syncing recent updates..."): df_l, err_l = load_live()

if err_l:
    st.error(f"🚨 JIRA API ERROR: {err_l}")

# --- FIX 1 (STEP 2): The perfect merge that crushes duplicates permanently ---
if df_v is not None and not df_v.empty and df_l is not None and not df_l.empty: 
    # pd.concat with drop_duplicates perfectly overwrites old statuses with the live ones
    df_raw = pd.concat([df_l, df_v]).drop_duplicates(subset=['Issue key'], keep='first')
    df_raw.to_csv("jira_history.csv", index=False) 
elif df_l is not None and not df_l.empty: 
    df_raw = df_l
    df_raw.to_csv("jira_history.csv", index=False)
elif df_v is not None and not df_v.empty: 
    df_raw = df_v
else: 
    st.error("Could not load data.")
    st.stop()
# -----------------------------------------------------------------------------

for c in ["Created", "Resolved"]: df_raw[f"{c}_dt"] = pd.to_datetime(df_raw[c], format="%d/%b/%y %I:%M %p", errors="coerce")
df_raw["YearMonth"] = df_raw["Created_dt"].dt.to_period("M").astype(str)
df_raw["Week"] = df_raw["Created_dt"].dt.to_period("W").astype(str)
df_raw["DayOfWeek"] = df_raw["Created_dt"].dt.day_name()
df_raw["Hour"] = df_raw["Created_dt"].dt.hour
df_raw["Year"] = df_raw["Created_dt"].dt.year
df_raw["TFR_m"], df_raw["TTR_m"] = df_raw["TFR_raw"].apply(p_hm), df_raw["TTR_raw"].apply(p_hm)
df_raw["TFR_met"] = df_raw["TFR_m"].apply(lambda x: "Met" if pd.notna(x) and x>=0 else ("Breached" if pd.notna(x) else None))
df_raw["TTR_met"] = df_raw["TTR_m"].apply(lambda x: "Met" if pd.notna(x) and x>=0 else ("Breached" if pd.notna(x) else None))
if df_raw["Resolved_dt"].notna().any() and df_raw["Created_dt"].notna().any(): df_raw["Act_Res"] = (df_raw["Resolved_dt"] - df_raw["Created_dt"]).dt.total_seconds()/3600

st.sidebar.title("🏢 Facilities Team")
st.sidebar.markdown("---")

if not os.path.exists("jira_history.csv"):
    st.sidebar.warning("⚠️ Recovery Mode: Missing history file.")
    st.sidebar.download_button("Download Recovery File", df_raw.to_csv(index=False).encode('utf-8'), "jira_history.csv", "text/csv")

m0 = dict(l=0, r=0, t=30, b=0)
def pc(fig, out=False):
    if out: fig.update_traces(textposition="outside")
    st.plotly_chart(fig.update_layout(margin=m0, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'), use_container_width=True)
def nl(fig, out=False):
    if out: fig.update_traces(textposition="outside")
    st.plotly_chart(fig.update_layout(showlegend=False, margin=m0, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'), use_container_width=True)

st.sidebar.title("🔍 Filters")
def ms(col): return st.sidebar.multiselect(col, sorted(df_raw[col].dropna().unique()), default=sorted(df_raw[col].dropna().unique()))
ss, sp, si, sa = ms("Status"), ms("Priority"), ms("Issue Type"), ms("Assignee")
d_min, d_max = (df_raw["Created_dt"].min().date(), df_raw["Created_dt"].max().date()) if not df_raw["Created_dt"].isna().all() else (pd.Timestamp.now().date(), pd.Timestamp.now().date())
dr = st.sidebar.date_input("Date Range", [d_min, d_max], min_value=d_min, max_value=d_max)
if len(dr)==1: dr=(dr[0],dr[0])

# --- FIX 2: All-Time Satisfaction Count ---
all_time_sat_count = df_raw["Satisfaction"].notna().sum() if "Satisfaction" in df_raw.columns else 0

df = df_raw[df_raw["Status"].isin(ss) & df_raw["Priority"].isin(sp) & df_raw["Issue Type"].isin(si) & df_raw["Assignee"].isin(sa) & (df_raw["Created_dt"].dt.date >= dr[0]) & (df_raw["Created_dt"].dt.date <= dr[1])]

st.title("📊 Facilities Team Dashboard")
t1, t2, t3, t4, t5 = st.tabs(["📈 Overview", "🎫 Ticket Analysis", "🚦 SLA", "⭐ Satisfaction", "📅 Data & Export"])

ttr, tfr, sat = df[df["TTR_met"].notna()], df[df["TFR_met"].notna()], df[df["Satisfaction"].notna()]
ttr_p = 100*(ttr["TTR_met"]=="Met").mean() if len(ttr) else 0
tfr_p = 100*(tfr["TFR_met"]=="Met").mean() if len(tfr) else 0
s_avg = sat["Satisfaction"].mean() if len(sat) else 0

with t1:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Tickets", f"{len(df):,}"); c2.metric("Open", int((df["Status"]=="Open").sum())); c3.metric("In Progress", int((df["Status"].str.contains("Progress", na=False)).sum()))
    c4.metric("Resolved", int((df["Status"]=="Resolved").sum())); c5.metric("Closed", int((df["Status"]=="Closed").sum())); c6.metric("Canceled", int((df["Status"]=="Canceled").sum()))
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Res SLA Met", f"{ttr_p:.1f}%", f"-{int((ttr['TTR_met']=='Breached').sum())} breached", "inverse")
    s2.metric("FR SLA Met", f"{tfr_p:.1f}%", f"-{int((tfr['TFR_met']=='Breached').sum())} breached", "inverse")
    s3.metric("Avg Sat", f"{s_avg:.2f}/5", f"{int(all_time_sat_count)} all-time ratings")
    s4.metric("5-Star", f"{int((sat['Satisfaction']==5).sum())}", f"{100*int((sat['Satisfaction']==5).sum())/len(sat):.1f}%" if len(sat) else "0%")

    def gauge(v, t, mx=100, c="#00CC96"): return go.Figure(go.Indicator(mode="gauge+number+delta" if mx==100 else "gauge+number", value=v, title={"text":t}, number={"suffix":"/5" if mx==5 else "%"}, delta={"reference":80} if mx==100 else None, gauge={"axis":{"range":[0 if mx==100 else 1, mx]},"bar":{"color":c},"threshold":{"line":{"color":"orange","width":3},"value":80 if mx==100 else 4}}))
    
    o1, o2, o3, o4 = st.columns(4)
    with o1: pc(gauge(ttr_p, "Res SLA %", 100, "#00CC96" if ttr_p>=80 else "#EF553B"))
    with o2: pc(gauge(tfr_p, "FR SLA %", 100, "#00CC96" if tfr_p>=80 else "#EF553B"))
    with o3: pc(gauge(s_avg, "Avg Score", 5, "#636EFA"))
    with o4:
        st.subheader("Satisfaction")
        if len(sat): nl(px.bar(sat["Satisfaction"].value_counts().reset_index(name="C").assign(L=lambda x: x["Satisfaction"].astype(int).astype(str)+" ⭐"), x="L", y="C", color="Satisfaction", color_continuous_scale=[[0, "#EF553B"], [0.5, "#FECB52"], [1.0, "#00CC96"]]).update_layout(coloraxis_showscale=False, xaxis_title="", yaxis_title=""))

    st.divider()
    c1, c2 = st.columns(2)
    with c1: nl(px.bar(df["Status"].value_counts().reset_index(name="C"), x="C", y="Status", orientation="h", color="Status", color_discrete_map=C_MAP, text="C", title="By Status"), True)
    with c2: pc(px.pie(df["Priority"].value_counts().reset_index(name="C"), names="Priority", values="C", hole=.45, color="Priority", color_discrete_map=PCOL, title="By Priority").update_traces(textinfo="label+percent+value"))

    r1, r2 = st.columns(2)
    with r1: pc(px.pie(df["Resolution"].fillna("Unresolved").value_counts().reset_index(name="C"), names="Resolution", values="C", hole=.45, title="Resolutions").update_traces(textinfo="label+percent+value"))
    with r2:
        m1, m2 = df.groupby("YearMonth").size().reset_index(name="C"), df[df["Resolved_dt"].notna()].copy()
        cb = m1.merge(m2.assign(RM=m2["Resolved_dt"].dt.to_period("M").astype(str)).groupby("RM").size().reset_index(name="R"), left_on="YearMonth", right_on="RM", how="left").fillna(0)
        f = go.Figure().add_trace(go.Scatter(x=cb["YearMonth"], y=cb["C"], name="Created", line=dict(color="#636EFA"))).add_trace(go.Scatter(x=cb["YearMonth"], y=cb["R"], name="Resolved", line=dict(color="#00CC96")))
        pc(f.update_layout(title="Monthly Volume", xaxis_tickangle=-45, legend=dict(orientation="h",y=1.1)))

with t2:
    rt = df["Request Type"].value_counts().reset_index(name="C").sort_values("C")
