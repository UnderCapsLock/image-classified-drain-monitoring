from flask import Flask, request, jsonify, render_template_string
import os, random, threading, sqlite3
from datetime import datetime, timedelta
from collections import deque, defaultdict

app = Flask(__name__)
MOCK_DB_PATH = "drainwatch_mock.db"

# ── CONFIG ──────────────────────────────────────────────
LABELS        = ["clear", "partial", "full", "blocked"]
ALERT_LABELS  = {"full", "blocked"}
NODE_NAMES    = [f"cameranode{i}" for i in range(1, 21)]
WORKERS       = ["Team Alpha", "Team Bravo", "Team Charlie", "Team Delta", "Team Echo"]
AUTO_CLEAN_AFTER_DAYS = 8   # auto-clean if blocked for this many sim-days

# ── DATABASE ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(MOCK_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS sim_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node TEXT NOT NULL, label TEXT NOT NULL,
            confidence REAL, sim_day REAL, source TEXT, timestamp TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sim_schedule (
            node TEXT PRIMARY KEY, label TEXT, sim_day REAL,
            week_label TEXT, slot TEXT, worker TEXT,
            confirmed INTEGER DEFAULT 0, range_low INTEGER, range_high INTEGER, priority REAL)""")
        conn.commit()

init_db()

def db_write_event(node, label, confidence, sim_day, source, timestamp):
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO sim_events (node,label,confidence,sim_day,source,timestamp) VALUES (?,?,?,?,?,?)",
                (node, label, confidence, round(sim_day, 1), source, timestamp))
            conn.commit()
    except Exception: pass

def db_block_count(node):
    """How many times has this node reached 'blocked' in its history."""
    try:
        with get_db() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sim_events WHERE node=? AND label='blocked'", (node,)
            ).fetchone()[0]
    except Exception: return 0

def db_total_events():
    try:
        with get_db() as conn:
            return conn.execute("SELECT COUNT(*) FROM sim_events").fetchone()[0]
    except Exception: return 0

# ── NODE STATE ────────────────────────────────────────────
def make_node(name):
    fill_days = random.uniform(6, 30)
    start_level = random.randint(0, 3)
    return {
        "name": name, "fill_days": fill_days,
        "progress": float(start_level),
        "label": LABELS[min(start_level, 3)],
        "confidence": round(random.uniform(72, 99), 1),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_since_real": None,    # real datetime for UI display
        "alert_since_sim":  None,    # sim day when alert started
        "locked": False,
        "last_cleaned_sim": 0.0,
        "overflow_sim_days": 0.0,
    }

nodes = {name: make_node(name) for name in NODE_NAMES}
for n in nodes.values():
    if n["label"] in ALERT_LABELS:
        n["alert_since_real"] = datetime.now()
        n["alert_since_sim"]  = 0.0

# ── SIM STATE ─────────────────────────────────────────────
sim_state = {
    "speed_mode":    "hour",
    "sim_time_days": 0.0,
    "paused":        False,
}
SPEED_MAP = {"hour": 1/24, "3hours": 3/24, "day": 1.0}

schedule           = {}
schedule_generated = False
event_log          = deque(maxlen=200)

# ── HELPERS ───────────────────────────────────────────────
def label_from_progress(p):
    if p < 1.0: return "clear"
    if p < 2.0: return "partial"
    if p < 3.0: return "full"
    return "blocked"

def fmt_sim_duration(sim_days_elapsed):
    """Format a sim-day duration in whole hours."""
    total_hours = int(sim_days_elapsed * 24)
    if total_hours < 1: return "< 1h"
    if total_hours < 24: return f"{total_hours}h"
    d, h = divmod(total_hours, 24)
    return f"{d}d {h}h" if h else f"{d}d"

def fmt_sim_time(days):
    d = int(days)
    h = int((days - d) * 24)
    return f"Day {d}, {h:02d}:00"

def priority_score(node_name):
    """
    Trend AI score — mix of:
    - Current severity (blocked=5, full=3, partial=1, clear=0)
    - Days since last cleaned (capped)
    - Historical block frequency from DB
    """
    n = nodes[node_name]
    level_score = {"clear":0,"partial":1,"full":3,"blocked":5}.get(n["label"], 0)
    days_dirty  = sim_state["sim_time_days"] - n["last_cleaned_sim"]
    time_score  = min(days_dirty / 20.0, 3.0)
    freq_score  = min(db_block_count(node_name) * 0.5, 3.0)
    return round(level_score + time_score + freq_score, 2)

def generate_schedule():
    """
    Build a 4-week Mon–Fri schedule, 2 slots per day (Morning / Afternoon).
    One crew. Prioritise by trend AI score.
    Slots fill up to 40 slots total (4 weeks × 5 days × 2 slots).
    """
    global schedule, schedule_generated
    schedule = {}

    sorted_nodes = sorted(NODE_NAMES, key=priority_score, reverse=True)

    # Build 4 weeks of Mon–Fri slots
    slots = []
    week_start = datetime.now()
    # advance to next Monday
    days_ahead = (7 - week_start.weekday()) % 7
    if days_ahead == 0: days_ahead = 7
    week_start = week_start + timedelta(days=days_ahead)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    for week in range(4):
        for day_offset in range(5):   # Mon=0 … Fri=4
            day_date = week_start + timedelta(weeks=week, days=day_offset)
            week_label = f"Week {week+1} — {day_date.strftime('%b %d')}"
            day_label  = day_date.strftime("%A %b %d")
            for slot in ["Morning", "Afternoon"]:
                slots.append({"week_label": week_label, "day_label": day_label,
                               "slot": slot, "date": day_date})

    for i, node_name in enumerate(sorted_nodes):
        if i >= len(slots): break
        sl  = slots[i]
        lbl = nodes[node_name]["label"]
        score = priority_score(node_name)

        if lbl == "blocked":     range_low, range_high = 1, 3
        elif lbl == "full":      range_low, range_high = 3, 7
        elif lbl == "partial":   range_low, range_high = 10, 20
        else:                    range_low, range_high = 20, 30

        worker = WORKERS[i % len(WORKERS)]

        schedule[node_name] = {
            "week_label": sl["week_label"],
            "day_label":  sl["day_label"],
            "slot":       sl["slot"],
            "date_str":   sl["date"].strftime("%Y-%m-%d"),
            "worker":     worker,
            "confirmed":  False,
            "range_low":  range_low,
            "range_high": range_high,
            "label":      lbl,
            "priority":   score,
        }

    schedule_generated = True

    # Persist to DB
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM sim_schedule")
            for node_name, s in schedule.items():
                conn.execute("""INSERT OR REPLACE INTO sim_schedule
                    (node,label,sim_day,week_label,slot,worker,confirmed,range_low,range_high,priority)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (node_name, s["label"], sim_state["sim_time_days"],
                     f"{s['day_label']} {s['slot']}", s["slot"], s["worker"],
                     0, s["range_low"], s["range_high"], s["priority"]))
            conn.commit()
    except Exception: pass

