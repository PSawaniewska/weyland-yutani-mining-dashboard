import plotly.graph_objects as go
import streamlit as st

from analysis import TESTS, find_anomalies, load_data, run_tests, summary_table, trendline
from report import build_report

# industrial palette shared by the theme and the Plotly charts
PALETTE = ["#F2A93B", "#4FB3BF", "#9AA5B1", "#C8693E", "#7DB87A"]
ANOMALY = "#E5533D"

st.set_page_config(page_title="Mining Ops Dashboard", page_icon=":material/precision_manufacturing:", layout="wide")


# the sheet changes whenever someone edits it, so the data is re-read at most once a minute
@st.cache_data(ttl=60)
def get_data():
    return load_data()


with st.sidebar:
    st.markdown("## :material/precision_manufacturing: Mining Ops")
    st.caption("Control panel")
    if st.button("Refresh data", icon=":material/refresh:", width="stretch"):
        st.cache_data.clear()

    st.subheader(":material/troubleshoot: Anomaly tests")
    params = {
        "weekly_adjust": st.toggle("Remove weekly pattern before testing", value=True),
        "iqr_k": st.slider("IQR rule: k", 1.0, 3.0, 1.5, 0.1),
        "z_threshold": st.slider("Z-score: threshold", 1.5, 4.0, 2.5, 0.1),
        "ma_window": st.slider("Moving average: window (days)", 3, 21, 7, 2),
        "ma_percent": st.slider("Moving average: max distance (%)", 10, 100, 30, 5),
        "grubbs_alpha": st.select_slider("Grubbs: significance level", [0.01, 0.025, 0.05, 0.1], 0.05),
    }

    st.subheader(":material/monitoring: Chart")
    chart_type = st.radio("Type", ["Line", "Bar", "Stacked"], horizontal=True)
    degree = st.select_slider("Trendline degree", [1, 2, 3, 4], 1)
    highlight = st.selectbox("Highlight anomalies from", ["Any test"] + TESTS)

df = get_data()
mines = [col for col in df.columns if col != "Total"]
flags = {name: run_tests(df[name], params) for name in df.columns}
stats_table = summary_table(df, flags)
anomalies = find_anomalies(df, flags)
# the total keeps the accent colour, each mine gets its own
color_of = {"Total": PALETTE[0]} | dict(zip(mines, PALETTE[1:]))

st.title("Weyland-Yutani Mining Operations")
st.caption(f"{df.index.min():%d %b %Y} to {df.index.max():%d %b %Y}  ·  {len(df)} days  ·  {len(mines)} mines")

tab_stats, tab_charts, tab_anomalies = st.tabs([
    ":material/table_chart: Statistics", ":material/show_chart: Charts", ":material/warning: Anomalies"
])

with tab_stats:
    st.dataframe(
        stats_table,
        column_config={col: st.column_config.NumberColumn(format="%.2f") for col in ["Mean", "Std dev", "Median", "IQR"]}
        | {test: st.column_config.NumberColumn(f"{test} (count)", format="%d") for test in TESTS},
    )

with tab_charts:
    fig = go.Figure()
    if chart_type == "Stacked":
        selected = st.multiselect("Mines", mines, default=mines)
        for name in selected:
            fig.add_bar(x=df.index, y=df[name], name=name, marker_color=color_of[name])
        # trend and anomalies are shown for the stacked total
        analysed = {"Total": df[selected].sum(axis=1)} if selected else {}
    else:
        selected = st.multiselect("Series", list(df.columns), default=["Total"])
        for name in selected:
            if chart_type == "Line":
                fig.add_scatter(x=df.index, y=df[name], mode="lines", name=name, line_color=color_of[name])
            else:
                fig.add_bar(x=df.index, y=df[name], name=name, marker_color=color_of[name])
        analysed = {name: df[name] for name in selected}

    for name, series in analysed.items():
        tests = run_tests(series, params)
        flagged = tests.any(axis=1) if highlight == "Any test" else tests[highlight]
        fig.add_scatter(x=series.index, y=trendline(series, degree), mode="lines", name=f"{name} trend",
                        line=dict(color=color_of[name], dash="dash"))
        fig.add_scatter(x=series.index[flagged], y=series[flagged], mode="markers", name=f"{name} anomalies",
                        marker=dict(color=ANOMALY, size=10, symbol="x"))

    fig.update_layout(barmode="stack" if chart_type == "Stacked" else "group", height=520,
                      margin=dict(t=20, b=20), legend=dict(orientation="h"), hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

with tab_anomalies:
    if anomalies.empty:
        st.info("No anomalies found with the current parameters.")
    else:
        st.dataframe(
            anomalies,
            hide_index=True,
            column_config={
                "Start": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "End": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Peak value": st.column_config.NumberColumn(format="%.1f"),
                "Median": st.column_config.NumberColumn(format="%.1f"),
                "Change vs median (%)": st.column_config.NumberColumn(format="%+.1f%%"),
            },
        )

if st.button("Generate PDF report", icon=":material/picture_as_pdf:", type="primary"):
    with st.spinner("Building the report..."):
        pdf = build_report(df, flags, stats_table, anomalies, params, degree)
    st.download_button("Download report", pdf, file_name="mining_report.pdf", mime="application/pdf")
