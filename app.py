import streamlit as st, pandas as pd, numpy as np, plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from jira import JIRA
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Jira SVF Dashboard", layout="wide")

# Auto-refresh every 1 minute (60,000 ms)
st_autorefresh(interval=60000, key="jira_refresh")

st.markdown('<style>.stMetric{background-color:#f8f9fa;border-radius:8px;padding:12px;} div[data-testid="metric-container"]{background-color:#f8f9fa;border:1px solid #e9ecef;border-radius:8px;padding:16px;}</style>', unsafe_allow_html=True)

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

# Cache expires at 55 seconds, so the 60-second auto-refresh always gets fresh data!
@st.cache_data(ttl=55)
def load():
    df, live, err = pd.DataFrame(), False, None
    if EM and TK:
        try:
            j = JIRA("https://itsupportsivision.atlassian.net", basic_auth=(EM, TK))
            afs = j.fields()
            def gid(ns): return next((f['id'] for f in afs if any(n in f['name'].lower() for n in ns)), None)
            f_tfr, f_ttr, f_sat, f_req = gid(['time to first response']), gid(['time to resolution']), gid(['satisfaction rating','satisfaction']), gid(['customer request type','portal request type','request type'])
            flds = ['status','priority','assignee','created','resolutiondate','updated','issuetype','resolution','reporter','summary','customfield_10010'] + [x for x in [f_tfr,f_ttr,f_sat,f_req] if x]
            d = []
            
            # Pull ALL historical tickets
            jql_query = 'project=SVF ORDER BY created DESC'
            
            for i in j.enhanced_search_issues(jql_query, maxResults=False, fields=','.join(flds)):
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
            df, live = pd.DataFrame(d), True
        except Exception as e: err = str(e)
    if not live and os.path.exists("Jira Service Desk (8).csv"): 
        df = pd.read_csv("Jira Service Desk (8).csv", low_memory=False)
        if "Custom field (Request Type).1" in df.columns: df["Request Type"] = df["Custom field (Request Type).1"].fillna("Unknown")
        df["TFR_raw"] = df.get("Custom field (Time to first response)", "")
        df["TTR_raw"] = df.get("Custom field (Time to resolution)", "")
        if "Satisfaction rating" in df.columns: df["Satisfaction"] = pd.to_numeric(df["Satisfaction rating"], errors="coerce")
    if not df.empty:
        for c in ["Created", "Resolved"]: df[f"{c}_dt"] = pd.to_datetime(df[c], format="%d/%b/%y %I:%M %p", errors="coerce")
        df["YearMonth"] = df["Created_dt"].dt.to_period("M").astype(str)
        df["Week"] = df["Created_dt"].dt.to_period("W").astype(str)
        df["DayOfWeek"] = df["Created_dt"].dt.day_name()
        df["Hour"] = df["Created_dt"].dt.hour
        df["Year"] = df["Created_dt"].dt.year
        df["TFR_m"], df["TTR_m"] = df["TFR_raw"].apply(p_hm), df["TTR_raw"].apply(p_hm)
        df["TFR_met"] = df["TFR_m"].apply(lambda x: "Met" if pd.notna(x) and x>=0 else ("Breached" if pd.notna(x) else None))
        df["TTR_met"] = df["TTR_m"].apply(lambda x: "Met" if pd.notna(x) and x>=0 else ("Breached" if pd.notna(x) else None))
        if df["Resolved_dt"].notna().any() and df["Created_dt"].notna().any(): df["Act_Res"] = (df["Resolved_dt"] - df["Created_dt"]).dt.total_seconds()/3600
    return df, live, err

with st.spinner("Downloading updates from Jira (Auto-Syncing)..."): df_raw, live, err = load()
if df_raw.empty: st.error(f"Error: {err}"); st.stop()

st.sidebar.title("⚡ Data Controls")
if st.sidebar.button("🔄 Force Live Sync", help="Click to pull the latest tickets instantly"):
    load.clear() 
    st.rerun()   

m0 = dict(l=0, r=0, t=30, b=0)
def pc(fig, out=False):
    if out: fig.update_traces(textposition="outside")
    st.plotly_chart(fig.update_layout(margin=m0), use_container_width=True)
def nl(fig, out=False):
    if out: fig.update_traces(textposition="outside")
    st.plotly_chart(fig.update_layout(showlegend=False, margin=m0), use_container_width=True)

st.sidebar.title("🔍 Filters")
if live: st.sidebar.success(f"🟢 Live Data Active\n{len(df_raw)} tickets synced.")
else: st.sidebar.warning(f"🟡 Offline CSV\n{err or ''}")

def ms(col): return st.sidebar.multiselect(col, sorted(df_raw[col].dropna().unique()), default=sorted(df_raw[col].dropna().unique()))
ss, sp, si, sa = ms("Status"), ms("Priority"), ms("Issue Type"), ms("Assignee")
d_min, d_max = (df_raw["Created_dt"].min().date(), df_raw["Created_dt"].max().date()) if not df_raw["Created_dt"].isna().all() else (pd.Timestamp.now().date(), pd.Timestamp.now().date())
dr = st.sidebar.
