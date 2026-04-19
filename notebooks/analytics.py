import marimo

__generated_with = "0.3.0"
app = marimo.App(width="medium")


@app.cell
def __():
    import marimo as mo
    import sqlite3
    import pandas as pd
    import altair as alt
    mo.md(
        """
        # Aegis Ocean Sensor Analytics
        Real-time inspection of the SQLite datastore visualizing thermal propagation and algorithmic scoring.
        """
    )
    return alt, mo, pd, sqlite3


@app.cell
def __(alt, mo, pd, sqlite3):
    conn = sqlite3.connect("../readings.db")
    try:
        df = pd.read_sql_query("SELECT * FROM readings", conn)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        base = alt.Chart(df).encode(
            x=alt.X('timestamp:T', title='Time')
        )

        temp_chart = base.mark_line(color="#ff4757").encode(
            y=alt.Y('temp_c:Q', title='Temperature (°C)'),
            tooltip=['timestamp', 'temp_c', 'z_temp']
        ).properties(height=150, width=600)

        salinity_chart = base.mark_line(color="#1e90ff").encode(
            y=alt.Y('salinity:Q', title='Salinity (PSU)'),
            tooltip=['timestamp', 'salinity', 'z_sal']
        ).properties(height=150, width=600)

        anomaly_chart = base.mark_area(color="#ffa502", opacity=0.3).encode(
            y=alt.Y('anomaly_score:Q', title='Isolation Forest Score')
        )
        anomaly_line = base.mark_line(color="#ffa502").encode(
            y=alt.Y('anomaly_score:Q')
        )

        # Baseline threshold constraint
        threshold = alt.Chart(pd.DataFrame({'y': [-0.1]})).mark_rule(
            color='red', 
            strokeDash=[5,5], 
            strokeWidth=2
        ).encode(y='y:Q')
        
        anomaly_layered = (anomaly_chart + anomaly_line + threshold).properties(
            height=150, 
            width=600, 
            title="Anomaly Score vs Operational Threshold (< -0.1)"
        )

        final_chart = alt.vconcat(
            temp_chart, 
            salinity_chart, 
            anomaly_layered
        ).resolve_scale(y='independent')
        
        display_chart = mo.ui.altair_chart(final_chart)
    except Exception as e:
        display_chart = mo.md(f"**Database Error** (Make sure the Digital Twin is running first to initialize `readings.db`): {e}")

    return anomaly_chart, anomaly_layered, anomaly_line, base, conn, df, display_chart, final_chart, salinity_chart, temp_chart, threshold


@app.cell
def __(display_chart):
    display_chart
    return


if __name__ == "__main__":
    app.run()
