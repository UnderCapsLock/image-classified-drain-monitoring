from flask import Flask, request, jsonify, render_template_string
import base64, os, sqlite3
from datetime import datetime
from collections import deque

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DB_PATH = "drainwatch_live.db"

LABELS       = ["clear", "partial", "blocked"]
ALERT_LABELS = {"blocked"}
NODE_NAME    = "cameranode-1"   # single node

# ── LOAD AI CLASSIFIER ────────────────────────────────────
classifier = None
try:
    from classify import DrainClassifier
    classifier = DrainClassifier()
    print("  ✓ AI classifier loaded — server will classify images automatically")
except Exception as e:
    print(f"  ⚠  No classifier loaded ({e}) — using label from ESP32 payload")

node_state = {
    "label": "unknown", "confidence": None,
    "timestamp": None, "image_b64": None, "alert_since": None,
}
event_log = deque(maxlen=50)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node TEXT NOT NULL, label TEXT NOT NULL,
            confidence REAL, image_path TEXT, timestamp TEXT NOT NULL)""")
        conn.commit()

init_db()

with get_db() as conn:
    row = conn.execute(
        "SELECT label,confidence,timestamp FROM readings WHERE node=? ORDER BY id DESC LIMIT 1",
        (NODE_NAME,)).fetchone()
    if row:
        node_state["label"]      = row["label"]
        node_state["confidence"] = row["confidence"]
        node_state["timestamp"]  = row["timestamp"]
    rows = conn.execute(
        "SELECT node,label,confidence,timestamp FROM readings ORDER BY id DESC LIMIT 50"
    ).fetchall()
    for r in reversed(rows):
        event_log.appendleft(dict(r))

def fmt_duration(since_dt):
    if since_dt is None: return None
    delta = datetime.now() - since_dt
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    if h:  return f"{h}h {m}m"
    if m:  return f"{m}m {s}s"
    return f"{s}s"

def db_total_readings():
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

def db_node_history(limit=12):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT label,confidence,timestamp FROM readings WHERE node=? ORDER BY id DESC LIMIT ?",
            (NODE_NAME, limit)).fetchall()
    return [dict(r) for r in rows]

DASHBOARD_HTML = """
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>DrainWatch — Live</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{--bg:#0a0f14;--surface:#111820;--s2:#162030;--border:#1e2a35;--text:#e2e8f0;--muted:#4a6070;--accent:#00d4ff;--clear:#22c55e;--partial:#f59e0b;--blocked:#ef4444;}
body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;font-size:14px;min-height:100vh;}
header{display:flex;align-items:center;justify-content:space-between;padding:18px 32px;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:10;gap:16px;flex-wrap:wrap;}
.wordmark{font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:20px;letter-spacing:.08em;color:var(--accent);}
.wordmark span{color:var(--text);}
.header-right{display:flex;align-items:center;gap:20px;flex-wrap:wrap;}
.db-stat{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--muted);letter-spacing:.08em;}
.db-stat span{color:var(--accent);font-weight:600;}
.live-pill{display:flex;align-items:center;gap:8px;font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--muted);letter-spacing:.1em;}
.pulse{width:9px;height:9px;border-radius:50%;background:var(--clear);animation:pulse 1.8s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.4;transform:scale(.75);}}

/* Sound toggle */
.sound-toggle{display:flex;align-items:center;gap:8px;background:var(--s2);border:1px solid var(--border);
  border-radius:20px;padding:6px 14px;cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:11px;
  color:var(--muted);letter-spacing:.06em;transition:all .15s;}
