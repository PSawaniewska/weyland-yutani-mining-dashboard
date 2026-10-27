import numpy as np
import pandas as pd
from scipy import stats

CSV_URL = (
    "https://docs.google.com/spreadsheets/d/1FkrTgr1sRXpvhPpsQqCinUWLUbuzJiUEwYtTBpZno3Y"
    "/export?format=csv&gid=689029608"
)
TESTS = ["IQR rule", "Z-score", "Moving average", "Grubbs"]


def load_data(url=CSV_URL):
    df = pd.read_csv(url, parse_dates=["Date"], index_col="Date")
    df["Total"] = df.sum(axis=1)
    return df


def describe(series):
    q1, q3 = series.quantile([0.25, 0.75])
    return {"Mean": series.mean(), "Std dev": series.std(), "Median": series.median(), "IQR": q3 - q1}


def iqr_outliers(series, k):
    q1, q3 = series.quantile([0.25, 0.75])
    iqr = q3 - q1
    return (series < q1 - k * iqr) | (series > q3 + k * iqr)


def zscore_outliers(series, threshold):
    z = (series - series.mean()) / series.std()
    return z.abs() > threshold


def moving_average_outliers(series, window, percent):
    moving_avg = series.rolling(window, center=True, min_periods=1).mean()
    return (series - moving_avg).abs() / moving_avg * 100 > percent


def grubbs_outliers(series, alpha):
    # Grubbs' test finds one outlier at a time, so the most extreme value
    # is removed and the test is repeated until nothing is found
    values = series.copy()
    flagged = pd.Series(False, index=series.index)

    while len(values) > 2:
        n = len(values)
        deviation = (values - values.mean()).abs()
        t = stats.t.ppf(1 - alpha / (2 * n), n - 2)
        g_critical = (n - 1) / np.sqrt(n) * np.sqrt(t**2 / (n - 2 + t**2))
        if deviation.max() / values.std() <= g_critical:
            break
        flagged[deviation.idxmax()] = True
        values = values.drop(deviation.idxmax())

    return flagged


def remove_weekly_pattern(series):
    # weekends are always lower, so without this every Sunday would look like a drop
    weekday_level = series.groupby(series.index.weekday).transform("mean") / series.mean()
    return series / weekday_level


def run_tests(series, params):
    if params["weekly_adjust"]:
        series = remove_weekly_pattern(series)
    return pd.DataFrame({
        "IQR rule": iqr_outliers(series, params["iqr_k"]),
        "Z-score": zscore_outliers(series, params["z_threshold"]),
        "Moving average": moving_average_outliers(series, params["ma_window"], params["ma_percent"]),
        "Grubbs": grubbs_outliers(series, params["grubbs_alpha"]),
    })


def trendline(series, degree):
    x = np.arange(len(series))
    return pd.Series(np.polyval(np.polyfit(x, series, degree), x), index=series.index)


def summary_table(df, flags):
    return pd.DataFrame({name: {**describe(df[name]), **flags[name].sum()} for name in df.columns}).T.rename_axis("Series")


def find_anomalies(df, flags):
    # consecutive flagged days of the same series count as one anomaly
    events = []
    for name in df.columns:
        series = df[name]
        median = series.median()
        dates = series.index[flags[name].any(axis=1)].to_series()
        event_id = (dates.diff() != pd.Timedelta(days=1)).cumsum()

        for _, days in dates.groupby(event_id):
            values = series[days.index]
            peak = values[(values - median).abs().idxmax()]
            events.append({
                "Series": name,
                "Start": days.index[0],
                "End": days.index[-1],
                "Days": len(days),
                "Type": "Spike" if peak > median else "Drop",
                "Peak value": peak,
                "Median": median,
                "Change vs median (%)": (peak - median) / median * 100,
                "Detected by": ", ".join(t for t in TESTS if flags[name].loc[days.index, t].any()),
            })

    return pd.DataFrame(events)
