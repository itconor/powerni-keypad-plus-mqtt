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

## Step 1 — Pair the meter (one time)

Pairing uses interactive passkey entry and must be done on the **host**, not inside
this add-on. Install the **Advanced SSH & Web Terminal** add-on (protection mode off),
then:

```bash
bluetoothctl
  power on
  agent KeyboardDisplay
  default-agent
  pairable on
  scan on            # note the meter's MAC — name B2200xxx, class 0x240404
  pair AA:BB:CC:DD:EE:FF
```

The host prints a 6-digit `Passkey: NNNNNN` — **type that on the meter's keypad**
(the entry window is short, so be ready). Only one device can be connected to the
meter at a time — make sure it isn't paired to your phone.

Find the RFCOMM channel if it isn't 6:

```bash
sdptool browse AA:BB:CC:DD:EE:FF     # look for the Serial Port / SPP channel
```

## Step 2 — Configure the add-on

| Option | Meaning |
|---|---|
| `meter_mac` | Your meter's Bluetooth MAC (from pairing) |
| `meter_channel` | RFCOMM channel — **6** on the meters tested |
| `poll_seconds` | Seconds between reads (default 1200 = 20 min) |
| `mqtt_host` | **Leave blank** to auto-use the Mosquitto add-on. Set it only to point at an external broker. |
| `mqtt_port` / `mqtt_user` / `mqtt_pass` | Only used when `mqtt_host` is set |

Start the add-on and watch the **Log** tab — you should see it connect to the broker
and read the meter.

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
