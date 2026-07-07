#!/usr/bin/env python3
"""Power NI keypad+ meter -> Home Assistant via MQTT discovery.

Reads the meter over Bluetooth Classic RFCOMM (channel 6): enter ISSC transparent
mode (55 BB 01 44), then press the meter's function keys (C2 3x) and parse the
byte-reversed LCD screens. Publishes balance (£), days-left and import kWh.
Read-only — never touches top-ups. The BT link idle-drops, so it reconnects per poll.
"""
import socket, time, re, json, os, sys
import paho.mqtt.client as mqtt

MAC = os.environ.get("METER_MAC", "")
CH  = int(os.environ.get("METER_CH", "6"))
POLL = int(os.environ.get("POLL_SECS", "1200"))          # 20 min
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")

DISC = "homeassistant"
ST = "keypad_meter/state"
AV = "keypad_meter/availability"
DEV = {"identifiers": ["powerni_keypad_meter"], "name": "Electricity Meter",
       "manufacturer": "Power NI", "model": "keypad+"}

def _rev(b):
    return [seg[::-1] for seg in b.decode('latin1').replace('\n', '\r').split('\r') if seg.strip()]

def read_meter():
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(12); s.connect((MAC, CH)); s.settimeout(1)
    def rd(t=3.0):
        end = time.time() + t; buf = b""
        while time.time() < end:
            try:
                d = s.recv(256)
                if d: buf += d; end = time.time() + 0.7
            except socket.timeout: pass
            except Exception: break
        return buf
    bal_scr, unit_lines = [], []
    try:
        s.send(bytes.fromhex("55BB0144")); rd(1.5)          # enter transparent
        for _ in range(8):                                   # cycle the balance key
            s.send(bytes.fromhex("C231")); bal_scr += _rev(rd(3.0))
        for _ in range(12):                                  # import units key
            s.send(bytes.fromhex("C239")); unit_lines.append(" ".join(_rev(rd(3.0))))
    finally:
        try: s.close()
        except Exception: pass
    bj = " ".join(bal_scr)
    m = re.search(r"#\s*(\d+\.\d+)", bj);   bal = float(m.group(1)) if m else None
    m = re.search(r"ABOUT\s+(\d+)", bj);    days = int(m.group(1)) if m else None
    units = None
    for ln in unit_lines:                                    # value sits on the screen labelled UNITS
        if "UNIT" in ln.upper():
            mm = re.search(r"(\d+\.\d+)", ln)
            if mm: units = float(mm.group(1)); break
    return bal, days, units, bj, " ".join(unit_lines)

def mk_client():
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="keypad_meter")
    except (AttributeError, TypeError):
        c = mqtt.Client(client_id="keypad_meter")
    if MQTT_USER:
        c.username_pw_set(MQTT_USER, MQTT_PASS)
    c.will_set(AV, "offline", retain=True)
    c.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    return c

def discovery(c):
    base = lambda uid: {"state_topic": ST, "availability_topic": AV, "device": DEV, "unique_id": uid}
    cfgs = {
        "keypad_balance": {**base("keypad_balance"), "object_id": "electricity_balance", "name": "Balance",
                           "value_template": "{{ value_json.balance }}", "unit_of_measurement": "£",
                           "state_class": "measurement", "icon": "mdi:cash"},
        "keypad_days_left": {**base("keypad_days"), "object_id": "electricity_days_left", "name": "Days Left",
                             "value_template": "{{ value_json.days }}", "unit_of_measurement": "d",
                             "state_class": "measurement", "icon": "mdi:calendar-clock"},
        "keypad_units": {**base("keypad_units"), "object_id": "electricity_import_units", "name": "Import Units",
                         "value_template": "{{ value_json.units }}", "unit_of_measurement": "kWh",
                         "device_class": "energy", "state_class": "total_increasing",
                         "icon": "mdi:transmission-tower"},
    }
    for slug, cfg in cfgs.items():
        c.publish(f"{DISC}/sensor/{slug}/config", json.dumps(cfg), retain=True)

def main():
    c = mk_client(); c.loop_start()
    discovery(c); c.publish(AV, "online", retain=True)
    print(f"[start] broker {MQTT_HOST}:{MQTT_PORT} user={MQTT_USER} poll={POLL}s", flush=True)
    last = {"balance": None, "days": None, "units": None}
    while True:
        bal = days = units = None
        for attempt in (1, 2):
            try:
                bal, days, units, bj, uj = read_meter()
                break
            except Exception as e:
                print(f"[read] attempt {attempt} failed: {e}", flush=True); time.sleep(4)
        if bal is not None: last["balance"] = bal
        if days is not None: last["days"] = days
        if units is not None: last["units"] = units
        if any(v is not None for v in (bal, days, units)):
            c.publish(ST, json.dumps(last), retain=True)
            c.publish(AV, "online", retain=True)
            print(f"[poll] balance £{bal} days {days} units {units} (kept: {last})", flush=True)
        else:
            print("[poll] no data this cycle", flush=True)
        time.sleep(POLL)

if __name__ == "__main__":
    main()
