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

## Step 1 — Configure the add-on

| Option | Meaning |
|---|---|
| `meter_mac` | Your meter's Bluetooth MAC |
| `meter_channel` | RFCOMM channel — **6** on the meters tested |
| `poll_seconds` | Seconds between reads (default 1200 = 20 min) |
| `mqtt_host` | **Leave blank** to auto-use the Mosquitto add-on. Set it only to point at an external broker. |
| `mqtt_port` / `mqtt_user` / `mqtt_pass` | Only used when `mqtt_host` is set |

**Finding the MAC:** the meter advertises as **`B2200xxx`** (class `0x240404`). If you
don't know its MAC, the quickest way is the phone's Bluetooth screen, or the
**Advanced SSH & Web Terminal** add-on (`bluetoothctl` → `scan on`).

## Step 2 — Pair the meter, in Home Assistant

Start the add-on, then open the **"Meter Pairing"** panel (it appears in the HA
sidebar, and under the add-on's **Ingress** page). Press **Pair meter** — a **6-digit
passkey** appears on the page. **Type that on the meter's keypad** while it's shown
(the window is short, so be ready).

- Make sure the meter isn't connected to your phone (single connection only).
- On success the page shows **paired ✔** and the reader (bridge) starts automatically.
- No SSH or `bluetoothctl` needed — it drives the host's Bluetooth for you.

Once paired, the three sensors appear in Home Assistant within one poll cycle. The
panel also shows the bridge status and a live log.

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
