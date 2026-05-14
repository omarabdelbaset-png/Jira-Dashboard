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
                    'Status Category': 'Done' if 'Done' in stt or 'Resolved' in stt else ('In Progress' if 'Progress' in stt
