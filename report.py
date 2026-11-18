from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from fpdf import FPDF
from fpdf.fonts import FontFace
from matplotlib import font_manager
from pandas import Timedelta
from PIL import Image

from analysis import TESTS, trendline

# same industrial palette as the app theme
BG = (21, 24, 28)
PANEL = (32, 37, 43)
ROW_ALT = (27, 31, 36)
LINE = (46, 53, 61)
TEXT = (232, 227, 216)
MUTED = (154, 165, 177)
AMBER = (242, 169, 59)
RED = (229, 83, 61)
TEAL = (79, 179, 191)
SERIES_COLORS = ["#F2A93B", "#4FB3BF", "#9AA5B1", "#C8693E", "#7DB87A"]

FONTS = Path(__file__).parent / "fonts"
for font in FONTS.glob("*.ttf"):
    font_manager.fontManager.addfont(str(font))
plt.rcParams.update({
    "font.family": "IBM Plex Sans",
    "figure.facecolor": "#15181C", "axes.facecolor": "#15181C",
    "axes.edgecolor": "#2E353D", "axes.labelcolor": "#9AA5B1",
    "xtick.color": "#9AA5B1", "ytick.color": "#9AA5B1", "text.color": "#E8E3D8",
    "grid.color": "#2E353D", "axes.spines.top": False, "axes.spines.right": False,
})


def hex_color(rgb):
    return "#" + "".join(f"{value:02X}" for value in rgb)


