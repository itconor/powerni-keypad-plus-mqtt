#!/usr/bin/env python3
"""PowerNI keypad+ add-on — ingress pairing UI + bridge supervisor.

Lets you set everything up from inside Home Assistant:
  * Scan for nearby Bluetooth devices and pick the meter (no MAC typing needed).
  * Pair it — the 6-digit passkey the host generates is shown big on the page
    for you to type on the meter's keypad.
  * The reader (keypad_meter.py) is (re)started automatically once paired, and
    paused during scan/pair so it doesn't hold the meter's single connection.

The chosen MAC is persisted to /data so it survives restarts. A meter_mac set in
the add-on Configuration tab (if any) takes precedence.
"""
import os, re, sys, time, threading, subprocess, collections
from flask import Flask, jsonify, request, render_template_string

VERSION     = "1.2.6"
PLACEHOLDER = "AA:BB:CC:DD:EE:FF"
DATA_DIR    = "/data"
MAC_FILE    = os.path.join(DATA_DIR, "meter_mac")
CFG_MAC     = os.environ.get("METER_MAC", "").strip()

app = Flask(__name__)

STATE = {
    "mac": "",
    "mac_source": "none",       # config | saved | selected | none
    "paired": False,
    "pairing": False,
    "scanning": False,
    "passkey": "",
    "status": "idle",
    "devices": [],              # [{mac,name,likely}]
    "lines": collections.deque(maxlen=40),
    "bridge": "stopped",
}
_bridge_proc = None
_lock = threading.Lock()

def log(msg):
    STATE["lines"].append(f"{time.strftime('%H:%M:%S')}  {msg}")

# ---- persistence ----------------------------------------------------------
def save_mac(mac):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MAC_FILE, "w") as f:
            f.write(mac.strip())
    except Exception as e:
        log(f"could not save MAC: {e}")

def load_saved_mac():
    try:
        return open(MAC_FILE).read().strip()
    except Exception:
        return ""

def is_real_mac(m):
    return bool(m) and m.upper() != PLACEHOLDER and re.fullmatch(r"[0-9A-Fa-f:]{17}", m or "")

def set_mac(mac, source):
    STATE["mac"] = mac
    STATE["mac_source"] = source

# ---- bluetooth helpers ----------------------------------------------------
def _btctl(*cmds, timeout=15):
    p = subprocess.run(["bluetoothctl"], input="\n".join(cmds) + "\nquit\n",
                       capture_output=True, text=True, timeout=timeout)
    return p.stdout + p.stderr

def is_paired(mac):
    try:
        return re.search(r"Paired:\s*yes", _btctl(f"info {mac}"), re.I) is not None
    except Exception:
        return False

def _looks_like_meter(name):
    return bool(re.match(r"B2\d{5,}", name or "", re.I))

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
def _clean(s):
    return _ANSI.sub("", s or "")

def do_scan(secs=12):
    """Scan for nearby BT devices, populate STATE['devices']."""
    try:
        import pexpect
    except Exception:
        STATE["status"] = "error: pexpect missing"; STATE["scanning"] = False; return
    stop_bridge()
    STATE.update(scanning=True, status="scanning…", devices=[])
    log("Scanning for Bluetooth devices…")
    try:
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=secs + 15)
        for c in ("power on", "scan on"):
            child.sendline(c); time.sleep(0.5)
        time.sleep(secs)
        child.sendline("devices")
        time.sleep(1.5)
        child.sendline("scan off"); child.sendline("quit")
        out = ""
        try:
            out = child.read()
        except Exception:
            pass
        found = {}
        for m in re.finditer(r"Device\s+([0-9A-F:]{17})\s+(.+)", out):
            mac, name = m.group(1).strip(), m.group(2).strip()
            if not name or name == mac:
                continue
            found[mac] = name
        devs = [{"mac": k, "name": v, "likely": _looks_like_meter(v)} for k, v in found.items()]
        devs.sort(key=lambda d: (not d["likely"], d["name"].lower()))
        STATE["devices"] = devs
        n_likely = sum(d["likely"] for d in devs)
        STATE["status"] = (f"found {len(devs)} device(s)"
                           + (f", {n_likely} likely meter(s)" if n_likely else ""))
        log(STATE["status"] + (" — none look like a meter (no adapter, or out of range?)"
                               if not devs else ""))
    except Exception as e:
        STATE["status"] = f"scan error: {e}"; log(STATE["status"])
    finally:
        STATE["scanning"] = False
        if STATE["paired"]:
            start_bridge()

