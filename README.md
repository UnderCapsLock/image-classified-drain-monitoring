# image-classified-drain-monitoring
Simple image classification of images of drains into three categories of severity.

![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Overview

Image classification system with dashboard and database using ESP32-CAM and ESP32-S3-CAM. Used for mock drains and categorising said mock drains into three categories, which are:
- **clear** — drain is unobstructed
- **partial** — drain is partially blocked
- **blocked** — drain is fully blocked
  
## Architecture
Simply put...
ESP32-CAM/ESP32-S3-CAM → WiFi → Flask Server → AI Classifier (TFLite) → SQLite → Dashboard

**How it works:**
1. an ESP32-CAM or ESP32-S3-CAM captures a JPEG image every few seconds
2. image is base64-encoded and sent via HTTP POST to the Flask server
3. server decodes the image and feeds it to a TFLite classifier
4. classification result + confidence is saved to SQLite
5. dashboard polls the server every second and updates live — no page reloads

Two systems:
- **Live system** — with real node, live classification shown in dashboard with sound alerts
- **Mock system** — deprecated, non-functional. for reference only, see `mock_server_deprecated.py`

## Tech Stack

- **Hardware:** ESP32-CAM / ESP32-S3-CAM
- **Backend:** Python, Flask, SQLite
- **AI:** TensorFlow, TFLite, MobileNetV2
- **Frontend:** JS, HTML/CSS

## Features

- real-time AI image classification of mock drains
- live dashboard with sound alerts on blockage detection
- full training pipeline, DIY friendly; just collect images, retrain model

## Setup

### what requirements
```bash
pip install flask requests tensorflow Pillow numpy
```

### how to run
```bash
python server.py
```
live system, port 5000 on `http://localhost:5000`.

> `mock_server.py` is deprecated and non-functional — see Roadmap section.
> Renamed to `mock_server_deprecated.py`, kept for reference only.

### collecting your own training images

```bash
python collect_images.py
```
runs a Flask server that receives images from an ESP32 and saves them 
into `dataset/clear/`, `dataset/partial/`, `dataset/blocked/` based on a 
label you provide. Unrecognized or missing labels are saved to 
`dataset/unsorted/` instead of being silently mislabeled — sort these 
manually before training.

### how to train your own model

```bash
python train.py
```
trains a MobileNetV2-based classifier on whatever is inside `dataset/`. 
output is two files:
- `drain_model.tflite` — model
- `labels.txt` — class names
copy both into the same folder and restart server as `server.py` to use the new model. 

### flashing the ESP32

see `/firmware` for both board variants:
- `drainwatch_esp32.ino` — for ESP32-CAM
- `drainwatch_esp32s3.ino` — for ESP32-S3-CAM

before flashing, edit these lines at the top of the file:
```cpp
const char* WIFI_SSID     = "yourNetworkName";
const char* WIFI_PASSWORD = "yourPassword";
const char* SERVER_IP     = "yourLaptopIP";   // run ipconfig (IPv4 address)
```

## Project Structure

```
├── ai/
│   ├── collect_images.py    # collects labelled images from ESP32
│   ├── train.py             # trains the classifier from dataset/
│   ├── classify.py          # wrapper for TFlite model, used by server.py
│   └── model/
│       ├── drain_model.tflite
│       └── labels.txt
│
├── server/
│   ├── server.py            # live dashboard + AI classification server
│   ├── mock_server_deprecated.py  # non-functional, kept for reference only
│   ├── launcher.html        # simple homepage linking both dashboards
│   ├── requirements.txt
│   └── start.sh
│
├── dataset/
│   └── dataset.zip          # training images (clear / partial / blocked) with around 400 each category
│
├── test/
│   └── test_post.py         # simulates ESP32 sending images (for testing)
│
└── firmware/
    ├── drainwatch_esp32.ino     # ESP32-CAM
    └── drainwatch_esp32s3.ino   # ESP32-S3-CAM
```
## Future Developments

not in any order
- [ ] Migrate from HTTP POST to MQTT for stability
- [ ] Browser push notifications
- [ ] Telegram bot integration
- [ ] Simple dashboard website
- [ ] Docker containerization
- [ ] Config file instead of hardcoded WiFi credentials
- [ ] Editable node names via UI
- [ ] Add/remove nodes dynamically without code changes
- [ ] Visual "system healthy" indicator beyond raw uptime
- [ ] Readding mock server for preliminary use
- [ ] Adding more images to README.md
- [ ] Document evidence tiers for DrainWatch subsystems
- [ ] Add a documented failure log

## Results

- Final model accuracy: ~97%
- Placed Top 5 at YIC State Round 2026 (Malaysia)

## License

MIT license.

## Extra Notes

to whomever finds this, free to copy verbatim and edit if you like

vibecoded using claude sonnet 5 and chatgpt gpt-5
