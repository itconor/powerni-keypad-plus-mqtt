#!/usr/bin/env python3
"""PowerNI keypad+ add-on — ingress pairing UI + bridge supervisor.

Runs as the add-on's ingress web app. It lets you pair the meter to the Home
Assistant host's Bluetooth adapter from within HA (no SSH / bluetoothctl by hand):
click "Pair", and the 6-digit passkey the host generates is shown big on the page
for you to type on the meter's keypad.

It also supervises the actual reader (keypad_meter.py): once the meter is paired,
the bridge is (re)started automatically. During a pairing attempt the bridge is
paused so it doesn't hold the meter's single Bluetooth connection.
"""
import os, re, sys, time, threading, subprocess, collections
from flask import Flask, jsonify, render_template_string

MAC  = os.environ.get("METER_MAC", "").strip()
app  = Flask(__name__)

# ---- shared state ---------------------------------------------------------
STATE = {
    "mac": MAC,
    "paired": False,
    "pairing": False,
    "passkey": "",
    "status": "idle",
    "lines": collections.deque(maxlen=40),
    "bridge": "stopped",
    "bridge_last": "",
}
_bridge_proc = None
_lock = threading.Lock()

def log(msg):
    STATE["lines"].append(f"{time.strftime('%H:%M:%S')}  {msg}")

# ---- bluetooth helpers ----------------------------------------------------
def _btctl(*cmds, timeout=15):
    """Run one-shot bluetoothctl commands, return combined output."""
    p = subprocess.run(["bluetoothctl"], input="\n".join(cmds) + "\nquit\n",
                       capture_output=True, text=True, timeout=timeout)
    return p.stdout + p.stderr

def is_paired(mac):
    try:
        out = _btctl(f"info {mac}")
        return re.search(r"Paired:\s*yes", out, re.I) is not None
    except Exception:
        return False

def do_pair(mac):
    """Drive an interactive bluetoothctl pairing, surfacing the passkey."""
    try:
        import pexpect
    except Exception:
        STATE["status"] = "error: pexpect missing"; STATE["pairing"] = False; return
    stop_bridge()
    STATE.update(pairing=True, passkey="", status="starting…")
    log(f"Pairing {mac} …")
    try:
        child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=90)
        for c in ("power on", "agent KeyboardDisplay", "default-agent",
                  "pairable on", "scan on"):
            child.sendline(c); time.sleep(0.4)
        STATE["status"] = "scanning for the meter…"
        log("Scanning… make sure the meter isn't connected to your phone.")
        time.sleep(8)
        child.sendline(f"pair {mac}")
        pats = [r"Passkey:\s*(\d{6})", r"Enter passkey", r"Confirm passkey",
                r"Pairing successful", r"Failed to pair", r"not available",
                r"org\.bluez\.Error", pexpect.TIMEOUT, pexpect.EOF]
        while True:
            i = child.expect(pats, timeout=90)
            if i == 0:
                key = child.match.group(1)
                STATE.update(passkey=key, status="TYPE THIS ON THE METER")
                log(f"Passkey {key} — type it on the meter keypad now.")
            elif i in (1, 2):
                child.sendline("yes")  # confirmation variant
            elif i == 3:
                STATE.update(status="paired", paired=True, pairing=False)
                log("Pairing successful ✔")
                try: _btctl(f"trust {mac}", "scan off")
                except Exception: pass
                child.sendline("quit"); break
            elif i in (4, 5, 6):
                STATE.update(status="failed — retry", pairing=False)
                log("Pairing failed. Ensure the meter is in range and not connected elsewhere.")
                child.sendline("quit"); break
            else:  # TIMEOUT / EOF
                STATE.update(status="timed out — retry", pairing=False)
                log("Timed out waiting for pairing.")
                break
    except Exception as e:
        STATE.update(status=f"error: {e}", pairing=False)
        log(f"Error: {e}")
    finally:
        STATE["pairing"] = False
        if STATE["paired"]:
            start_bridge()

# ---- bridge supervisor ----------------------------------------------------
def _bridge_reader(proc):
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if line:
            STATE["bridge_last"] = line
            log(f"[bridge] {line}")

def start_bridge():
    global _bridge_proc
    with _lock:
        if _bridge_proc and _bridge_proc.poll() is None:
            return
        log("Starting meter bridge…")
        _bridge_proc = subprocess.Popen([sys.executable, "/keypad_meter.py"],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1)
        STATE["bridge"] = "running"
        threading.Thread(target=_bridge_reader, args=(_bridge_proc,), daemon=True).start()

