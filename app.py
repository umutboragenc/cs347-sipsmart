"""
SmartSip (SipSmart) BLE -> NiceGUI dashboard (product metrics)

Shows:
- Last sip (mL): volume consumed in the most recent drinking event
- Today total (mL): total consumed since local midnight
- All-time (mL): lifetime total (from device total_l)

Chart:
- Rolling flow rate vs relative seconds (0s, 5s, 10s...)
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from bleak import BleakClient, BleakScanner
from nicegui import ui

# ------------------- BLE CONFIG -------------------
DEVICE_NAME = "XIAO_Flow"
NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notify/read

# ------------------- SIP DETECTION TUNING -------------------
# Any per-interval volume above this counts as "actively sipping"
SIP_ACTIVE_THRESHOLD_ML = 0.5

# If we see "inactive" for this many seconds after being active, sip ends
SIP_GAP_SECONDS = 2.0

# ------------------- CHART TUNING -------------------
CHART_SECONDS_WINDOW = 120  # show last N seconds on chart
UI_REFRESH_S = 0.5


# ------------------- DATA MODEL -------------------
@dataclass
class FlowSample:
    ts: float
    pulses: int
    freq_hz: float
    flow_lpm: float
    vol_ml: float          # volume during last interval (mL)
    total_l: float         # lifetime total from device (L)


def parse_csv_payload(s: str) -> FlowSample | None:
    """
    Expected CSV from ESP32:
      pulses,frequency_hz,flow_l_min,vol_ml_interval,total_l
    """
    s = s.strip()
    if not s or "pulses" in s.lower():
        return None

    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 5:
        return None

    try:
        return FlowSample(
            ts=time.time(),
            pulses=int(parts[0]),
            freq_hz=float(parts[1]),
            flow_lpm=float(parts[2]),
            vol_ml=float(parts[3]),
            total_l=float(parts[4]),
        )
    except ValueError:
        return None


# ------------------- APP STATE -------------------
state = {
    "running": False,
    "connected": False,
    "status": "Idle",
    "last_sample": None,     # FlowSample | None
    "client": None,          # BleakClient | None
    "task": None,            # asyncio.Task | None

    # Product metrics
    "last_sip_ml": 0.0,
    "today_ml": 0.0,
    "all_time_ml": 0.0,

    # Tracking for today reset
    "today_date": datetime.now().date(),

    # Sip state machine
    "sip_active": False,
    "sip_accum_ml": 0.0,
    "sip_last_active_ts": 0.0,
}

# Rolling buffers for chart
# We'll store (t_rel_s, flow_lpm)
t_buf = deque()
flow_buf = deque()

# We choose an anchor time so x-axis is stable and starts at 0
chart_t0 = None


def local_midnight_date():
    return datetime.now().date()


def reset_chart():
    global chart_t0
    t_buf.clear()
    flow_buf.clear()
    chart_t0 = None


def reset_metrics():
    # Do not touch all-time (device lifetime). Reset "today" and "last sip".
    state["last_sip_ml"] = 0.0
    state["today_ml"] = 0.0
    state["today_date"] = local_midnight_date()
    # also reset sip-in-progress
    state["sip_active"] = False
    state["sip_accum_ml"] = 0.0
    state["sip_last_active_ts"] = 0.0


# ------------------- METRIC UPDATE LOGIC -------------------
def update_day_rollover_if_needed():
    today = local_midnight_date()
    if today != state["today_date"]:
        # new day: reset daily total and sip accumulator
        state["today_date"] = today
        state["today_ml"] = 0.0
        state["sip_active"] = False
        state["sip_accum_ml"] = 0.0
        state["sip_last_active_ts"] = 0.0


def process_sample(sample: FlowSample):
    global chart_t0

    state["last_sample"] = sample

    # --- all-time from device total ---
    state["all_time_ml"] = max(0.0, sample.total_l * 1000.0)

    # --- daily rollover check ---
    update_day_rollover_if_needed()

    # --- today total accumulates from interval volume ---
    # (Assumes firmware is sending vol_ml_interval once per ~1s interval)
    if sample.vol_ml >= 0:
        state["today_ml"] += sample.vol_ml

    # --- sip detection ---
    now = sample.ts
    is_active = sample.vol_ml >= SIP_ACTIVE_THRESHOLD_ML

    if is_active:
        if not state["sip_active"]:
            state["sip_active"] = True
            state["sip_accum_ml"] = 0.0
        state["sip_accum_ml"] += sample.vol_ml
        state["sip_last_active_ts"] = now
    else:
        # If we were in a sip, check if it's time to finalize it
        if state["sip_active"] and (now - state["sip_last_active_ts"] >= SIP_GAP_SECONDS):
            # finalize sip
            state["last_sip_ml"] = state["sip_accum_ml"]
            state["sip_active"] = False
            state["sip_accum_ml"] = 0.0

    # --- chart update (relative seconds) ---
    if chart_t0 is None:
        chart_t0 = sample.ts

    t_rel = sample.ts - chart_t0
    t_buf.append(t_rel)
    flow_buf.append(sample.flow_lpm)

    # Trim to last CHART_SECONDS_WINDOW seconds
    while t_buf and (t_rel - t_buf[0] > CHART_SECONDS_WINDOW):
        t_buf.popleft()
        flow_buf.popleft()


# ------------------- BLE LOGIC -------------------
async def ble_stream_loop():
    while state["running"]:
        state["status"] = "Scanning for BLE device…"
        state["connected"] = False
        await asyncio.sleep(0)

        devices = await BleakScanner.discover(timeout=10.0)

        # Robust matching: exact match, then contains
        target = None
        for d in devices:
            if d.name == DEVICE_NAME:
                target = d
                break
        if not target:
            for d in devices:
                if d.name and DEVICE_NAME.lower() in d.name.lower():
                    target = d
                    break

        if not target:
            found_names = sorted({d.name for d in devices if d.name})
            preview = ", ".join(
                found_names[:8]) if found_names else "(no named devices)"
            state["status"] = f"Not found: {DEVICE_NAME}. Found: {preview}. Retrying…"
            await asyncio.sleep(2.0)
            continue

        state["status"] = f"Connecting to {target.name} ({target.address})…"

        def on_notify(_: int, data: bytearray):
            s = data.decode("utf-8", errors="ignore").strip()
            sample = parse_csv_payload(s)
            if not sample:
                return
            process_sample(sample)

        try:
            async with BleakClient(target.address) as client:
                state["client"] = client
                state["connected"] = True
                state["status"] = "Connected. Subscribed to notifications."
                await client.start_notify(NUS_TX_UUID, on_notify)

                while state["running"] and client.is_connected:
                    await asyncio.sleep(0.5)

        except Exception as e:
            state["status"] = f"BLE error: {type(e).__name__}: {e}"

        finally:
            state["connected"] = False
            state["client"] = None

        if state["running"]:
            state["status"] = "Disconnected. Reconnecting…"
            await asyncio.sleep(1.5)

    state["status"] = "Stopped."


def start_stream():
    if state["running"]:
        return
    state["running"] = True
    state["task"] = asyncio.create_task(ble_stream_loop())


async def disconnect():
    state["running"] = False

    client = state.get("client")
    if client:
        try:
            await client.stop_notify(NUS_TX_UUID)
        except Exception:
            pass
        try:
            await client.disconnect()
        except Exception:
            pass

    state["connected"] = False
    state["client"] = None
    state["task"] = None
    state["status"] = "Disconnected."


# ------------------- UI -------------------
ui.page_title("SipSmart • Flow Dashboard")

with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
    ui.label("SipSmart • Live Flow Sensor").classes("text-2xl font-bold")

    # Top status bar
    with ui.card().classes("w-full p-4"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("Connection").classes("text-sm opacity-70")
                conn_chip = ui.chip("Disconnected").classes(
                    "q-ma-none bg-red-2")

            with ui.column().classes("gap-1"):
                ui.label("Status").classes("text-sm opacity-70")
                status_chip = ui.chip("Idle").props("outline")

            with ui.column().classes("gap-1"):
                ui.label("Last update").classes("text-sm opacity-70")
                last_update = ui.label("—").classes("font-medium")

    # Product metric cards
    with ui.row().classes("w-full gap-4"):
        def metric_card(title: str, unit: str):
            with ui.card().classes("flex-1 p-4"):
                ui.label(title).classes("text-sm opacity-70")
                value = ui.label("—").classes("text-4xl font-bold")
                ui.label(unit).classes("text-sm opacity-60")
            return value

        last_sip_value = metric_card("Last sip", "mL")
        today_value = metric_card("Today total", "mL")
        all_time_value = metric_card("All-time total", "mL")

    # Chart
    with ui.card().classes("w-full p-4"):
        ui.label("Flow over time").classes("text-sm opacity-70")
        chart = ui.echart({
            "xAxis": {"type": "category", "data": []},
            "yAxis": {"type": "value", "name": "L/min"},
            "series": [{"type": "line", "data": [], "smooth": True, "showSymbol": False}],
            "grid": {"left": 50, "right": 20, "top": 30, "bottom": 40},
            "tooltip": {"trigger": "axis"},
        }).classes("w-full").style("height: 260px;")

    # Controls
    with ui.row().classes("gap-3"):
        start_btn = ui.button(
            "Start", on_click=start_stream).props("color=primary")
        disc_btn = ui.button("Disconnect", on_click=lambda: asyncio.create_task(
            disconnect())).props("outline")

        def reset_ui():
            reset_metrics()
            reset_chart()

        ui.button("Reset totals/chart", on_click=reset_ui).props("outline")

    def tick():
        # status
        status_chip.text = state["status"] or "—"

        if state["connected"]:
            conn_chip.text = "Connected"
            conn_chip.classes("bg-green-2", remove="bg-red-2")
        else:
            conn_chip.text = "Disconnected"
            conn_chip.classes("bg-red-2", remove="bg-green-2")

        # buttons
        start_btn.enabled = not state["running"]
        disc_btn.enabled = state["running"] or state["connected"]

        # last update
        samp: FlowSample | None = state["last_sample"]
        last_update.text = time.strftime(
            "%H:%M:%S", time.localtime(samp.ts)) if samp else "—"

        # product metrics (format nicely)
        last_sip_value.text = f"{state['last_sip_ml']:.1f}"
        today_value.text = f"{state['today_ml']:.1f}"
        all_time_value.text = f"{state['all_time_ml']:.1f}"

        # chart with relative seconds labels
        chart.options["xAxis"]["data"] = [f"{t:.0f}s" for t in t_buf]
        chart.options["series"][0]["data"] = list(flow_buf)
        chart.update()

    ui.timer(UI_REFRESH_S, tick)

ui.run(reload=False, host="127.0.0.1", port=8080)
