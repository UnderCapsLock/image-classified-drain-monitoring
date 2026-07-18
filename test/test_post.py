"""
test_post.py — simulates ESP32 using real collected images
Cycles through your dataset images so classifications are real
"""
import requests, base64, time, random, os
from pathlib import Path

SERVER   = "http://localhost:5000/upload"
NODE     = "cameranode-1"
DATASET  = "dataset"
CLASSES  = ["clear", "partial", "blocked"]
INTERVAL = 8   # seconds between sends

# Load all images from dataset
image_pool = []
for cls in CLASSES:
    folder = Path(DATASET) / cls
    if folder.exists():
        for img_path in folder.glob("*.jpg"):
            image_pool.append((str(img_path), cls))

if not image_pool:
    print("  No images found in dataset/ folder")
    print("  Make sure dataset/clear, dataset/partial, dataset/blocked exist")
    exit(1)

print(f"\n  DrainWatch Simulator")
print(f"  Loaded {len(image_pool)} images from dataset")
print(f"  Posting to {SERVER} every {INTERVAL}s")
print(f"  Ctrl+C to stop\n")

random.shuffle(image_pool)
idx = 0

while True:
    img_path, true_label = image_pool[idx % len(image_pool)]
    idx += 1

    try:
        with open(img_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "node":  NODE,
            "image": image_b64,
        }

        r = requests.post(SERVER, json=payload, timeout=10)
        if r.ok:
            result = r.json()
            print(f"  Sent {os.path.basename(img_path)} → HTTP {r.status_code}")
        else:
            print(f"  Error: HTTP {r.status_code}")

    except Exception as e:
        print(f"  Failed: {e}")

    time.sleep(INTERVAL)