def stop_bridge():
    global _bridge_proc
    with _lock:
        if _bridge_proc and _bridge_proc.poll() is None:
            log("Pausing meter bridge for pairing…")
            _bridge_proc.terminate()
            try: _bridge_proc.wait(timeout=5)
            except Exception: _bridge_proc.kill()
        STATE["bridge"] = "stopped"

# ---- routes ---------------------------------------------------------------
PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Meter Pairing</title><style>
body{font-family:system-ui,sans-serif;background:#0b1220;color:#e8eef7;margin:0;padding:18px;max-width:640px}
h1{font-size:19px;margin:0 0 4px} .mu{color:#93a2bd;font-size:13px}
.card{background:#131c30;border:1px solid #24334f;border-radius:12px;padding:16px;margin:14px 0}
button{background:#2f6df6;border:0;color:#fff;font-size:15px;font-weight:600;padding:11px 18px;border-radius:9px;cursor:pointer}
button:disabled{opacity:.5;cursor:default} .key{font-size:52px;font-weight:800;letter-spacing:8px;text-align:center;color:#ffd23f;margin:8px 0}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700}
.ok{background:#0f2e1b;color:#37d67a} .bad{background:#3a1414;color:#ff6b6b} .idle{background:#1e2b45;color:#93a2bd}
pre{background:#0a1120;border:1px solid #24334f;border-radius:8px;padding:10px;max-height:230px;overflow:auto;font-size:12px;white-space:pre-wrap}
code{background:#0a1120;padding:2px 6px;border-radius:5px}
</style></head><body>
<h1>PowerNI keypad+ — Bluetooth pairing</h1>
<div class=mu>Meter <code id=mac>{{mac}}</code></div>

<div class=card>
  <div>Status: <span id=status class="pill idle">idle</span>
       &nbsp; Bridge: <span id=bridge class="pill idle">stopped</span></div>
  <div id=keywrap style="display:none">
    <div class=mu style="margin-top:10px">Type this on the meter keypad now:</div>
    <div class=key id=key>––––––</div>
  </div>
  <div style="margin-top:12px">
    <button id=pair onclick="pair()">Pair meter</button>
    <button id=unpair onclick="unpair()" style="background:#38445e">Remove pairing</button>
  </div>
  <div class=mu style="margin-top:10px">
    Make sure the meter isn't connected to your phone (single connection only).
    Press <b>Pair meter</b>, then watch for the code above and enter it on the meter.
  </div>
</div>

<div class=card><div class=mu>Log</div><pre id=log></pre></div>

<script>
function cls(el,c){el.className='pill '+c}
async function pair(){ await fetch('pair',{method:'POST'}); }
async function unpair(){ await fetch('unpair',{method:'POST'}); }
async function tick(){
  try{
    const s = await (await fetch('state')).json();
    const st=document.getElementById('status'); st.textContent=s.status;
    cls(st, s.paired?'ok':(s.status.includes('fail')||s.status.includes('error')?'bad':'idle'));
    const br=document.getElementById('bridge'); br.textContent=s.bridge; cls(br, s.bridge=='running'?'ok':'idle');
    document.getElementById('pair').disabled = s.pairing;
    const kw=document.getElementById('keywrap');
    if(s.passkey){ kw.style.display='block'; document.getElementById('key').textContent=s.passkey; }
    else kw.style.display='none';
    document.getElementById('log').textContent = s.lines.join('\\n');
  }catch(e){}
}
setInterval(tick, 1000); tick();
</script></body></html>"""

@app.get("/")
def index():
    return render_template_string(PAGE, mac=MAC or "(not set)")

@app.get("/state")
def state():
    return jsonify({k: (list(v) if isinstance(v, collections.deque) else v)
                    for k, v in STATE.items()})

@app.post("/pair")
def pair():
    if not MAC:
        log("meter_mac is not set in the add-on config."); return ("", 204)
    if not STATE["pairing"]:
        threading.Thread(target=do_pair, args=(MAC,), daemon=True).start()
    return ("", 204)

@app.post("/unpair")
def unpair():
    if MAC:
        stop_bridge()
        _btctl(f"remove {MAC}")
        STATE.update(paired=False, status="removed", passkey="")
        log(f"Removed pairing for {MAC}")
    return ("", 204)

def _boot():
    if MAC and is_paired(MAC):
        STATE.update(paired=True, status="paired")
        log("Meter already paired — starting bridge.")
        start_bridge()
    else:
        log("Meter not paired yet. Open this page and press 'Pair meter'.")

if __name__ == "__main__":
    _boot()
    app.run(host="0.0.0.0", port=int(os.environ.get("INGRESS_PORT", "8099")))
