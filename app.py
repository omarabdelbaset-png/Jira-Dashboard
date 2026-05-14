import streamlit as st, pandas as pd, numpy as np, plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from jira import JIRA
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Facilities Team Dashboard", layout="wide")
st_autorefresh(interval=60000, key="j_ref")
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
            
            for i in j.search_issues(jql, maxResults=1000, fields=','.join(flds)):
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
    # FIX: Set back to use live updates, but expanded to 60 days to bridge the gap from April 7th to today!
    return fetch_data('project=SVF AND updated >= -60d ORDER BY created DESC')

with st.spinner("Accessing History Data..."): df_v, err_v = load_vault()
with st.spinner("Syncing recent updates..."): df_l, err_l = load_live()

if err_l:
    st.error(f"🚨 JIRA API ERROR: {err_l}")

if df_v is not None and not df_v.empty and df_l is not None and not df_l.empty: df_raw = pd.concat([df_v, df_l]).drop_duplicates(subset=['Issue key'], keep='last')
elif df_l is not None and not df_l.empty: df_raw = df_l
elif df_v is not None and not df_v.empty: df_raw = df_v
else: st.error("Could not load data."); st.stop()

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
    st.plotly_chart(fig.update_layout(margin=m0), use_container_width=True)
def nl(fig, out=False):
    if out: fig.update_traces(textposition="outside")
    st.plotly_chart(fig.update_layout(showlegend=False, margin=m0), use_container_width=True)

st.sidebar.title("🔍 Filters")
def ms(col): return st.sidebar.multiselect(col, sorted(df_raw[col].dropna().unique()), default=sorted(df_raw[col].dropna().unique()))
ss, sp, si, sa = ms("Status"), ms("Priority"), ms("Issue Type"), ms("Assignee")
d_min, d_max = (df_raw["Created_dt"].min().date(), df_raw["Created_dt"].max().date()) if not df_raw["Created_dt"].isna().all() else (pd.Timestamp.now().date(), pd.Timestamp.now().date())
dr = st.sidebar.date_input("
