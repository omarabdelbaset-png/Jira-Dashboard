import streamlit as st, pandas as pd, numpy as np, plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from jira import JIRA
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Jira SVF Dashboard", layout="wide")
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
            for i in j.enhanced_search_issues('project=SVF ORDER BY created DESC', maxResults=False, fields=','.join(flds)):
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

with st.spinner("Downloading updates..."): df_raw, live, err = load()
if df_raw.empty: st.error(f"Error: {err}"); st.stop()

st.sidebar.title("⚡ Data Controls")
if st.sidebar.button("🔄 Force Live Sync"):
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
if live: st.sidebar.success(f"🟢 Live Data Active\n{len(df_raw)} tickets.")
else: st.sidebar.warning(f"🟡 Offline CSV\n{err or ''}")

def ms(col): return st.sidebar.multiselect(col, sorted(df_raw[col].dropna().unique()), default=sorted(df_raw[col].dropna().unique()))
ss, sp, si, sa = ms("Status"), ms("Priority"), ms("Issue Type"), ms("Assignee")
d_min, d_max = (df_raw["Created_dt"].min().date(), df_raw["Created_dt"].max().date()) if not df_raw["Created_dt"].isna().all() else (pd.Timestamp.now().date(), pd.Timestamp.now().date())
dr = st.sidebar.date_input("Date Range", [d_min, d_max], min_value=d_min, max_value=d_max)
if len(dr)==1: dr=(dr[0],dr[0])

df = df_raw[df_raw["Status"].isin(ss) & df_raw["Priority"].isin(sp) & df_raw["Issue Type"].isin(si) & df_raw["Assignee"].isin(sa) & (df_raw["Created_dt"].dt.date >= dr[0]) & (df_raw["Created_dt"].dt.date <= dr[1])]

