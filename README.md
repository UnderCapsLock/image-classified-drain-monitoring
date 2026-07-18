# image-classified-drain-monitoring
Simple image classification of images of drains into three categories of severity.

## Overview

Image classification system with dashboard and database using ESP32-CAM and ESP32-S3-CAM. Used for mock drains and categorising said mock drains into three categories, which are clear, blocked and partial. 

## Architecture
Simply put...
ESP32-CAM/ESP32-S3-CAM → WiFi → Flask Server → AI Classifier (TFLite) → SQLite → Dashboard


Two systems:
- **Live system** — real camera node (singular), live classification, live dashboard with sound alerts
- **Mock system** — non-functional, would avoid use, its here

## Tech Stack

- **Hardware:** ESP32-CAM / ESP32-S3-CAM
- **Backend:** Python, Flask, SQLite
- **AI:** TensorFlow, TFLite, MobileNetV2
- **Frontend:** JS, HTML/CSS

## Features

- Real-time AI image classification of mock drains
- Live dashboard with sound alerts on blockage detection
- SQLite persistence — survives restarts (yay or nay)


## Setup

### what requirements
pip install flask requests tensorflow Pillow numpy


### how to run
python server.py       # live system, port 5000
python mock_server.py  # mock system, port 5001 (dont do this)


### how to train your own model
python train.py

See `/firmware` for ESP32 Arduino sketches (edit WiFi credentials before flashing).

## Future Developments

- nothing planned, will stay dormant

## Results

- Final model accuracy: ~97%
- Placed Top 5 at YIC State Round 2026

## License

MIT — free to use, modify, and distribute.

## Extra Notes

to whomever finds this, free to copy verbatim and edit if you like