def bt_diag():
    """Print the ground truth about Bluetooth support to the panel log."""
    import socket as _sock
    log("── Bluetooth diagnostic ──")
    log(f"add-on pair_ui version: {VERSION}")
    has = hasattr(_sock, "AF_BLUETOOTH")
    log(f"python AF_BLUETOOTH const: {('yes = ' + str(_sock.AF_BLUETOOTH)) if has else 'MISSING'}")
    af    = getattr(_sock, "AF_BLUETOOTH", 31)
    proto = getattr(_sock, "BTPROTO_RFCOMM", 3)
    try:
        t = _sock.socket(af, _sock.SOCK_STREAM, proto); t.close()
        log("raw RFCOMM socket: OK ✔  → privileged BT access is working")
    except OSError as e:
        hint = {97: "AF_BLUETOOTH only works in the HOST network namespace → add-on needs host_network: true (fixed in v1.2.6). Update + restart.",
                93: "kernel has no Bluetooth-Classic RFCOMM → can't run in-container; use the standalone Docker/script on a Pi-OS box"}.get(e.errno, "")
        log(f"raw RFCOMM socket: FAILED errno {e.errno} ({e.strerror})")
        if hint:
            log(f"   → {hint}")
    try:
        mods = set(os.listdir("/sys/module"))
        present = [m for m in ("bluetooth", "rfcomm", "btusb", "hci_uart") if m in mods]
        log("kernel modules loaded: " + (", ".join(present) if present else "none of bluetooth/rfcomm/btusb"))
    except Exception as e:
        log(f"module check failed: {e}")
    try:
        import gzip
        if os.path.exists("/proc/config.gz"):
            cfg = gzip.open("/proc/config.gz", "rt", errors="ignore").read()
            for line in cfg.splitlines():
                if line.startswith(("CONFIG_BT=", "CONFIG_BT_RFCOMM")):
                    log(f"  {line}")
        else:
            log("/proc/config.gz not available (can't read kernel config)")
    except Exception as e:
        log(f"kernel-config read failed: {e}")
    log("── end diagnostic ──")

def do_reset():
    """Recover a wedged adapter / half-bonded device: power-cycle + remove."""
    stop_bridge()
    STATE.update(status="resetting Bluetooth…", passkey="", paired=False)
    log("Resetting the Bluetooth adapter…")
    try:
        _btctl("power off"); time.sleep(2)
        _btctl("power on");  time.sleep(1)
        if is_real_mac(STATE["mac"]):
            _btctl(f"remove {STATE['mac']}")
            log(f"Power-cycled the adapter and cleared {STATE['mac']}. Scan again, then Pair.")
        else:
            log("Power-cycled the adapter. Scan again, then Pair.")
        STATE.update(status="reset done — scan again", devices=[])
    except Exception as e:
        STATE["status"] = f"reset error: {e}"; log(f"Reset error: {e}")

