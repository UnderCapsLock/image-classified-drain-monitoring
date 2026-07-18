"""
collect_images_windows.py - fixed JPEG saving
"""
from flask import Flask, request, jsonify, render_template_string
import base64, os
from datetime import datetime

app = Flask(__name__)

CLASSES   = ["clear", "partial", "blocked"]
SAVE_ROOT = "dataset"
counts    = {c: 0 for c in CLASSES}
recent    = []

for c in CLASSES:
    os.makedirs(f"{SAVE_ROOT}/{c}", exist_ok=True)

def save_image(label, raw_bytes):
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = os.path.join(SAVE_ROOT, label, ts + ".jpg")
    # Save raw bytes directly — no base64 encoding
    with open(filepath, "wb") as f:
        f.write(raw_bytes)
    counts[label] += 1
    # Keep base64 only for the review page display
    b64 = base64.b64encode(raw_bytes).decode("utf-8")
    recent.insert(0, {"label": label, "image": b64, "ts": ts})
    if len(recent) > 10:
        recent.pop()
    print(f"  Saved {label} — {len(raw_bytes)} bytes | clear={counts['clear']} partial={counts['partial']} blocked={counts['blocked']}")
    return filepath

@app.route("/upload", methods=["POST"])
def upload():
    data = request.get_json()

    if not data or "image" not in data:
        print("  No JSON image received")
        return jsonify({"error": "no image"}), 400

    class_hint = request.args.get("class", "").lower().strip()
    label = class_hint if class_hint in CLASSES else "clear"

    try:
        raw_bytes = base64.b64decode(data["image"])
    except Exception as e:
        print("  Base64 decode failed:", e)
        return jsonify({"error": "decode failed"}), 400

    save_image(label, raw_bytes)
    return jsonify({"status": "ok"}), 200

@app.route("/relabel", methods=["POST"])
def relabel():
    data    = request.get_json(force=True)
    ts      = data.get("ts")
    old_lbl = data.get("old_label")
    new_lbl = data.get("new_label")
    if not all([ts, old_lbl, new_lbl]):
        return jsonify({"error": "missing fields"}), 400
    old_path = os.path.join(SAVE_ROOT, old_lbl, ts + ".jpg")
    new_path = os.path.join(SAVE_ROOT, new_lbl, ts + ".jpg")
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        counts[old_lbl] = max(0, counts[old_lbl] - 1)
        counts[new_lbl] += 1
        for r in recent:
            if r["ts"] == ts:
                r["label"] = new_lbl
    return jsonify({"status": "ok", "counts": counts})

REVIEW_HTML = """
<!DOCTYPE html><html><head>
<title>DrainWatch — Image Review</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{background:#0a0f14;color:#e2e8f0;font-family:'Inter',sans-serif;padding:24px;}
h1{font-family:'IBM Plex Mono',monospace;color:#00d4ff;font-size:18px;margin-bottom:20px;}
.counts{display:flex;gap:16px;margin-bottom:24px;}
.count{background:#111820;border:1px solid #1e2a35;border-radius:6px;padding:12px 20px;font-family:'IBM Plex Mono',monospace;font-size:14px;}
.count.clear{color:#22c55e;}.count.partial{color:#f59e0b;}.count.blocked{color:#ef4444;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;}
.card{background:#111820;border:1px solid #1e2a35;border-radius:8px;overflow:hidden;}
.card img{width:100%;height:140px;object-fit:cover;background:#0d1a24;}
.card-footer{padding:10px;}
.lbl{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;text-transform:uppercase;margin-bottom:8px;}
.lbl.clear{color:#22c55e;}.lbl.partial{color:#f59e0b;}.lbl.blocked{color:#ef4444;}
.btns{display:flex;gap:4px;}
.btn{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:4px 8px;border-radius:4px;
  border:1px solid #1e2a35;background:#162030;color:#e2e8f0;cursor:pointer;}
.btn:hover{border-color:#00d4ff;color:#00d4ff;}
.empty{color:#4a6070;font-family:'IBM Plex Mono',monospace;font-size:12px;padding:20px 0;}
</style></head><body>
<h1>DrainWatch — Image Review</h1>
<div class="counts">
  <div class="count clear">CLEAR {{ counts.clear }}</div>
  <div class="count partial">PARTIAL {{ counts.partial }}</div>
  <div class="count blocked">BLOCKED {{ counts.blocked }}</div>
</div>
{% if recent %}
<div class="grid">
{% for r in recent %}
<div class="card" id="card-{{ r.ts }}">
  <img src="data:image/jpeg;base64,{{ r.image }}" onerror="this.style.background='#ef444420';this.alt='bad image'">
  <div class="card-footer">
    <div class="lbl {{ r.label }}">{{ r.label }}</div>
    <div class="btns">
      {% for c in ['clear','partial','blocked'] %}{% if c != r.label %}
      <button class="btn" onclick="relabel('{{ r.ts }}','{{ r.label }}','{{ c }}')">→{{ c }}</button>
      {% endif %}{% endfor %}
    </div>
  </div>
</div>{% endfor %}
</div>
{% else %}
<div class="empty">Waiting for images from ESP32-CAM...<br><br>
Make sure ESP32 is on and connected to the same Wi-Fi as this laptop.</div>
{% endif %}
<script>
function relabel(ts, old_label, new_label){
  fetch('/relabel',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ts,old_label,new_label})})
  .then(r=>r.json()).then(()=>location.reload());
}
setTimeout(()=>location.reload(), 4000);
</script>
</body></html>
"""

@app.route("/review")
def review():
    return render_template_string(REVIEW_HTML, recent=recent, counts=counts)

@app.route("/data")
def data():
    return jsonify({"counts": counts})

if __name__ == "__main__":
    print("\n  DrainWatch Image Collector (Windows)")
    print("  ─────────────────────────────────────")
    print("  Saving raw JPEG bytes directly")
    print("  Review: http://localhost:5000/review")
    print("  Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