class Report(FPDF):
    def __init__(self):
        super().__init__()
        # embedded fonts, so the report looks the same on every computer
        self.add_font("Oswald", "", FONTS / "Oswald-SemiBold.ttf")
        self.add_font("Plex", "", FONTS / "IBMPlexSans-Regular.ttf")
        self.add_font("Plex", "B", FONTS / "IBMPlexSans-SemiBold.ttf")
        self.add_font("Mono", "", FONTS / "IBMPlexMono-Regular.ttf")
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)

    def header(self):
        # dark background on every page, like the dashboard
        self.set_fill_color(*BG)
        self.rect(0, 0, self.w, self.h, style="F")
        if self.page_no() == 1:
            return
        self.set_font("Plex", size=7)
        self.set_text_color(*MUTED)
        self.set_y(9)
        self.cell(0, 5, "WEYLAND-YUTANI CORPORATION  /  MINING OPERATIONS REPORT")
        self.set_draw_color(*AMBER)
        self.set_line_width(0.4)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)
        self.set_y(22)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Mono", size=7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"PAGE {self.page_no()} / {{nb}}", align="R")

    def ensure_space(self, height):
        # a new page only when the next block would not fit, so pages are filled before breaking
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def section(self, number, title, keep=70):
        # keep the heading together with the start of its content
        self.ensure_space(keep)
        self.set_font("Oswald", size=18)
        self.set_text_color(*AMBER)
        self.cell(12, 10, f"{number:02d}")
        self.set_text_color(*TEXT)
        self.cell(0, 10, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def text_block(self, text, color=TEXT, size=9.5):
        self.set_font("Plex", size=size)
        self.set_text_color(*color)
        self.multi_cell(0, 5.5, text, new_x="LMARGIN", new_y="NEXT")

    def kpi_cards(self, items, y, weights, height=24):
        gap = 4
        unit = (self.w - self.l_margin - self.r_margin - gap * (len(items) - 1)) / sum(weights)
        x = self.l_margin
        for (label, value), weight in zip(items, weights):
            width = unit * weight
            self.set_fill_color(*PANEL)
            self.rect(x, y, width, height, style="F")
            self.set_fill_color(*AMBER)
            self.rect(x, y, 1.2, height, style="F")
            self.set_xy(x + 5, y + 4)
            self.set_font("Plex", size=7)
            self.set_text_color(*MUTED)
            self.cell(width - 8, 4, label.upper())
            self.set_xy(x + 5, y + 10)
            self.set_font("Oswald", size=15)
            self.set_text_color(*TEXT)
            self.cell(width - 8, 9, value)
            x += width + gap

    def data_table(self, header, rows, col_widths=None):
        heading = FontFace(family="Plex", emphasis="BOLD", size_pt=8, color=AMBER, fill_color=PANEL)
        self.set_font("Mono", size=8)
        self.set_text_color(*TEXT)
        self.set_draw_color(*LINE)
        # the table fills alternate rows with the current fill colour
        self.set_fill_color(*ROW_ALT)
        with self.table(col_widths=col_widths, headings_style=heading, borders_layout="HORIZONTAL_LINES",
                        cell_fill_color=ROW_ALT, cell_fill_mode="ROWS", text_align="CENTER",
                        line_height=7, padding=1) as table:
            table.row(header)
            for row in rows:
                table.row([str(value) for value in row])
        self.ln(5)

    def tag(self, text, color):
        self.set_font("Plex", "B", 7)
        self.set_fill_color(*color)
        self.set_text_color(*BG)
        self.cell(self.get_string_width(text) + 6, 6, text, align="C", fill=True)

    def chart(self, fig, width=174):
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=170, bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        pixels_wide, pixels_high = Image.open(buffer).size
        self.ensure_space(width * pixels_high / pixels_wide)
        buffer.seek(0)
        self.image(buffer, w=width)
        self.ln(3)


def series_chart(series, flags, degree, title, color, zoom=None):
    fig, ax = plt.subplots(figsize=(10, 2.0))
    shown = series if zoom is None else series.loc[zoom[0]:zoom[1]]
    shown_flags = flags.loc[shown.index]

    ax.plot(shown.index, shown, color=color, linewidth=1.5, label="Output")
    if zoom is None:
        ax.plot(series.index, trendline(series, degree), color=hex_color(TEXT), alpha=0.6,
                linestyle="--", linewidth=1.2, label=f"Trend (degree {degree})")
    ax.scatter(shown.index[shown_flags], shown[shown_flags], color=hex_color(RED),
               marker="x", zorder=3, s=40, linewidths=2, label="Anomaly")

    ax.set_title(title.upper(), fontsize=10, loc="left", color=hex_color(MUTED))
    ax.grid(axis="y", linewidth=0.6)
    ax.legend(fontsize=8, loc="upper left", frameon=False, ncol=3)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    return fig


def build_report(df, flags, stats_table, anomalies, params, degree):
    pdf = Report()
    mines = [col for col in df.columns if col != "Total"]
    color_of = {"Total": SERIES_COLORS[0]} | dict(zip(mines, SERIES_COLORS[1:]))

    # cover page
    pdf.add_page()
    pdf.set_fill_color(*AMBER)
    pdf.rect(0, 0, 6, pdf.h, style="F")
    pdf.set_xy(pdf.l_margin, 70)
    pdf.set_font("Plex", "B", 9)
    pdf.set_text_color(*AMBER)
    pdf.cell(0, 6, "MINING OPERATIONS REPORT", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Oswald", size=38)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(0, 16, "WEYLAND-YUTANI\nCORPORATION", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.text_block(f"Mines: {', '.join(mines)}", color=MUTED, size=10)
    pdf.kpi_cards([
        ("Period", f"{df.index.min():%d %b %Y} - {df.index.max():%d %b %Y}"),
        ("Days", str(len(df))),
        ("Anomalies", str(len(anomalies))),
    ], y=150, weights=(3, 1, 1))
    pdf.set_xy(pdf.l_margin, pdf.h - 30)
    pdf.set_font("Mono", size=8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, f"GENERATED {datetime.now():%d %b %Y, %H:%M}".upper())

    # statistics
    pdf.add_page()
    pdf.section(1, "Summary statistics")
    rows = [[name] + [f"{stats_table.loc[name, col]:.2f}" for col in ["Mean", "Std dev", "Median", "IQR"]]
            for name in stats_table.index]
    pdf.data_table(["Series", "Mean", "Std dev", "Median", "IQR"], rows)

    pdf.section(2, "Anomaly detection")
    if params["weekly_adjust"]:
        pdf.text_block("The weekly pattern was removed before testing, so regular weekend drops are not counted as anomalies.",
                       color=MUTED)
        pdf.ln(2)
    pdf.text_block(
        f"IQR rule: outside Q1 - {params['iqr_k']} x IQR and Q3 + {params['iqr_k']} x IQR.\n"
        f"Z-score: more than {params['z_threshold']} standard deviations from the mean.\n"
        f"Moving average: more than {params['ma_percent']}% away from the "
        f"{params['ma_window']}-day centered moving average.\n"
        f"Grubbs' test: repeated two-sided test, significance level {params['grubbs_alpha']}."
    )
    pdf.ln(3)
    rows = [[name] + [int(stats_table.loc[name, test]) for test in TESTS] for name in stats_table.index]
    pdf.data_table(["Series"] + TESTS, rows)

    # sections follow each other on the same page while there is room
    pdf.section(3, "Charts")
    for name in ["Total"] + mines:
        pdf.chart(series_chart(df[name], flags[name].any(axis=1), degree, name, color_of[name]))

    # one block per anomaly
    pdf.section(4, "Anomalies", keep=85)
    if anomalies.empty:
        pdf.text_block("No anomalies were found with the current parameters.")

    for i, event in anomalies.iterrows():
        # the title, table and chart of one anomaly stay on the same page
        pdf.ensure_space(78)
        period = f"{event['Start']:%d %b %Y}"
        if event["Days"] > 1:
            period += f" - {event['End']:%d %b %Y}"
        pdf.tag(event["Type"].upper(), AMBER if event["Type"] == "Spike" else RED)
        pdf.set_font("Oswald", size=12)
        pdf.set_text_color(*TEXT)
        pdf.cell(0, 6, f"   ANOMALY {i + 1}  /  {event['Series']}  /  {period}".upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.data_table(
            ["Duration", "Peak value", "Median", "Change", "Detected by"],
            [[f"{event['Days']} day(s)", f"{event['Peak value']:.1f}", f"{event['Median']:.1f}",
              f"{event['Change vs median (%)']:+.1f}%", event["Detected by"]]],
            col_widths=(20, 20, 20, 20, 60),
        )
        name = event["Series"]
        zoom = (event["Start"] - Timedelta(days=7), event["End"] + Timedelta(days=7))
        pdf.chart(series_chart(df[name], flags[name].any(axis=1), degree, f"{name} around the anomaly",
                               color_of[name], zoom), width=140)

    return bytes(pdf.output())