# ── SIM TICK ──────────────────────────────────────────────
def sim_tick():
    threading.Timer(1.0, sim_tick).start()
    if sim_state["paused"]: return

    speed   = SPEED_MAP[sim_state["speed_mode"]]
    dt_days = speed
    sim_state["sim_time_days"] += dt_days

    for name in NODE_NAMES:
        n = nodes[name]

        # Auto-clean if blocked too long
        if n["label"] == "blocked" and n["alert_since_sim"] is not None:
            blocked_for = sim_state["sim_time_days"] - n["alert_since_sim"]
            if blocked_for >= AUTO_CLEAN_AFTER_DAYS:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                n.update({"label":"clear","progress":0.0,"confidence":99.0,
                          "timestamp":ts,"alert_since_real":None,"alert_since_sim":None,
                          "overflow_sim_days":0.0,"locked":False,
                          "last_cleaned_sim":sim_state["sim_time_days"]})
                entry = {"node":name,"label":"clear","timestamp":ts,"confidence":99.0,
                         "sim_day":round(sim_state["sim_time_days"],1),"source":"auto-clean"}
                event_log.appendleft(entry)
                db_write_event(name,"clear",99.0,sim_state["sim_time_days"],"auto-clean",ts)
                schedule.pop(name, None)
                continue

        if n["locked"]:
            if n["label"] == "blocked":
                n["overflow_sim_days"] += dt_days
            continue

        if n["label"] == "blocked":
            n["overflow_sim_days"] += dt_days
            continue

        # Advance fill progress
        rate = 4.0 / n["fill_days"]
        old_label = n["label"]
        n["progress"] = min(n["progress"] + rate * dt_days, 4.0)
        new_label = label_from_progress(n["progress"])
        n["confidence"] = round(random.uniform(80, 99), 1)
        n["timestamp"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if new_label != old_label:
            n["label"] = new_label
            if new_label in ALERT_LABELS and old_label not in ALERT_LABELS:
                n["alert_since_real"] = datetime.now()
                n["alert_since_sim"]  = sim_state["sim_time_days"]
            elif new_label not in ALERT_LABELS:
                n["alert_since_real"] = None
                n["alert_since_sim"]  = None
            entry = {"node":name,"label":new_label,"timestamp":n["timestamp"],
                     "confidence":n["confidence"],"sim_day":round(sim_state["sim_time_days"],1),"source":"auto"}
            event_log.appendleft(entry)
            db_write_event(name,new_label,n["confidence"],sim_state["sim_time_days"],"auto",n["timestamp"])

sim_tick()

# ── DASHBOARD HTML ────────────────────────────────────────
DASHBOARD_HTML = r"""
<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>DrainWatch MOCK</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{--bg:#0a0f14;--surface:#111820;--s2:#162030;--border:#1e2a35;--text:#e2e8f0;--muted:#4a6070;--accent:#f59e0b;--clear:#22c55e;--partial:#f59e0b;--full:#f97316;--blocked:#ef4444;}
body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;font-size:14px;}
header{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:20;flex-wrap:wrap;gap:10px;}
.wordmark{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:17px;letter-spacing:.08em;color:var(--accent);}
.wordmark span{color:var(--text);}
.speed-bar{display:flex;align-items:center;gap:10px;}
.speed-label{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:.12em;}
.speed-btns{display:flex;gap:6px;}
.spd{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.07em;padding:6px 14px;border-radius:4px;border:1px solid var(--border);background:var(--s2);color:var(--muted);cursor:pointer;transition:all .1s;}
.spd:hover{border-color:var(--accent);color:var(--accent);}
.spd.active{border-color:var(--accent);color:var(--accent);background:#f59e0b20;font-weight:600;}
.sim-clock{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--text);letter-spacing:.05em;min-width:160px;}
.mock-pill{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--accent);letter-spacing:.1em;border:1px solid var(--accent);border-radius:4px;padding:4px 10px;}
.page{padding:24px 28px;display:flex;flex-direction:column;gap:28px;}
.section-label{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.18em;color:var(--muted);text-transform:uppercase;margin-bottom:12px;}
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 18px;}
.stat-card .val{font-family:'IBM Plex Mono',monospace;font-size:32px;font-weight:600;line-height:1;margin-bottom:5px;}
.stat-card .lbl{font-size:11px;color:var(--muted);letter-spacing:.06em;}
.stat-card .nodes-list{margin-top:8px;padding-top:8px;border-top:1px solid var(--border);font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);line-height:1.7;min-height:16px;}
.stat-card.clear .val{color:var(--clear);}.stat-card.partial .val{color:var(--partial);}.stat-card.full .val{color:var(--full);}.stat-card.blocked .val{color:var(--blocked);}
.alerts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;}
.alert-card{background:var(--surface);border:1px solid #ef444430;border-left:3px solid var(--blocked);border-radius:6px;padding:12px 14px;}
.alert-card.full{border-color:#f9731630;border-left-color:var(--full);}
.alert-card .alert-node{font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;letter-spacing:.06em;margin-bottom:3px;}
.alert-card.blocked .alert-node{color:var(--blocked);}.alert-card.full .alert-node{color:var(--full);}
.alert-card .alert-meta{font-size:11px;color:var(--muted);margin-bottom:3px;}
.alert-card .alert-duration{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;color:var(--text);}
.no-alerts{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);letter-spacing:.1em;padding:8px 0;}
/* NODE GRID */
.node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;}
.node-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;transition:border .15s;}
.node-card.locked{border-color:var(--accent);}
.node-card.alert-full{border-color:#f9731640;}.node-card.alert-blocked{border-color:#ef444440;}
.node-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;}
.node-name{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;letter-spacing:.05em;}
.lock-badge{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--accent);border:1px solid var(--accent);border-radius:3px;padding:1px 5px;}
.progress-wrap{margin:6px 0;height:5px;background:var(--border);border-radius:3px;overflow:hidden;}
.progress-fill{height:100%;border-radius:3px;transition:width .8s;}
.progress-fill.clear{background:var(--clear);}.progress-fill.partial{background:var(--partial);}.progress-fill.full{background:var(--full);}.progress-fill.blocked{background:var(--blocked);}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;border:1px solid currentColor;}
.badge.clear{color:var(--clear);background:#22c55e14;}.badge.partial{color:var(--partial);background:#f59e0b14;}.badge.full{color:var(--full);background:#f9731614;}.badge.blocked{color:var(--blocked);background:#ef444414;}.badge.unknown{color:var(--muted);background:#4a607014;}
.node-info{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
.node-fill-label{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--muted);}
/* Override controls — clear labelled buttons */
.override-label{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:.1em;margin-bottom:4px;}
.node-controls{display:grid;grid-template-columns:1fr 1fr;gap:4px;}
.ctrl-btn{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.05em;padding:5px 6px;border-radius:4px;border:1px solid var(--border);background:var(--s2);color:var(--text);cursor:pointer;transition:all .12s;text-align:center;}
.ctrl-btn:hover{border-color:var(--accent);color:var(--accent);}
.ctrl-btn.sel-clear{border-color:var(--clear);color:var(--clear);background:#22c55e14;}
.ctrl-btn.sel-partial{border-color:var(--partial);color:var(--partial);background:#f59e0b14;}
.ctrl-btn.sel-full{border-color:var(--full);color:var(--full);background:#f9731614;}
.ctrl-btn.sel-blocked{border-color:var(--blocked);color:var(--blocked);background:#ef444414;}
.ctrl-btn.auto-btn{grid-column:span 2;border-color:var(--muted);color:var(--muted);font-size:9px;}
.ctrl-btn.clean-btn{grid-column:span 2;border-color:var(--clear);color:var(--clear);background:#22c55e14;}
/* SCHEDULE */
.gen-btn{font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:.08em;padding:10px 24px;border-radius:6px;border:1px solid var(--accent);background:#f59e0b14;color:var(--accent);cursor:pointer;transition:all .2s;margin-bottom:20px;display:inline-block;}
.gen-btn:hover{background:#f59e0b30;}
.need-days{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);padding:12px 0;letter-spacing:.08em;}
.week-block{margin-bottom:24px;}
.week-title{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;color:var(--accent);text-transform:uppercase;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border);}
.day-row{display:flex;gap:0;margin-bottom:2px;}
.day-label-col{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);width:130px;flex-shrink:0;padding:8px 12px 8px 0;border-right:1px solid var(--border);}
.slots-col{flex:1;display:flex;flex-direction:column;gap:4px;padding-left:12px;}
.slot-entry{display:flex;align-items:center;gap:10px;padding:7px 12px;background:var(--surface);border:1px solid var(--border);border-radius:5px;flex-wrap:wrap;}
.slot-entry.confirmed{border-color:#22c55e40;background:#22c55e08;}
.slot-time{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);min-width:80px;}
.slot-node{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;min-width:110px;}
.slot-range{font-size:11px;color:var(--muted);}
.slot-worker{font-size:11px;color:var(--text);}
.slot-priority{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid var(--border);color:var(--muted);}
.slot-priority.high{border-color:var(--blocked);color:var(--blocked);}.slot-priority.med{border-color:var(--full);color:var(--full);}.slot-priority.low{border-color:var(--clear);color:var(--clear);}
.conf-badge{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--clear);border:1px solid var(--clear);border-radius:3px;padding:2px 6px;margin-left:auto;}
.confirm-btn{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.07em;padding:4px 10px;border-radius:4px;border:1px solid var(--accent);background:#f59e0b14;color:var(--accent);cursor:pointer;margin-left:auto;}
.empty-slot{padding:7px 12px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);font-style:italic;}
/* LOG */
.log-wrap{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;max-height:260px;overflow-y:auto;}
.log-entry{display:flex;align-items:flex-start;gap:10px;padding:8px 16px;border-bottom:1px solid var(--border);}
.log-entry:last-child{border-bottom:none;}
.log-dot{width:7px;height:7px;border-radius:50%;margin-top:4px;flex-shrink:0;}
.log-dot.clear{background:var(--clear);}.log-dot.partial{background:var(--partial);}.log-dot.full{background:var(--full);}.log-dot.blocked{background:var(--blocked);}.log-dot.unknown{background:var(--muted);}
.log-node{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;}
.log-status{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;margin-top:1px;}
.log-status.clear{color:var(--clear);}.log-status.partial{color:var(--partial);}.log-status.full{color:var(--full);}.log-status.blocked{color:var(--blocked);}
.log-meta{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--muted);margin-top:2px;}
.src-tag{font-size:9px;padding:1px 4px;border-radius:3px;border:1px solid var(--muted);color:var(--muted);margin-left:5px;}
.src-tag.manual{border-color:var(--accent);color:var(--accent);}
.src-tag.auto-clean{border-color:var(--clear);color:var(--clear);}
.empty-log{padding:32px 20px;text-align:center;color:var(--muted);font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.1em;}
::-webkit-scrollbar{width:4px;}::-webkit-scrollbar-track{background:transparent;}::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
.toast{position:fixed;bottom:24px;right:24px;background:var(--surface);border:1px solid var(--accent);color:var(--accent);font-family:'IBM Plex Mono',monospace;font-size:12px;padding:10px 18px;border-radius:6px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:99;}
.toast.show{opacity:1;}
</style></head><body>

<header>
  <div class="wordmark">DRAIN<span>WATCH</span> <span style="font-size:13px;letter-spacing:.15em;">MOCK</span></div>
  <div class="speed-bar">
    <span class="speed-label">SIM SPEED</span>
    <div class="speed-btns" id="speed-btns">
      <button class="spd {% if speed=='hour' %}active{% endif %}" id="spd-hour"   onclick="setSpeed('hour')">1 HR/S</button>
      <button class="spd {% if speed=='3hours' %}active{% endif %}" id="spd-3hours" onclick="setSpeed('3hours')">3 HR/S</button>
      <button class="spd {% if speed=='day' %}active{% endif %}" id="spd-day"    onclick="setSpeed('day')">1 DAY/S</button>
    </div>
    <div class="sim-clock" id="sim-clock">{{ sim_time_str }}</div>
  </div>
  <div class="mock-pill">⚡ PORT 5001 — {{ total_events }} events</div>
</header>

<div class="page">

  <!-- STATS -->
  <div>
    <div class="section-label">Network Summary — 20 simulated nodes · auto-clean after {{ auto_clean_days }}d blocked</div>
    <div class="stats-row">
      {% for status in ["clear","partial","full","blocked"] %}
      <div class="stat-card {{ status }}">
        <div class="val">{{ counts[status] }}</div>
        <div class="lbl">{{ status | capitalize }}</div>
        <div class="nodes-list">
          {% if nodes_by_status[status] %}{% for n in nodes_by_status[status] %}{{ n }}<br>{% endfor %}{% else %}—{% endif %}
        </div>
      </div>{% endfor %}
    </div>
  </div>

  <!-- ALERTS -->
  <div>
    <div class="section-label">⚠ Active Alerts — L3 Full &amp; L4 Blocked</div>
    {% if alerts %}<div class="alerts-grid">
      {% for a in alerts %}
      <div class="alert-card {{ a.label }}">
        <div class="alert-node">{{ a.node }}</div>
        <div class="alert-meta">{{ a.label|upper }} — L{{ '3' if a.label=='full' else '4' }}</div>
        <div class="alert-duration">{{ a.duration }} in sim-time</div>
      </div>{% endfor %}
    </div>
    {% else %}<div class="no-alerts">ALL NODES CLEAR — NO ACTIVE ALERTS</div>{% endif %}
  </div>

  <!-- NODE GRID -->
  <div>
    <div class="section-label">Camera Nodes — progress bars show fill level · click a status to lock it</div>
    <div class="node-grid">
      {% for name in node_list %}
      {% set n = node_states[name] %}
      {% set cls = n.label %}
      {% set pct = [[((n.progress / 4.0)*100)|int, 0]|max, 100]|min %}
      <div class="node-card {% if n.locked %}locked{% endif %} {% if n.label in ['full','blocked'] %}alert-{{ n.label }}{% endif %}">
        <div class="node-header">
          <span class="node-name">{{ name }}</span>
          {% if n.locked %}<span class="lock-badge">LOCKED</span>{% endif %}
        </div>
        <div class="node-info">
          <span class="badge {{ cls }}">● {{ n.label }}</span>
          <span class="node-fill-label">{{ pct }}% · {{ "%.0f"|format(n.fill_days) }}d cycle</span>
        </div>
        <div class="progress-wrap">
          <div class="progress-fill {{ cls }}" style="width:{{ pct }}%"></div>
        </div>
        <div class="override-label">SET STATUS</div>
        <div class="node-controls">
          <button class="ctrl-btn {% if n.locked and n.label=='clear' %}sel-clear{% endif %}"   onclick="setNode('{{ name }}','clear')">⬤ Clear</button>
          <button class="ctrl-btn {% if n.locked and n.label=='partial' %}sel-partial{% endif %}" onclick="setNode('{{ name }}','partial')">⬤ Partial</button>
          <button class="ctrl-btn {% if n.locked and n.label=='full' %}sel-full{% endif %}"    onclick="setNode('{{ name }}','full')">⬤ Full</button>
          <button class="ctrl-btn {% if n.locked and n.label=='blocked' %}sel-blocked{% endif %}" onclick="setNode('{{ name }}','blocked')">⬤ Blocked</button>
          {% if n.locked %}
          <button class="ctrl-btn auto-btn" onclick="unlockNode('{{ name }}')">↺ Resume Auto-Sim</button>
          {% endif %}
          {% if n.label in ['full','blocked'] %}
          <button class="ctrl-btn clean-btn" onclick="cleanNode('{{ name }}')">✓ Mark as Cleaned</button>
          {% endif %}
        </div>
      </div>{% endfor %}
    </div>
  </div>

  <!-- SCHEDULE -->
  <div>
    <div class="section-label">Maintenance Schedule — One Crew · Mon–Fri · 2 Drains/Day · 4 Weeks</div>
    {% if sim_days >= 100 or schedule_generated %}
      <button class="gen-btn" onclick="generateSchedule()">
        {% if schedule_generated %}↻ Regenerate (Trend AI){% else %}⚡ Generate Schedule (Trend AI){% endif %}
      </button>
    {% else %}
      <div class="need-days">SCHEDULE UNLOCKS AT SIM DAY 100 — Currently Day {{ "%.1f"|format(sim_days) }}</div>
    {% endif %}

    {% if weeks %}
      {% for week_name, days in weeks.items() %}
      <div class="week-block">
        <div class="week-title">{{ week_name }}</div>
        {% for day_name, slots in days.items() %}
        <div class="day-row">
          <div class="day-label-col">{{ day_name }}</div>
          <div class="slots-col">
            {% for slot_entry in slots %}
              {% if slot_entry %}
              <div class="slot-entry {% if slot_entry.confirmed %}confirmed{% endif %}">
                <span class="slot-time">{{ slot_entry.slot }}</span>
                <span class="slot-node">{{ slot_entry.node }}</span>
                <span class="badge {{ slot_entry.label }}" style="font-size:9px;padding:2px 6px;">{{ slot_entry.label }}</span>
                <span class="slot-range">{{ slot_entry.range_low }}–{{ slot_entry.range_high }}d window</span>
                <span class="slot-worker">👷 {{ slot_entry.worker }}</span>
                {% set pri = 'high' if slot_entry.priority > 5 else ('med' if slot_entry.priority > 2 else 'low') %}
                <span class="slot-priority {{ pri }}">P{{ "%.1f"|format(slot_entry.priority) }}</span>
                {% if slot_entry.confirmed %}
                  <span class="conf-badge">✓ CONFIRMED</span>
                {% else %}
                  <button class="confirm-btn" onclick="confirmSlot('{{ slot_entry.node }}')">Confirm</button>
                {% endif %}
              </div>
              {% else %}
              <div class="empty-slot">— available —</div>
              {% endif %}
            {% endfor %}
          </div>
        </div>{% endfor %}
      </div>{% endfor %}
    {% endif %}
  </div>

  <!-- LOG -->
  <div>
    <div class="section-label">Event Log</div>
    <div class="log-wrap">
      {% if entries %}{% for e in entries %}
      <div class="log-entry">
        <div class="log-dot {{ e.label }}"></div>
        <div>
          <div class="log-node">{{ e.node }} <span class="src-tag {% if e.source=='manual' %}manual{% elif e.source=='auto-clean' %}auto-clean{% endif %}">{{ e.source }}</span></div>
          <div class="log-status {{ e.label }}">{{ e.label }}</div>
          <div class="log-meta">{{ e.timestamp }} · sim day {{ e.sim_day }} · {{ e.confidence }}%</div>
        </div>
      </div>{% endfor %}
      {% else %}<div class="empty-log">NO EVENTS YET</div>{% endif %}
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>
<script>
function showToast(msg){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2000);
}
function post(url,body){return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

// Speed buttons — instant visual feedback, no page reload needed
function setSpeed(mode){
  document.querySelectorAll('.spd').forEach(b=>b.classList.remove('active'));
  document.getElementById('spd-'+mode).classList.add('active');
  post('/speed',{mode}).then(()=>showToast('Speed → '+mode));
}

function setNode(node,label){
  post('/override',{node,label}).then(()=>{
    showToast(node+' → '+label.toUpperCase()+' (locked)');
    setTimeout(()=>location.reload(),400);
  });
}
function unlockNode(node){
  post('/unlock',{node}).then(()=>{
    showToast(node+' → auto-sim');
    setTimeout(()=>location.reload(),400);
  });
}
function cleanNode(node){
  post('/clean',{node}).then(()=>{
    showToast(node+' cleaned → CLEAR');
    setTimeout(()=>location.reload(),400);
  });
}
function generateSchedule(){
  post('/generate_schedule',{}).then(r=>r.json()).then(d=>{
    showToast('Schedule generated — '+d.count+' drains');
    setTimeout(()=>location.reload(),500);
  });
}
function confirmSlot(node){
  post('/confirm_schedule',{node}).then(()=>{
    showToast(node+' confirmed ✓');
    setTimeout(()=>location.reload(),400);
  });
}

// Live clock every second — no reload needed
function updateClock(){
  fetch('/clock').then(r=>r.json()).then(d=>{
    const el=document.getElementById('sim-clock');
    if(el) el.textContent=d.sim_time_str;
  }).catch(()=>{});
}
setInterval(updateClock,1000);

// Full page reload every 10s for node states
setTimeout(()=>location.reload(),10000);
</script>
</body></html>
"""

# ── ROUTES ────────────────────────────────────────────────
@app.route("/")
def dashboard():
    counts = {l:0 for l in LABELS}
    nodes_by_status = {l:[] for l in LABELS}
    for name in NODE_NAMES:
        lbl = nodes[name]["label"]
        if lbl in counts:
            counts[lbl] += 1
            nodes_by_status[lbl].append(name)

    alerts = []
    for name in NODE_NAMES:
        n = nodes[name]
        if n["label"] in ALERT_LABELS and n["alert_since_sim"] is not None:
            elapsed_sim = sim_state["sim_time_days"] - n["alert_since_sim"]
            alerts.append({"node":name,"label":n["label"],
                           "duration":fmt_sim_duration(elapsed_sim)})

    # Build weekly schedule display
    from collections import OrderedDict
    weeks = OrderedDict()
    if schedule:
        for node_name, s in schedule.items():
            w = s["week_label"]
            d = s["day_label"]
            if w not in weeks: weeks[w] = OrderedDict()
            if d not in weeks[w]: weeks[w][d] = [None, None]
            slot_idx = 0 if s["slot"] == "Morning" else 1
            weeks[w][d][slot_idx] = {**s, "node": node_name}

    return render_template_string(DASHBOARD_HTML,
        node_list=NODE_NAMES, node_states=nodes,
        counts=counts, nodes_by_status=nodes_by_status,
        alerts=alerts, weeks=weeks,
        schedule_generated=schedule_generated,
        sim_days=sim_state["sim_time_days"],
        sim_time_str=fmt_sim_time(sim_state["sim_time_days"]),
        speed=sim_state["speed_mode"],
        auto_clean_days=AUTO_CLEAN_AFTER_DAYS,
        total_events=db_total_events(),
        entries=list(event_log)[:60])

@app.route("/clock")
def clock():
    return jsonify({"sim_time_str": fmt_sim_time(sim_state["sim_time_days"]),
                    "sim_days": round(sim_state["sim_time_days"], 2)})

@app.route("/speed", methods=["POST"])
def set_speed():
    data = request.get_json(force=True)
    mode = data.get("mode","hour")
    if mode in SPEED_MAP:
        sim_state["speed_mode"] = mode
    return jsonify({"status":"ok","mode":sim_state["speed_mode"]})

@app.route("/override", methods=["POST"])
def override():
    data  = request.get_json(force=True)
    name  = data.get("node")
    label = data.get("label","clear").lower()
    if name not in nodes: return jsonify({"error":"unknown node"}),400
    n = nodes[name]
    old_label = n["label"]
    n.update({"label":label,"progress":{"clear":0.0,"partial":1.0,"full":2.0,"blocked":3.5}[label],
              "confidence":99.0,"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"locked":True})
    if label in ALERT_LABELS and old_label not in ALERT_LABELS:
        n["alert_since_real"] = datetime.now()
        n["alert_since_sim"]  = sim_state["sim_time_days"]
    elif label not in ALERT_LABELS:
        n["alert_since_real"] = None
        n["alert_since_sim"]  = None
    entry = {"node":name,"label":label,"timestamp":n["timestamp"],"confidence":99.0,
             "sim_day":round(sim_state["sim_time_days"],1),"source":"manual"}
    event_log.appendleft(entry)
    db_write_event(name,label,99.0,sim_state["sim_time_days"],"manual",n["timestamp"])
    return jsonify({"status":"ok"})

@app.route("/unlock", methods=["POST"])
def unlock():
    data = request.get_json(force=True)
    name = data.get("node")
    if name in nodes: nodes[name]["locked"] = False
    return jsonify({"status":"ok"})

@app.route("/clean", methods=["POST"])
def clean():
    data = request.get_json(force=True)
    name = data.get("node")
    if name not in nodes: return jsonify({"error":"unknown node"}),400
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nodes[name].update({"label":"clear","progress":0.0,"confidence":99.0,"timestamp":ts,
                         "alert_since_real":None,"alert_since_sim":None,
                         "overflow_sim_days":0.0,"locked":False,
                         "last_cleaned_sim":sim_state["sim_time_days"]})
    schedule.pop(name, None)
    entry = {"node":name,"label":"clear","timestamp":ts,"confidence":99.0,
             "sim_day":round(sim_state["sim_time_days"],1),"source":"cleaned"}
    event_log.appendleft(entry)
    db_write_event(name,"clear",99.0,sim_state["sim_time_days"],"cleaned",ts)
    return jsonify({"status":"ok"})

@app.route("/generate_schedule", methods=["POST"])
def gen_schedule():
    generate_schedule()
    return jsonify({"status":"ok","count":len(schedule)})

@app.route("/confirm_schedule", methods=["POST"])
def confirm_sched():
    data = request.get_json(force=True)
    name = data.get("node")
    if name in schedule:
        schedule[name]["confirmed"] = True
        try:
            with get_db() as conn:
                conn.execute("UPDATE sim_schedule SET confirmed=1 WHERE node=?",(name,))
                conn.commit()
        except Exception: pass
    return jsonify({"status":"ok"})

@app.route("/data")
def data():
    return jsonify({"sim_days":sim_state["sim_time_days"],
                    "total_events":db_total_events(),
                    "log":list(event_log)[:20]})

@app.route("/clear_db", methods=["POST"])
def clear_db():
    global schedule, schedule_generated
    with get_db() as conn:
        conn.execute("DELETE FROM sim_events")
        conn.execute("DELETE FROM sim_schedule")
        conn.commit()
    event_log.clear()
    schedule = {}
    schedule_generated = False
    for name in NODE_NAMES:
        nodes[name].update(make_node(name))
    return jsonify({"status":"ok","message":"Mock DB cleared"})

@app.route("/history/<node>")
def node_history(node):
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT label,confidence,sim_day,source,timestamp FROM sim_events WHERE node=? ORDER BY id DESC LIMIT 50",
                (node,)).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception: return jsonify([])

if __name__ == "__main__":
    print("\n  DrainWatch MOCK server running.")
    print(f"  Database  → {MOCK_DB_PATH}")
    print("  Dashboard → http://localhost:5001\n")
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
