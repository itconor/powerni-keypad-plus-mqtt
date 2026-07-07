# Power NI keypad+ → Home Assistant (MQTT bridge)

Reads your **Power NI keypad+** prepayment electricity meter over Bluetooth and publishes the readings to **Home Assistant** via MQTT auto-discovery — so you can see your **credit balance**, **days of credit left** and **import units** on your dashboard and get low-balance alerts.

> **Read-only.** This bridge only *reads* the meter's display. It never enters tokens, tops up, or changes anything on the meter.

This is for the **Power NI keypad+** prepayment meter (the in-home unit with the keypad and LCD, model `keypad+`). It was built by reverse-engineering the official app's Bluetooth link — there was no prior public integration.

---

## Two ways to run it

Whichever you pick, the machine doing the reading needs a **Bluetooth adapter within range of the meter** (it's Bluetooth Classic, not BLE).

- **🏠 Home Assistant add-on** — if you run **HA OS / Supervised on a Pi or mini-PC near the meter**, add this repo as an add-on repository and configure everything in the HA UI. See [`powerni_keypad/DOCS.md`](powerni_keypad/DOCS.md).

  In HA: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add
  `https://github.com/itconor/powerni-keypad-plus-mqtt`, then install **PowerNI keypad+ Meter**.
  It auto-uses the Mosquitto broker add-on — **scan and pick your meter** in the add-on's **Meter Pairing** panel, then **pair it
  right in HA** (it shows the passkey to type on the meter — no SSH, no MAC hunting).

- **🐧 Standalone script** — if your HA runs in a **VM / away from the meter**, run `keypad_meter.py` as a systemd service on a small Linux box (a **Pi Zero W** is ideal) sitting next to the meter. Instructions below.

Both publish the same three MQTT-discovery sensors to Home Assistant.

---

## What you get in Home Assistant

Three sensors are created automatically via MQTT discovery (device **"Electricity Meter"**):

| Sensor | Example | Notes |
|---|---|---|
| `sensor.electricity_balance` | `£64.68` | current prepayment credit |
| `sensor.electricity_days_left` | `9` | meter's own "days of credit" estimate |
| `sensor.electricity_import_units` | `7431 kWh` | lifetime imported energy |

---

## How it works

The keypad+ exposes a **Bluetooth Classic SPP (RFCOMM)** serial port — a Microchip/ISSC **"Transparent UART"** bridge (service UUID prefix `49535343` = "ISSC"). It is **not** BLE.

The bridge:

1. Opens an RFCOMM socket to the meter (channel **6** on the units tested).
2. Sends `55 BB 01 44` to enter *transparent* mode (meter replies `55 CC 01 33`).
3. "Presses" the meter's function keys by sending their key-codes, e.g. **`C2 31`** (balance / days screens) and **`C2 39`** (import units). Each press advances the LCD to the next screen and returns the screen contents **byte-reversed**.
4. Parses the de-reversed text:
   - balance from a screen like `1  #64.68` (`#` = £),
   - days from `ABOUT 09`,
   - units from the `#7431.00 IMP UNITS` screen.
5. Publishes the values (keeping the last good reading so a flaky poll never blanks a sensor) and re-connects on each poll, because the meter's link idle-drops.

No credentials or crypto are involved in *reading* the meter — the read functions send the plain key-code and parse the plaintext reply.

---

## Requirements

- A Linux host with a **Bluetooth adapter, physically within range of the meter** — a **Raspberry Pi Zero W** sitting near the meter is ideal.
- Python 3 with **`paho-mqtt`** (`pip install paho-mqtt`, or `apt install python3-paho-mqtt`).
- An **MQTT broker** and **Home Assistant** with the MQTT integration.
- Standard BlueZ tools (`bluetoothctl`, `sdptool`, `rfkill`, `hciconfig`).

---

## Setup

### 1. Find and pair the meter

The meter advertises as **`B2200xxx`** and is always discoverable (no button to press). Only one host can connect at a time — make sure it isn't connected to your phone/another machine.

```bash
bluetoothctl
  power on
  agent KeyboardDisplay
  default-agent
  pairable on
  scan on          # note the meter's MAC (class 0x240404, name B2200xxx)
  pair AA:BB:CC:DD:EE:FF
```

Pairing uses **SSP passkey-entry**: the *host* prints a 6-digit `Passkey: NNNNNN` — **type that code on the meter's keypad**. Relay the code quickly (the entry window is short).

> Gotchas: if the radio locks up after failed attempts, `sudo reboot`. After boot the adapter may be rfkill-blocked — `sudo rfkill unblock bluetooth; sudo hciconfig hci0 up`.

### 2. Find the RFCOMM channel

```bash
sdptool browse AA:BB:CC:DD:EE:FF
```

Look for the Serial Port / SPP channel (**6** on the meters tested; set `METER_CH` if different).

### 3. Configure and run

Set the environment variables and run it:

```bash
export METER_MAC=AA:BB:CC:DD:EE:FF
export MQTT_HOST=192.168.1.10
export MQTT_USER=your_mqtt_user
export MQTT_PASS=your_mqtt_password
python3 keypad_meter.py
```

| Variable | Default | Meaning |
|---|---|---|
| `METER_MAC` | *(required)* | the meter's Bluetooth MAC |
| `METER_CH` | `6` | RFCOMM channel |
| `MQTT_HOST` / `MQTT_PORT` | `127.0.0.1` / `1883` | your broker |
| `MQTT_USER` / `MQTT_PASS` | *(empty)* | broker credentials |
| `POLL_SECS` | `1200` | seconds between reads (20 min) |

### 4. Run it as a service

Edit `keypad_meter.service` (set `User=`, the `ExecStart` path, `METER_MAC` and the MQTT variables), then:

```bash
sudo cp keypad_meter.py /home/pi/keypad_meter.py
sudo cp keypad_meter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now keypad_meter.service
journalctl -u keypad_meter -f
```

The sensors appear in Home Assistant automatically once the first poll succeeds.

---

## Notes & caveats

- **Read-only** — it only reads the display; it never touches top-ups.
- The Bluetooth link **idle-drops**, so the bridge reconnects on every poll — this is normal.
- **Import units** is the least reliable field (its screen cycles through several pages); the bridge presses the key several times and keeps the last good value.
- Screen text/regexes were derived from the meters the author had access to; other firmware revisions may differ slightly.

---

## Disclaimer

Not affiliated with, endorsed by, or supported by Power NI, Eckoh, or the meter manufacturer. Provided as-is under the MIT licence. Use at your own risk; only ever connect to a meter you own/control.