def do_pair(mac):
    try:
        import pexpect
    except Exception:
        STATE.update(status="error: pexpect missing", pairing=False); return
    stop_bridge()
    STATE.update(pairing=True, passkey="", status="starting…")
    log(f"Pairing {mac} … watch for the code below.")
    child = None
    try:
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=5,
                              codec_errors="ignore")
        for c in ("power on", "agent KeyboardDisplay", "default-agent",
                  "pairable on", "scan on"):
            child.sendline(c); time.sleep(0.5)
        STATE["status"] = "pairing…"
        log("Meter allows only ONE connection — turn the phone's Bluetooth OFF first.")
        time.sleep(3)
        attempts = 1
        child.sendline(f"pair {mac}")

        deadline = time.monotonic() + 180
        pending = ""
        while time.monotonic() < deadline and STATE["pairing"]:
            try:
                data = child.read_nonblocking(size=512, timeout=2)
            except pexpect.TIMEOUT:
                data = ""
            except pexpect.EOF:
                break
            if not data:
                continue
            pending += _clean(data)
            parts = re.split(r"[\r\n]+", pending)
            pending = parts.pop()                      # keep the partial last line
            for ln in parts:
                ln = ln.strip()
                if not ln:
                    continue
                low = ln.lower()
                # surface the raw bluetoothctl lines that matter (skip prompt spam)
                if any(k in low for k in ("passkey", "pin", "pairing", "confirm",
                                          "agent", "fail", "success", "request",
                                          "authentication")):
                    log(f"» {ln}")
                m = re.search(r"passkey[:\s]+0*(\d{1,6})", low)
                if m:
                    key = m.group(1).zfill(6)
                    if key != STATE["passkey"]:
                        STATE.update(passkey=key, status="TYPE THIS ON THE METER")
                        log(f"★ Passkey {key} — type it on the meter keypad NOW.")
                    continue
                m2 = re.search(r"pin code[:\s]+0*(\d{1,8})", low)
                if m2:
                    STATE.update(passkey=m2.group(1), status="TYPE THIS PIN ON THE METER")
                    log(f"★ PIN {m2.group(1)} — type it on the meter keypad NOW.")
                    continue
                if "confirm passkey" in low or "(yes/no)" in low:
                    child.sendline("yes")
                elif "enter passkey" in low or "enter pin" in low:
                    STATE["status"] = "meter asked host to enter a code (unexpected)"
                    log("BlueZ asked the HOST to enter a code — the meter should be entering. Paste this log.")
                elif "pairing successful" in low:
                    STATE.update(status="paired", paired=True)
                    log("Pairing successful ✔")
                    try: _btctl(f"trust {mac}")
                    except Exception: pass
                    break
                elif "connectionattemptfailed" in low:
                    if attempts < 3:
                        attempts += 1
                        log(f"Connection failed — retry {attempts}/3. Turn the phone's Bluetooth OFF (it holds the meter's only connection).")
                        time.sleep(3)
                        child.sendline(f"pair {mac}")
                    else:
                        STATE["status"] = "failed — connection kept failing"
                        log("Still failing after 3 tries. Turn OFF the phone's Bluetooth + force-quit the PowerNI app, then Pair again.")
                        break
                elif ("failed to pair" in low or "not available" in low
                      or "org.bluez.error" in low or "authentication failed" in low):
                    STATE["status"] = "failed — retry"
                    log("Pairing failed — see the lines above.")
                    break
        if not STATE["paired"] and STATE["status"] not in ("failed — retry",):
            STATE["status"] = ("waiting — enter the code on the meter"
                               if STATE["passkey"] else "no code seen — check the log")
    except Exception as e:
        STATE.update(status=f"error: {e}"); log(f"Error: {e}")
    finally:
        try:
            if child and child.isalive():
                child.sendline("quit"); child.close()
        except Exception:
            pass
        STATE["pairing"] = False
        if not STATE["paired"] and is_paired(mac):
            STATE.update(paired=True, status="paired")
        if STATE["paired"]:
            start_bridge()

# ---- bridge supervisor ----------------------------------------------------
def _reader(proc):
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if line:
            log(f"[bridge] {line}")

def start_bridge():
    global _bridge_proc
    with _lock:
        if _bridge_proc and _bridge_proc.poll() is None:
            return
        if not is_real_mac(STATE["mac"]):
            return
        env = dict(os.environ, METER_MAC=STATE["mac"])
        log("Starting meter bridge…")
        _bridge_proc = subprocess.Popen([sys.executable, "/keypad_meter.py"],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, env=env)
        STATE["bridge"] = "running"
        threading.Thread(target=_reader, args=(_bridge_proc,), daemon=True).start()

