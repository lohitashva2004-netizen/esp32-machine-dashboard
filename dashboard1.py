import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import paho.mqtt.client as mqtt
import json
import threading
from collections import deque
# Latest sensor values
latest_data = {
    "vibration": 0,
    "temperature": 0,
    "current": 0,
    "status": "Waiting"
}

# =========================================================
# DATA STORAGE (rolling buffers)
# =========================================================

vibration = deque(maxlen=200)
temperature = deque(maxlen=200)
current = deque(maxlen=200)
status = deque(maxlen=200)

# initialize so UI has something to render
vibration.append(0)
temperature.append(0)
current.append(0)
status.append("Waiting")

# =========================================================
# ANALYTICS FUNCTIONS
# =========================================================

def calculate_health(v, t, c):
    """
    Simple health score based on sensor magnitude.
    Lower combined magnitude => higher health.
    """
    score = 100 - ((v + t + c) / 150.0)
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return round(score, 1)

def detect_fault(v, t, c):
    """
    Basic rule-based fault classification.
    """
    if v > 2500:
        return "Bearing Fault"
    if t > 2500:
        return "Thermal Fault"
    if c > 2500:
        return "Electrical Overload"
    return "Normal"

def predict_rul(v, t, c):
    """
    Very simple Remaining Useful Life estimate
    derived from average degradation.
    """
    degradation = (v + t + c) / 3.0
    rul = max(0, 5000 - degradation)
    return round(rul / 100.0, 1)

def maintenance_advice(fault):
    if fault == "Bearing Fault":
        return "Inspect bearings and lubrication"
    if fault == "Thermal Fault":
        return "Check cooling system / airflow"
    if fault == "Electrical Overload":
        return "Reduce motor load / inspect wiring"
    return "No maintenance required"

# =========================================================
# MQTT CALLBACK
# =========================================================

def on_message(client, userdata, msg):

    global latest_data

    try:

        payload = json.loads(msg.payload.decode())

        vib = payload.get("vibration",0)
        temp = payload.get("temperature",0)
        curr = payload.get("current",0)
        stat = payload.get("status","Normal")

        print("MQTT:", payload)

        # update global values
        latest_data["vibration"] = vib
        latest_data["temperature"] = temp
        latest_data["current"] = curr
        latest_data["status"] = stat

        vibration.append(vib)
        temperature.append(temp)
        current.append(curr)
        status.append(stat)

    except Exception as e:

        print("MQTT ERROR:",e)

# =========================================================
# START MQTT CLIENT IN BACKGROUND THREAD
# =========================================================

def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect("broker.hivemq.com", 1883, 60)
    client.subscribe("machine/sensors")
    client.loop_forever()

mqtt_thread = threading.Thread(target=start_mqtt)
mqtt_thread.daemon = True
mqtt_thread.start()

# =========================================================
# DASH APP
# =========================================================

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
server = app.server

app.layout = dbc.Container([

    html.H1("⚙ Industrial Predictive Maintenance System"),

    dbc.Row([
        dbc.Col(dcc.Graph(id="vibration-gauge")),
        dbc.Col(dcc.Graph(id="temperature-gauge")),
        dbc.Col(dcc.Graph(id="current-gauge"))
    ]),

    html.Br(),

    dbc.Row([
        dbc.Col(dcc.Graph(id="health-gauge")),
        dbc.Col(html.H3(id="rul-display")),
        dbc.Col(html.H3(id="maintenance-text"))
    ]),

    html.Br(),

    dbc.Row([
        dbc.Col(html.H3(id="fault-type")),
        dbc.Col(html.H3(id="alarm-indicator"))
    ]),

    html.Br(),

    dbc.Row([
        dbc.Col(dcc.Graph(id="fault-probability"))
    ]),

    html.Br(),

    dbc.Row([
        dbc.Col(dcc.Graph(id="trend-graph"))
    ]),

    html.Br(),

    dbc.Row([
        dbc.Col(html.H4("Recent Sensor Data")),
        dbc.Col(html.Div(id="data-table"))
    ]),

    dcc.Interval(
        id="interval-update",
        interval=2000,
        n_intervals=0
    )

], fluid=True)

# =========================================================
# DASH UPDATE CALLBACK
# =========================================================

@app.callback(

    [
        Output("vibration-gauge","figure"),
        Output("temperature-gauge","figure"),
        Output("current-gauge","figure"),
        Output("health-gauge","figure"),
        Output("trend-graph","figure"),
        Output("fault-probability","figure"),
        Output("rul-display","children"),
        Output("maintenance-text","children"),
        Output("fault-type","children"),
        Output("alarm-indicator","children"),
        Output("data-table","children")
    ],

    [Input("interval-update","n_intervals")]

)

def update_dashboard(n):
    v = latest_data["vibration"]
    t = latest_data["temperature"]
    c = latest_data["current"]


    health = calculate_health(v, t, c)
    fault = detect_fault(v, t, c)
    rul = predict_rul(v, t, c)
    maintenance = maintenance_advice(fault)

    if fault != "Normal":
        alarm = "🔴 ALARM ACTIVE"
    else:
        alarm = "🟢 SYSTEM NORMAL"

    # ---------------------------
    # GAUGES
    # ---------------------------

    vib_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        title={'text':"Vibration"},
        gauge={'axis':{'range':[0,4095]}}
    ))

    temp_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=t,
        title={'text':"Temperature"},
        gauge={'axis':{'range':[0,4095]}}
    ))

    curr_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=c,
        title={'text':"Current"},
        gauge={'axis':{'range':[0,4095]}}
    ))

    health_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=health,
        title={'text':"Machine Health %"},
        gauge={'axis':{'range':[0,100]}}
    ))

    # ---------------------------
    # TREND GRAPH
    # ---------------------------

    trend = go.Figure()

    trend.add_trace(go.Scatter(
        y=list(vibration),
        mode="lines",
        name="Vibration"
    ))

    trend.add_trace(go.Scatter(
        y=list(temperature),
        mode="lines",
        name="Temperature"
    ))

    trend.add_trace(go.Scatter(
        y=list(current),
        mode="lines",
        name="Current"
    ))

    trend.update_layout(title="Sensor Trend Analysis")

    # ---------------------------
    # FAULT PROBABILITY CHART
    # ---------------------------

    fault_chart = go.Figure()

    fault_chart.add_bar(
        x=["Bearing", "Thermal", "Electrical"],
        y=[v/40, t/40, c/40]
    )

    fault_chart.update_layout(title="Fault Probability")

    # ---------------------------
    # TABLE
    # ---------------------------

    df = pd.DataFrame({
        "Vibration": list(vibration)[-10:],
        "Temperature": list(temperature)[-10:],
        "Current": list(current)[-10:]
    })

    table = dbc.Table.from_dataframe(df, striped=True, bordered=True, hover=True)

    return (
        vib_gauge,
        temp_gauge,
        curr_gauge,
        health_gauge,
        trend,
        fault_chart,
        f"Remaining Useful Life: {rul} hours",
        f"Maintenance: {maintenance}",
        f"Detected Fault: {fault}",
        alarm,
        table
    )

# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