st.title("📊 Jira Service Desk Dashboard")
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
    s3.metric("Avg Sat", f"{s_avg:.2f}/5", f"{len(sat)} ratings")
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
    nl(px.bar(rt.tail(20), x="C", y="Request Type", orientation="h", color="C", color_continuous_scale="Blues", text="C", title="Request Types"), True)
    c1, c2 = st.columns(2)
    p_ord = [x for x in ["Critical","High","Medium","Low"] if x in df["Priority"].unique()]
    with c1: pc(px.imshow(df.groupby(["Priority","Status"]).size().unstack(fill_value=0).reindex(p_ord), text_auto=True, color_continuous_scale="YlOrRd", aspect="auto", title="Priority × Status"))
    with c2: pc(px.imshow(df.groupby(["Issue Type","Priority"]).size().unstack(fill_value=0), text_auto=True, color_continuous_scale="Blues", aspect="auto", title="Issue Type × Priority"))
    c3, c4 = st.columns(2)
    with c3: nl(px.bar(df["DayOfWeek"].value_counts().reindex(["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]).fillna(0).reset_index(name="C"), x="DayOfWeek", y="C", color="C", color_continuous_scale="Purples", text="C", title="By Day").update_layout(coloraxis_showscale=False), True)
    with c4: nl(px.bar(df["Hour"].value_counts().sort_index().reset_index(name="C"), x="Hour", y="C", color="C", color_continuous_scale="Teal", text="C", title="By Hour").update_layout(coloraxis_showscale=False))
    if "Status Category" in df.columns: pc(px.area(df.groupby(["YearMonth","Status Category"]).size().reset_index(name="C"), x="YearMonth", y="C", color="Status Category", color_discrete_map={"Done":"#00CC96","In Progress":"#FFA15A","To Do":"#636EFA"}, title="Status Category Trend").update_layout(xaxis_tickangle=-45))

def s_bar(d, m, t):
    p = d.groupby(["Priority", m]).size().reset_index(name="C").pivot(index="Priority", columns=m, values="C").fillna(0).reset_index().set_index("Priority").reindex(p_ord).reset_index()
    f = go.Figure()
    if "Met" in p: f.add_trace(go.Bar(name="Met", x=p["Priority"], y=p["Met"], marker_color="#00CC96", text=p["Met"].astype(int), textposition="inside"))
    if "Breached" in p: f.add_trace(go.Bar(name="Breached", x=p["Priority"], y=p["Breached"], marker_color="#EF553B", text=p["Breached"].astype(int), textposition="inside"))
    pc(f.update_layout(title=t, barmode="stack", legend=dict(orientation="h",y=1.1)))

def s_trnd(d, m, t, c):
    d["Mo"] = d["Created_dt"].dt.to_period("M").astype(str)
    mg = d.groupby("Mo")[m].apply(lambda x: 100*(x=="Met").sum()/len(x)).reset_index(name="P").merge(d.groupby("Mo").size().reset_index(name="C"), on="Mo")
    f = make_subplots(specs=[[{"secondary_y":True}]])
    f.add_trace(go.Bar(x=mg["Mo"], y=mg["C"], name="Tickets", marker_color="#c7e8c7" if c=="#00CC96" else "#f5c6c6", opacity=0.6), secondary_y=False)
    f.add_trace(go.Scatter(x=mg["Mo"], y=mg["P"], mode="lines+markers", name="Met %", line=dict(color=c)), secondary_y=True)
    f.add_hline(y=80, line_dash="dash", line_color="orange", annotation_text="80% target", secondary_y=True)
    pc(f.update_layout(title=t, xaxis_tickangle=-45, legend=dict(orientation="h",y=1.1)))

def s_brc(d, m, gc, t, c):
    nl(px.bar(d[d[m]=="Breached"].groupby(gc).size().sort_values().tail(15).reset_index(name="B"), x="B", y=gc, orientation="h", color="B", color_continuous_scale=c, text="B", title=t).update_layout(coloraxis_showscale=False), True)

with t3:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("FR SLA Met", f"{tfr_p:.1f}%"); c2.metric("FR SLA Breached", f"{100*(tfr['TFR_met']=='Breached').mean() if len(tfr) else 0:.1f}%", delta_color="inverse")
    c3.metric("Res SLA Met", f"{ttr_p:.1f}%"); c4.metric("Res SLA Breached", f"{100*(ttr['TTR_met']=='Breached').mean() if len(ttr) else 0:.1f}%", delta_color="inverse")
    c5.metric("Avg Act FR", f"{df.get('Act_TFR', pd.Series([0])).clip(lower=0).median():.1f} hrs" if "Act_TFR" in df else "N/A")
    c6.metric("Avg Act Res", f"{df.get('Act_Res', pd.Series([0])).clip(lower=0).median():.1f} hrs" if "Act_Res" in df else "N/A")
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: pc(px.pie(tfr["TFR_met"].value_counts().reset_index(name="C"), names="TFR_met", values="C", hole=.5, color="TFR_met", color_discrete_map={"Met":"#00CC96","Breached":"#EF553B"}, title="FR SLA Met vs Breached").update_traces(pull=[0.05,0]))
    with c2: pc(px.pie(ttr["TTR_met"].value_counts().reset_index(name="C"), names="TTR_met", values="C", hole=.5, color="TTR_met", color_discrete_map={"Met":"#00CC96","Breached":"#EF553B"}, title="Res SLA Met vs Breached").update_traces(pull=[0.05,0]))
    
    c3, c4 = st.columns(2)
    with c3: s_bar(tfr, "TFR_met", "FR SLA by Priority")
    with c4: s_bar(ttr, "TTR_met", "Res SLA by Priority")
    
    c5, c6 = st.columns(2)
    with c5: s_trnd(tfr, "TFR_met", "FR SLA % Met Trend", "#00CC96")
    with c6: s_trnd(ttr, "TTR_met", "Res SLA % Met Trend", "#636EFA")
    
    c7, c8 = st.columns(2)
    with c7: s_brc(tfr, "TFR_met", "Assignee", "FR Breaches by Assignee", "Reds")
    with c8: s_brc(ttr, "TTR_met", "Assignee", "Res Breaches by Assignee", "Oranges")
    
    c9, c10 = st.columns(2)
    with c9: s_brc(tfr, "TFR_met", "Request Type", "FR Breaches by Req Type", "Reds")
    with c10: s_brc(ttr, "TTR_met", "Request Type", "Res Breaches by Req Type", "Oranges")

    if "Act_Res" in df and len(df[df["Act_Res"]>0]):
        rc = df[df["Act_Res"]>0]
        rc = rc[rc["Act_Res"] <= rc["Act_Res"].quantile(0.95)]
        ca, cb = st.columns(2)
        with ca: pc(px.histogram(rc, x="Act_Res", nbins=50, color_discrete_sequence=["#636EFA"], title="Act Res Time Dist (hrs)"))
        with cb: nl(px.box(rc[rc["Priority"].notna()], x="Priority", y="Act_Res", color="Priority", color_discrete_map=PCOL, title="Res Time by Priority"))

    with st.expander("🔎 View Breached Tickets"):
        b_d = tfr[tfr["TFR_met"]=="Breached"] if st.radio("Type", ["FR", "Res"], horizontal=True)=="FR" else ttr[ttr["TTR_met"]=="Breached"]
        st.dataframe(b_d[["Issue key","Summary","Status","Priority","Assignee","Created"]].sort_values("Created", ascending=False), use_container_width=True, hide_index=True)

with t4:
    if len(sat):
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Sat", f"{s_avg:.2f} / 5"); c2.metric("Ratings", f"{len(sat):,}"); c3.metric("5-Star", f"{int((sat['Satisfaction']==5).sum())} ({100*(sat['Satisfaction']==5).mean():.1f}%)")
        ca, cb = st.columns(2)
        with ca: nl(px.bar(sat["Satisfaction"].value_counts().sort_index().reset_index(name="C").assign(L=lambda x: x["Satisfaction"].astype(int).astype(str)+" ⭐"), x="L", y="C", color="Satisfaction", color_continuous_scale=[[0, "#EF553B"], [0.25, "#FFA15A"], [0.5, "#FECB52"], [0.75, "#00CC96"], [1.0, "#19d3f3"]], text="C", title="Score Dist").update_layout(coloraxis_showscale=False), True)
        with cb:
            sm = sat.groupby("YearMonth")["Satisfaction"].agg(["mean","count"]).reset_index()
            f = make_subplots(specs=[[{"secondary_y":True}]])
            f.add_trace(go.Bar(x=sm["YearMonth"], y=sm["count"], name="# Ratings", marker_color="#c7d7f5"), secondary_y=False)
            f.add_trace(go.Scatter(x=sm["YearMonth"], y=sm["mean"], mode="lines+markers", name="Avg Score", line=dict(color="#636EFA")), secondary_y=True)
            pc(f.update_layout(title="Sat Over Time", xaxis_tickangle=-45))
        c3, c4 = st.columns(2)
        with c3: nl(px.bar(sat.groupby("Priority")["Satisfaction"].mean().reset_index(name="A"), x="Priority", y="A", color="Priority", color_discrete_map=PCOL, text=np.round(sat.groupby("Priority")["Satisfaction"].mean().values,2), title="CSAT by Priority", range_y=[1,5]), True)
        with c4: nl(px.bar(sat.groupby("Request Type")["Satisfaction"].agg(["mean","count"]).reset_index().query("count>=3").sort_values("mean").tail(10), x="mean", y="Request Type", orientation="h", color="mean", color_continuous_scale="RdYlGn", text=np.round(sat.groupby("Request Type")["Satisfaction"].agg(["mean","count"]).reset_index().query("count>=3").sort_values("mean").tail(10)["mean"].values,2), title="CSAT by Req Type (top 10)", range_x=[1,5]).update_layout(coloraxis_showscale=False))
        nl(px.bar(sat.groupby("Assignee")["Satisfaction"].agg(["mean","count"]).reset_index().query("count>=3").sort_values("mean").tail(15), x="mean", y="Assignee", orientation="h", color="mean", color_continuous_scale="RdYlGn", text=np.round(sat.groupby("Assignee")["Satisfaction"].agg(["mean","count"]).reset_index().query("count>=3").sort_values("mean").tail(15)["mean"].values,2), title="Avg CSAT by Assignee", range_x=[1,5]).update_layout(coloraxis_showscale=False))
    else: st.info("No sat data")

with t5:
    c1, c2 = st.columns(2)
    with c1: pc(px.area(df.groupby("Week").size().reset_index(name="C"), x="Week", y="C", color_discrete_sequence=["#a6a6ff"], title="Weekly Volume").update_layout(xaxis_tickangle=-45))
    with c2: nl(px.bar(df.groupby("Year").size().reset_index(name="C"), x="Year", y="C", color="Year", color_continuous_scale="Viridis", text="C", title="By Year").update_layout(coloraxis_showscale=False), True)

    pc(px.line(df.groupby(["YearMonth", "Priority"]).size().reset_index(name="C"), x="YearMonth", y="C", color="Priority", color_discrete_map=PCOL, markers=True, title="Priority Trend").update_layout(xaxis_tickangle=-45, legend=dict(orientation="h", y=1.1)))
    pc(px.imshow(df.groupby(["DayOfWeek", "Hour"]).size().unstack(fill_value=0).reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]), text_auto=True, color_continuous_scale="YlOrRd", aspect="auto", title="Day × Hour Heatmap"))
    
    c_df = df.sort_values("Created_dt").dropna(subset=["Created_dt"]).copy()
    c_df["Cum"] = range(1, len(c_df) + 1)
    pc(px.area(c_df, x="Created_dt", y="Cum", color_discrete_sequence=["#82e0bc"], title="Cumulative Tickets"))

    st.divider()
    r1, r2 = st.columns([3, 1])
    with r1: st.subheader("📋 Raw Data")
    
    sr = st.text_input("Search Summary")
    dp = df[df["Summary"].fillna("").str.contains(sr, case=False)] if sr else df
    cs = st.multiselect("Cols", ["Summary", "Issue key", "Status", "Priority", "Assignee", "Reporter", "Created", "Resolution", "Request Type"], default=["Summary", "Issue key", "Status", "Priority", "Assignee", "Reporter", "Created", "Resolution"])
    
    with r2:
        st.write("") 
        st.download_button("📥 Download Data", data=dp[cs].sort_values("Created", ascending=False).to_csv(index=False).encode('utf-8'), file_name="jira_export.csv", mime="text/csv", use_container_width=True)

    st.dataframe(dp[cs].sort_values("Created", ascending=False).head(1000), use_container_width=True, hide_index=True)
    st.caption(f"Showing up to 1,000 of {len(dp):,} matching records")