def stop_bridge():
    global _bridge_proc
    with _lock:
        if _bridge_proc and _bridge_proc.poll() is None:
            _bridge_proc.terminate()
            try: _bridge_proc.wait(timeout=5)
            except Exception: _bridge_proc.kill()
        STATE["bridge"] = "stopped"

# ---- page -----------------------------------------------------------------
PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Meter Pairing</title><style>
body{font-family:system-ui,sans-serif;background:#0b1220;color:#e8eef7;margin:0;padding:18px;max-width:680px}
h1{font-size:19px;margin:0 0 4px}.mu{color:#93a2bd;font-size:13px}
.card{background:#131c30;border:1px solid #24334f;border-radius:12px;padding:16px;margin:14px 0}
button{background:#2f6df6;border:0;color:#fff;font-size:15px;font-weight:600;padding:10px 16px;border-radius:9px;cursor:pointer}
button.sec{background:#38445e}button:disabled{opacity:.5;cursor:default}
.key{font-size:52px;font-weight:800;letter-spacing:8px;text-align:center;color:#ffd23f;margin:8px 0}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700}
.ok{background:#0f2e1b;color:#37d67a}.bad{background:#3a1414;color:#ff6b6b}.idle{background:#1e2b45;color:#93a2bd}
.dev{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 11px;border:1px solid #24334f;border-radius:9px;margin:7px 0;background:#0e1626}
.dev.likely{border-color:#37d67a}.tag{font-size:11px;font-weight:700;color:#37d67a}
code{background:#0a1120;padding:2px 6px;border-radius:5px}
pre{background:#0a1120;border:1px solid #24334f;border-radius:8px;padding:10px;max-height:200px;overflow:auto;font-size:12px;white-space:pre-wrap}
.mac{font-family:ui-monospace,monospace;font-size:13px}
</style></head><body>
<h1>PowerNI keypad+ — Bluetooth</h1>
<div class=mu>Selected meter: <code class=mac id=mac>none</code> <span id=src class=mu></span></div>

<div class=card>
  <div>Status: <span id=status class="pill idle">idle</span>
       &nbsp; Bridge: <span id=bridge class="pill idle">stopped</span></div>
  <div style="margin-top:12px">
    <button id=scan onclick="scan()">Scan for meter</button>
    <button id=pair onclick="pair()">Pair selected</button>
    <button class=sec onclick="unpair()">Remove pairing</button>
    <button class=sec onclick="reset()">Reset Bluetooth</button>
    <button class=sec onclick="diag()">Diagnose</button>
  </div>
  <div id=keywrap style="display:none">
    <div class=mu style="margin-top:12px">Type this on the meter keypad now:</div>
    <div class=key id=key>––––––</div>
  </div>
</div>

<div class=card>
  <div class=mu>Discovered devices <span id=devhint></span></div>
  <div id=devs></div>
</div>

<div class=card><div class=mu>Log</div><pre id=log></pre></div>

<script>
function cls(el,c){el.className='pill '+c}
async function scan(){ await fetch('scan',{method:'POST'}); }
async function pair(){ await fetch('pair',{method:'POST'}); }
async function unpair(){ await fetch('unpair',{method:'POST'}); }
async function reset(){ await fetch('reset',{method:'POST'}); }
async function diag(){ await fetch('diag',{method:'POST'}); }
async function pick(mac){ await fetch('select?mac='+encodeURIComponent(mac),{method:'POST'}); }
function devRow(d,sel){
  const b = d.mac===sel ? '<span class=tag>selected</span>'
          : '<button onclick="pick(\\''+d.mac+'\\')">Select</button>';
  return '<div class="dev'+(d.likely?' likely':'')+'">'
    +'<div><b>'+ (d.name||'(unnamed)') +'</b>'+(d.likely?' <span class=tag>★ likely meter</span>':'')
    +'<div class="mu mac">'+d.mac+'</div></div>'+b+'</div>';
}
async function tick(){
  try{
    const s = await (await fetch('state')).json();
    document.getElementById('mac').textContent = s.mac || 'none';
    document.getElementById('src').textContent = s.mac ? '('+s.mac_source+')' : '';
    const st=document.getElementById('status'); st.textContent=s.status;
    cls(st, s.paired?'ok':((s.status||'').match(/fail|error/)?'bad':'idle'));
    const br=document.getElementById('bridge'); br.textContent=s.bridge; cls(br, s.bridge=='running'?'ok':'idle');
    document.getElementById('scan').disabled = s.scanning||s.pairing;
    document.getElementById('pair').disabled = s.pairing||s.scanning|| !s.mac;
    const kw=document.getElementById('keywrap');
    if(s.passkey){ kw.style.display='block'; document.getElementById('key').textContent=s.passkey; }
    else kw.style.display='none';
    document.getElementById('devhint').textContent = s.scanning?'— scanning…':(s.devices.length?'':'— press "Scan for meter"');
    document.getElementById('devs').innerHTML = s.devices.map(d=>devRow(d,s.mac)).join('') || '';
    document.getElementById('log').textContent = s.lines.join('\\n');
  }catch(e){}
}
setInterval(tick,1000); tick();
</script></body></html>"""

@app.get("/")
def index():
    return render_template_string(PAGE)

@app.get("/state")
def state():
    return jsonify({k: (list(v) if isinstance(v, collections.deque) else v)
                    for k, v in STATE.items()})

@app.post("/scan")
def scan():
    if not STATE["scanning"]:
        threading.Thread(target=do_scan, daemon=True).start()
    return ("", 204)

@app.post("/select")
def select():
    mac = (request.args.get("mac") or "").strip()
    if is_real_mac(mac):
        stop_bridge()
        set_mac(mac, "selected")
        save_mac(mac)
        STATE.update(paired=is_paired(mac), passkey="", status="selected " + mac)
        log(f"Selected meter {mac}")
        if STATE["paired"]:
            start_bridge()
    return ("", 204)

@app.post("/reset")
def reset():
    if not (STATE["pairing"] or STATE["scanning"]):
        threading.Thread(target=do_reset, daemon=True).start()
    return ("", 204)

@app.post("/diag")
def diag():
    threading.Thread(target=bt_diag, daemon=True).start()
    return ("", 204)

@app.post("/pair")
def pair():
    if not is_real_mac(STATE["mac"]):
        log("Scan and select a meter first."); return ("", 204)
    if not STATE["pairing"]:
        threading.Thread(target=do_pair, args=(STATE["mac"],), daemon=True).start()
    return ("", 204)

@app.post("/unpair")
def unpair():
    mac = STATE["mac"]
    if is_real_mac(mac):
        stop_bridge()
        try: _btctl(f"remove {mac}")
        except Exception: pass
        STATE.update(paired=False, status="removed", passkey="")
        log(f"Removed pairing for {mac}")
    return ("", 204)

def _boot():
    log(f"PowerNI keypad+ pair_ui v{VERSION}")
    bt_diag()
    # precedence: explicit config option > saved selection
    if is_real_mac(CFG_MAC):
        set_mac(CFG_MAC, "config")
    else:
        saved = load_saved_mac()
        if is_real_mac(saved):
            set_mac(saved, "saved")
    if is_real_mac(STATE["mac"]):
        if is_paired(STATE["mac"]):
            STATE.update(paired=True, status="paired")
            log(f"{STATE['mac']} already paired — starting bridge.")
            start_bridge()
        else:
            log(f"Meter {STATE['mac']} not paired yet — open the panel and press 'Pair selected'.")
    else:
        log("No meter selected. Press 'Scan for meter' and pick your meter (name B2200…).")

if __name__ == "__main__":
    _boot()
    app.run(host="0.0.0.0", port=int(os.environ.get("INGRESS_PORT", "8099")))
