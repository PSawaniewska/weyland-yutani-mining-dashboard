from datetime import datetime
from io import BytesIO

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from fpdf import FPDF
from fpdf.fonts import FontFace
from pandas import Timedelta

from analysis import TESTS, trendline

# same cyan shades as the generator spreadsheet
DARK = (19, 79, 92)
LIGHT = (208, 224, 227)


class Report(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 6, "Weyland-Yutani Corporation - Mining Operations Report", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 6, f"Page {self.page_no()}", align="C")

    def section(self, title):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*DARK)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*DARK)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)
        self.set_text_color(0)

    def text_line(self, text):
        self.set_font("Helvetica", size=10)
        self.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

    def data_table(self, header, rows, col_widths=None):
        self.set_font("Helvetica", size=9)
        heading = FontFace(emphasis="BOLD", color=255, fill_color=DARK)
        with self.table(col_widths=col_widths, headings_style=heading,
                        cell_fill_color=LIGHT, cell_fill_mode="ROWS",
                        text_align="CENTER", line_height=6) as table:
            table.row(header)
            for row in rows:
                table.row([str(value) for value in row])
        self.ln(4)

    def chart(self, fig, width=180):
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        self.image(buffer, w=width)
        self.ln(3)


def series_chart(series, flags, degree, title, zoom=None):
    fig, ax = plt.subplots(figsize=(10, 2.5))
    shown = series if zoom is None else series.loc[zoom[0]:zoom[1]]
    shown_flags = flags.loc[shown.index]

    ax.plot(shown.index, shown, color="#45818E", linewidth=1.4, label="Output")
    if zoom is None:
        ax.plot(series.index, trendline(series, degree), color="#F79646",
                linestyle="--", linewidth=1.6, label=f"Trend (degree {degree})")
    ax.scatter(shown.index[shown_flags], shown[shown_flags], color="#C0504D",
               zorder=3, s=30, label="Anomaly")

    ax.set_title(title, fontsize=11, loc="left")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    return fig


def build_report(df, flags, stats_table, anomalies, params, degree):
    pdf = Report()
    pdf.set_auto_page_break(auto=True, margin=15)

    # cover page
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 12, "Weyland-Yutani Corporation", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 16)
    pdf.cell(0, 10, "Mining Operations Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(15)
    pdf.set_text_color(0)
    pdf.set_font("Helvetica", "", 11)
    mines = [col for col in df.columns if col != "Total"]
    for line in [
        f"Period: {df.index.min():%Y-%m-%d} to {df.index.max():%Y-%m-%d} ({len(df)} days)",
        f"Mines: {', '.join(mines)}",
        f"Anomalies found: {len(anomalies)}",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
    ]:
        pdf.cell(0, 8, line, align="C", new_x="LMARGIN", new_y="NEXT")

    # statistics
    pdf.add_page()
    pdf.section("1. Summary statistics")
    rows = [[name] + [f"{stats_table.loc[name, col]:.2f}" for col in ["Mean", "Std dev", "Median", "IQR"]]
            for name in stats_table.index]
    pdf.data_table(["Series", "Mean", "Std dev", "Median", "IQR"], rows)

    pdf.section("2. Anomaly detection")
    if params["weekly_adjust"]:
        pdf.text_line("The weekly pattern was removed before testing, so regular weekend drops are not counted as anomalies.")
        pdf.ln(1)
    pdf.text_line(
        f"IQR rule: outside Q1 - {params['iqr_k']} x IQR and Q3 + {params['iqr_k']} x IQR.\n"
        f"Z-score: more than {params['z_threshold']} standard deviations from the mean.\n"
        f"Moving average: more than {params['ma_percent']}% away from the "
        f"{params['ma_window']}-day centered moving average.\n"
        f"Grubbs' test: repeated two-sided test, significance level {params['grubbs_alpha']}."
    )
    pdf.ln(2)
    rows = [[name] + [int(stats_table.loc[name, test]) for test in TESTS] for name in stats_table.index]
    pdf.data_table(["Series"] + TESTS, rows)

    # charts
    pdf.add_page()
    pdf.section("3. Charts")
    for name in ["Total"] + [col for col in df.columns if col != "Total"]:
        pdf.chart(series_chart(df[name], flags[name].any(axis=1), degree, name), width=170)

    # one section per anomaly
    pdf.add_page()
    pdf.section("4. Anomalies")
    if anomalies.empty:
        pdf.text_line("No anomalies were found with the current parameters.")

    for i, event in anomalies.iterrows():
        # start a new page if the table and its chart would not fit
        if pdf.get_y() > 180:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*DARK)
        period = f"{event['Start']:%Y-%m-%d}"
        if event["Days"] > 1:
            period += f" to {event['End']:%Y-%m-%d}"
        pdf.cell(0, 8, f"Anomaly {i + 1}: {event['Type']} in {event['Series']}, {period}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
        pdf.data_table(
            ["Duration", "Peak value", "Median", "Change", "Detected by"],
            [[f"{event['Days']} day(s)", f"{event['Peak value']:.1f}", f"{event['Median']:.1f}",
              f"{event['Change vs median (%)']:+.1f}%", event["Detected by"]]],
            col_widths=(20, 20, 20, 20, 60),
        )
        name = event["Series"]
        zoom = (event["Start"] - Timedelta(days=7), event["End"] + Timedelta(days=7))
        pdf.chart(series_chart(df[name], flags[name].any(axis=1), degree, f"{name} around the anomaly", zoom), width=150)

    return bytes(pdf.output())

