# PowerNI keypad+ Meter — Home Assistant add-on

Reads your **PowerNI keypad+** prepayment electricity meter over Bluetooth and
publishes **credit balance**, **days of credit left** and **import units** to Home
Assistant via MQTT auto-discovery.

> **Read-only.** The bridge only reads the meter's display. It never tops up or
> changes anything on the meter.

## ⚠️ Before you install — will this work for you?

A Home Assistant **add-on runs on the machine running Home Assistant**. For this to
work, that machine must:

1. have a **Bluetooth adapter**, and
2. be **physically within Bluetooth range of the meter**.

That's fine if you run **HA OS on a Raspberry Pi / mini-PC near the meter**. If your
HA runs in a **VM or on a NUC away from the meter**, the add-on can't reach it — run
the standalone `keypad_meter.py` script on a small Linux box (e.g. a Pi Zero W) next
to the meter instead. See the repository README for that path.

The meter is **Bluetooth Classic (SPP/RFCOMM)**, *not* BLE — so ESPHome Bluetooth
proxies cannot help.

## Requirements

- Home Assistant OS (or Supervised) on hardware with Bluetooth, near the meter.
- The **Mosquitto broker** add-on (recommended — this add-on picks up its credentials
  automatically), or any MQTT broker.
- The **MQTT integration** enabled in Home Assistant.

## Step 1 — Options (all optional to start)

| Option | Meaning |
|---|---|
| `meter_mac` | **Leave blank** — you'll pick the meter by scanning in the panel. Set it only to force a specific MAC. |
| `meter_channel` | RFCOMM channel — **6** on the meters tested |
| `poll_seconds` | Seconds between reads (default 1200 = 20 min) |
| `mqtt_host` | **Leave blank** to auto-use the Mosquitto add-on. Set it only for an external broker. |
| `mqtt_port` / `mqtt_user` / `mqtt_pass` | Only used when `mqtt_host` is set |

You can start the add-on with everything at its defaults and do the rest in the panel.

## Step 2 — Scan, select, and pair — all in Home Assistant

Open the **"Meter Pairing"** panel (HA sidebar, or the add-on's **Ingress** page):

1. **Scan for meter** — discovers nearby Bluetooth devices and flags the likely meter
   with a green **★ likely meter** tag (its name is `B2200…`).
2. **Select** your meter from the list — the choice is saved automatically.
3. **Pair selected** — a **6-digit passkey** appears on the page. **Type it on the
   meter's keypad** while it's shown (the window is short, so be ready).

- Make sure the meter isn't connected to your phone (single connection only).
- On success the page shows **paired ✔** and the reader starts automatically.
- No SSH or `bluetoothctl` — it drives the host's Bluetooth for you.
- If the scan finds nothing, the host has no Bluetooth adapter (or the meter's out of
  range) — this add-on must run on HA hardware with Bluetooth near the meter.

Once paired, the three sensors appear in Home Assistant within one poll cycle.

## What you get

Three sensors appear automatically (device **"Electricity Meter"**):

| Sensor | Example |
|---|---|
| `sensor.electricity_balance` | `£64.68` |
| `sensor.electricity_days_left` | `9` |
| `sensor.electricity_import_units` | `7431 kWh` |

## Notes

- The Bluetooth link idle-drops; the bridge reconnects on every poll — normal.
- **Import units** is the least reliable field (its screen cycles several pages); the
  bridge keeps the last good value.
- If reads fail, confirm nothing else is connected to the meter and that the host is
  actually in Bluetooth range.