.sound-toggle:hover{border-color:var(--accent);}
.sound-toggle.on{border-color:var(--clear);color:var(--clear);background:#22c55e14;}

.page{padding:28px 32px;display:flex;flex-direction:column;gap:28px;max-width:1100px;margin:0 auto;}
.section-label{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;color:var(--muted);text-transform:uppercase;margin-bottom:14px;}

/* Big status banner */
.status-banner{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:24px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;
  transition:border-color .3s, background .3s;}
.status-banner.clear{border-color:#22c55e40;}
.status-banner.partial{border-color:#f59e0b40;}
.status-banner.blocked{border-color:#ef444460;background:#ef44440a;}
.status-left{display:flex;align-items:center;gap:20px;}
.status-dot-big{width:20px;height:20px;border-radius:50%;flex-shrink:0;}
.status-dot-big.clear{background:var(--clear);box-shadow:0 0 20px #22c55e80;}
.status-dot-big.partial{background:var(--partial);box-shadow:0 0 20px #f59e0b80;}
.status-dot-big.blocked{background:var(--blocked);box-shadow:0 0 20px #ef444480;animation:blink 1s infinite;}
@keyframes blink{0%,100%{opacity:1;}50%{opacity:.5;}}
.status-text{font-family:'IBM Plex Mono',monospace;font-size:28px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;}
.status-text.clear{color:var(--clear);}
.status-text.partial{color:var(--partial);}
.status-text.blocked{color:var(--blocked);}
.status-sub{font-size:13px;color:var(--muted);margin-top:4px;}
.status-conf{font-family:'IBM Plex Mono',monospace;font-size:32px;font-weight:700;color:var(--text);}
.status-conf-lbl{font-size:11px;color:var(--muted);text-align:right;letter-spacing:.08em;}

/* Big image */
.image-wrap{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.image-wrap img{width:100%;max-height:560px;object-fit:contain;display:block;background:#000;}
.image-wrap .no-img{width:100%;height:400px;display:flex;align-items:center;justify-content:center;
  color:var(--muted);font-family:'IBM Plex Mono',monospace;font-size:13px;letter-spacing:.12em;background:#0d1a24;}
.image-footer{padding:16px 24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;}
.node-name{font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:600;letter-spacing:.05em;}
.node-ts{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--muted);margin-top:3px;}

/* History strip */
.history-strip{display:flex;gap:6px;flex-wrap:wrap;align-items:center;}
.hist-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0;}
.hist-dot.clear{background:var(--clear);}.hist-dot.partial{background:var(--partial);}.hist-dot.blocked{background:var(--blocked);}
.hist-dot.unknown{background:var(--muted);}

/* Alert box */
.alert-box{background:var(--surface);border:1px solid #ef444440;border-left:4px solid var(--blocked);
  border-radius:10px;padding:20px 24px;}
.alert-box.hidden-alert{display:none;}
.alert-title{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:700;color:var(--blocked);letter-spacing:.1em;margin-bottom:6px;}
.alert-duration{font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:700;color:var(--text);}
.no-alerts{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--muted);letter-spacing:.1em;padding:10px 0;}

/* Log */
.log-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;max-height:280px;overflow-y:auto;}
.log-entry{display:flex;align-items:flex-start;gap:12px;padding:12px 20px;border-bottom:1px solid var(--border);}
.log-entry:last-child{border-bottom:none;}
.log-dot{width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0;}
.log-dot.clear{background:var(--clear);}.log-dot.partial{background:var(--partial);}.log-dot.blocked{background:var(--blocked);}
.log-status{font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;}
.log-status.clear{color:var(--clear);}.log-status.partial{color:var(--partial);}.log-status.blocked{color:var(--blocked);}
.log-meta{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);margin-top:2px;}
.empty-log{padding:32px 20px;text-align:center;color:var(--muted);font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:.1em;}
::-webkit-scrollbar{width:5px;}::-webkit-scrollbar-track{background:transparent;}::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
</style></head><body>

<header>
  <div class="wordmark">DRAIN<span>WATCH</span></div>
  <div class="header-right">
    <div class="sound-toggle" id="soundToggle" onclick="toggleSound()">🔊 SOUND: OFF</div>
    <div class="db-stat">DB READINGS <span id="db-total">{{ total_readings }}</span></div>
    <div class="live-pill"><div class="pulse"></div>LIVE — UPDATING 1s</div>
  </div>
</header>

<div class="page">

  <!-- BIG STATUS BANNER -->
  <div class="status-banner {{ node.label }}" id="statusBanner">
    <div class="status-left">
      <div class="status-dot-big {{ node.label }}" id="statusDot"></div>
      <div>
        <div class="status-text {{ node.label }}" id="statusText">{{ node.label }}</div>
        <div class="status-sub" id="statusSub">{{ node.timestamp if node.timestamp else "no data yet" }}</div>
      </div>
    </div>
    <div>
      <div class="status-conf" id="statusConf">{{ node.confidence if node.confidence else "—" }}{% if node.confidence %}%{% endif %}</div>
      <div class="status-conf-lbl">CONFIDENCE</div>
    </div>
  </div>

  <!-- ALERT -->
  <div class="alert-box {% if node.label != 'blocked' %}hidden-alert{% endif %}" id="alertBox">
    <div class="alert-title">⚠ DRAIN BLOCKED — ACTION NEEDED</div>
    <div class="alert-duration" id="alertDuration">{{ alert_duration if alert_duration else "0s" }} in this state</div>
  </div>

  <!-- BIG IMAGE -->
  <div>
    <div class="section-label">Live Feed — {{ node_name }}</div>
    <div class="image-wrap">
      {% if node.image_b64 %}
        <img id="liveImg" src="data:image/jpeg;base64,{{ node.image_b64 }}">
      {% else %}
        <img id="liveImg" style="display:none">
        <div class="no-img" id="noImgMsg">AWAITING FEED</div>
      {% endif %}
      <div class="image-footer">
        <div>
          <div class="node-name">{{ node_name }}</div>
          <div class="node-ts" id="footerTs">{{ node.timestamp if node.timestamp else "no data yet" }}</div>
        </div>
        <div class="history-strip" id="historyStrip">
          {% for h in history %}<div class="hist-dot {{ h.label }}" title="{{ h.label }} @ {{ h.timestamp }}"></div>{% endfor %}
        </div>
      </div>
    </div>
  </div>

  <!-- LOG -->
  <div>
    <div class="section-label">Event Log</div>
    <div class="log-wrap" id="logBox">
      {% if entries %}{% for e in entries %}
      <div class="log-entry"><div class="log-dot {{ e.label }}"></div>
        <div><div class="log-status {{ e.label }}">{{ e.label }}</div>
        <div class="log-meta">{{ e.timestamp }}{% if e.confidence %} · {{ e.confidence }}%{% endif %}</div></div>
      </div>{% endfor %}
      {% else %}<div class="empty-log">NO READINGS YET</div>{% endif %}
    </div>
  </div>

</div>

<script>
let soundOn = false;
let lastAlertSoundTime = 0;
const ALERT_INTERVAL_MS = {{ alert_sound_interval_ms }};  // configurable: demo=10000, real=180000

// Simple beep using Web Audio API — no external file needed
function playBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.frequency.value = 880;
    osc.type = 'sine';
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    osc.start(); osc.stop(ctx.currentTime + 0.5);
  } catch(e) { console.log('audio error', e); }
}

function toggleSound() {
  soundOn = !soundOn;
  const btn = document.getElementById('soundToggle');
  btn.textContent = soundOn ? '🔊 SOUND: ON' : '🔊 SOUND: OFF';
  btn.classList.toggle('on', soundOn);
  if (soundOn) playBeep();  // confirm sound works when turned on
}

async function update() {
  try {
    const r = await fetch('/live');
    const d = await r.json();
    const n = d.node;
    const cls = n.label.toLowerCase();

    // Status banner
    const banner = document.getElementById('statusBanner');
    banner.className = 'status-banner ' + cls;
    document.getElementById('statusDot').className = 'status-dot-big ' + cls;
    const st = document.getElementById('statusText');
    st.className = 'status-text ' + cls;
    st.textContent = n.label;
    document.getElementById('statusSub').textContent = n.timestamp || 'no data yet';
    document.getElementById('statusConf').textContent = n.confidence ? n.confidence + '%' : '—';

    // Alert box
    const alertBox = document.getElementById('alertBox');
    if (cls === 'blocked') {
      alertBox.classList.remove('hidden-alert');
      document.getElementById('alertDuration').textContent = (d.alert_duration || '0s') + ' in this state';

      // Sound logic
      if (soundOn) {
        const now = Date.now();
        if (now - lastAlertSoundTime >= ALERT_INTERVAL_MS) {
          playBeep();
          lastAlertSoundTime = now;
        }
      }
    } else {
      alertBox.classList.add('hidden-alert');
      lastAlertSoundTime = 0;  // reset so next block triggers immediately
    }

    // Image
    if (n.image_b64) {
      const img = document.getElementById('liveImg');
      img.style.display = 'block';
      img.src = 'data:image/jpeg;base64,' + n.image_b64;
      const noImg = document.getElementById('noImgMsg');
      if (noImg) noImg.style.display = 'none';
    }
    document.getElementById('footerTs').textContent = n.timestamp || 'no data yet';

    // History
    const hist = document.getElementById('historyStrip');
    if (d.history) {
      hist.innerHTML = d.history.map(h => `<div class="hist-dot ${h.label}" title="${h.label} @ ${h.timestamp}"></div>`).join('');
    }

    // DB counter
    document.getElementById('db-total').textContent = d.total_readings;

    // Log
    const logBox = document.getElementById('logBox');
    if (d.log && d.log.length) {
      logBox.innerHTML = d.log.map(e => `
        <div class="log-entry">
          <div class="log-dot ${e.label.toLowerCase()}"></div>
          <div>
            <div class="log-status ${e.label.toLowerCase()}">${e.label}</div>
            <div class="log-meta">${e.timestamp}${e.confidence ? ' · ' + e.confidence + '%' : ''}</div>
          </div>
        </div>`).join('');
    }

  } catch(e) { console.log('update error', e); }
}

setInterval(update, 1000);
update();
</script>
</body></html>
"""

@app.route("/upload", methods=["POST"])
def upload():
    data = request.get_json(force=True)
    if not data: return jsonify({"error": "No JSON body"}), 400

    label      = data.get("label", "unknown").lower()
    image_b64  = data.get("image", "")
    confidence = data.get("confidence", None)
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if classifier and image_b64:
        try:
            image_bytes       = base64.b64decode(image_b64)
            label, confidence = classifier.predict(image_bytes)
        except Exception as e:
            print(f"  Classifier error: {e} — using payload label")

    if label in ALERT_LABELS:
        if node_state["alert_since"] is None:
            node_state["alert_since"] = datetime.now()
    else:
        node_state["alert_since"] = None

    image_path = None
    if image_b64:
        safe_ts    = timestamp.replace(":", "-").replace(" ", "_")
        image_path = f"{UPLOAD_FOLDER}/{safe_ts}_{label}.jpg"
        try:
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(image_b64))
        except Exception:
            image_path = None

    with get_db() as conn:
        conn.execute(
            "INSERT INTO readings (node,label,confidence,image_path,timestamp) VALUES (?,?,?,?,?)",
            (NODE_NAME, label, confidence, image_path, timestamp))
        conn.commit()

    node_state.update({"label":label,"confidence":confidence,"timestamp":timestamp,"image_b64":image_b64})
    event_log.appendleft({"node":NODE_NAME,"label":label,"timestamp":timestamp,"confidence":confidence})

    return jsonify({"status": "ok", "timestamp": timestamp, "label": label, "confidence": confidence}), 200

@app.route("/")
def dashboard():
    alert_duration = fmt_duration(node_state["alert_since"]) if node_state["alert_since"] else None
    return render_template_string(DASHBOARD_HTML,
        node=node_state, node_name=NODE_NAME,
        history=db_node_history(12),
        entries=list(event_log),
        total_readings=db_total_readings(),
        alert_duration=alert_duration,
        alert_sound_interval_ms=10000,   # 10s for demo — change to 180000 for real 3-min interval
    )

@app.route("/live")
def live():
    alert_duration = fmt_duration(node_state["alert_since"]) if node_state["alert_since"] else None
    return jsonify({
        "node":            node_state,
        "history":         db_node_history(12),
        "total_readings":  db_total_readings(),
        "alert_duration":  alert_duration,
        "log":             list(event_log)[:20],
    })

@app.route("/history")
def history():
    return jsonify(db_node_history(50))

@app.route("/clear_db", methods=["POST"])
def clear_db():
    with get_db() as conn:
        conn.execute("DELETE FROM readings")
        conn.commit()
    event_log.clear()
    node_state.update({"label":"unknown","confidence":None,"timestamp":None,"image_b64":None,"alert_since":None})
    return jsonify({"status": "ok", "message": "Live DB cleared"})

if __name__ == "__main__":
    print("\n  DrainWatch LIVE server running (single node)")
    print(f"  Database  → {DB_PATH}")
    print("  Dashboard → http://localhost:5000")
    print("  Upload    → POST http://localhost:5000/upload\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
