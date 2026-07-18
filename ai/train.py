"""
train.py — DrainWatch classifier
─────────────────────────────────
Expects:  dataset/clear/  dataset/partial/  dataset/blocked/
Outputs:  drain_model.tflite  labels.txt

python3 train.py
"""

import os, numpy as np
from pathlib import Path

print("\n  DrainWatch Model Trainer")
print("  ─────────────────────────")

CLASSES    = ["clear", "partial", "blocked"]
DATASET    = "dataset"
IMG_SIZE   = 96
BATCH_SIZE = 16
EPOCHS     = 50     # more epochs since each only takes 2 seconds

# Check counts
total = 0
for c in CLASSES:
    path  = Path(f"{DATASET}/{c}")
    count = len(list(path.glob("*.jpg"))) if path.exists() else 0
    print(f"  {c:10s} — {count} images")
    total += count
print(f"  Total: {total} images\n")

print("  Loading TensorFlow...")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.preprocessing.image import ImageDataGenerator
print(f"  TensorFlow {tf.__version__}\n")

# ── DATA — stronger augmentation for lighting robustness ──
train_gen = ImageDataGenerator(
    rescale=1./255,
    validation_split=0.2,
    rotation_range=15,
    brightness_range=[0.5, 1.5],   # wider brightness range
    horizontal_flip=True,
    vertical_flip=False,
    zoom_range=0.15,
    width_shift_range=0.1,
    height_shift_range=0.1,
    channel_shift_range=30.0,      # slight colour shift = lighting variety
)

train_ds = train_gen.flow_from_directory(
    DATASET, target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE, class_mode="categorical",
    subset="training", classes=CLASSES, shuffle=True,
)
val_ds = train_gen.flow_from_directory(
    DATASET, target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE, class_mode="categorical",
    subset="validation", classes=CLASSES, shuffle=False,
)

print(f"  Training: {train_ds.samples} samples")
print(f"  Validation: {val_ds.samples} samples\n")

# ── MODEL ─────────────────────────────────────────────────
base = MobileNetV2(
    input_shape=(IMG_SIZE, IMG_SIZE, 3),
    include_top=False,
    weights="imagenet",
)
base.trainable = False

model = models.Sequential([
    base,
    layers.GlobalAveragePooling2D(),
    layers.BatchNormalization(),
    layers.Dropout(0.4),
    layers.Dense(128, activation="relu"),
    layers.Dropout(0.3),
    layers.Dense(len(CLASSES), activation="softmax"),
])

model.compile(
    optimizer=tf.keras.optimizers.Adam(1e-3),
    loss="categorical_crossentropy",
    metrics=["accuracy"],
)

# ── PHASE 1 — train head only ─────────────────────────────
print(f"  Phase 1: training classifier head ({EPOCHS} epochs)...")
callbacks = [
    tf.keras.callbacks.EarlyStopping(patience=8, restore_best_weights=True, verbose=1),
    tf.keras.callbacks.ReduceLROnPlateau(patience=4, factor=0.5, verbose=1, min_lr=1e-6),
]

history = model.fit(
    train_ds, validation_data=val_ds,
    epochs=EPOCHS, callbacks=callbacks, verbose=1,
)

val_acc = max(history.history["val_accuracy"])
print(f"\n  Phase 1 accuracy: {val_acc*100:.1f}%")

# ── PHASE 2 — fine-tune top layers of base ────────────────
print("\n  Phase 2: fine-tuning top 30 layers of MobileNetV2...")
base.trainable = True
for layer in base.layers[:-30]:
    layer.trainable = False

model.compile(
    optimizer=tf.keras.optimizers.Adam(1e-4),   # lower LR for fine-tuning
    loss="categorical_crossentropy",
    metrics=["accuracy"],
)

history2 = model.fit(
    train_ds, validation_data=val_ds,
    epochs=30, callbacks=callbacks, verbose=1,
)

val_acc2 = max(history2.history["val_accuracy"])
best_acc = max(val_acc, val_acc2)
print(f"\n  Phase 2 accuracy: {val_acc2*100:.1f}%")
print(f"  Best overall:     {best_acc*100:.1f}%")

# ── EXPORT ────────────────────────────────────────────────
print("\n  Converting to TFLite...")
converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
tflite_model = converter.convert()

with open("drain_model.tflite", "wb") as f:
    f.write(tflite_model)
with open("labels.txt", "w") as f:
    for c in CLASSES:
        f.write(c + "\n")

print(f"  Saved drain_model.tflite  ({len(tflite_model)//1024} KB)")
print(f"  Saved labels.txt")
print(f"\n  ✓ Final accuracy: {best_acc*100:.1f}%")

if best_acc >= 0.85:
    print("  ✓ Target met — ready for deployment")
else:
    print("  ⚠  Below 85% — try collecting 20-30 more images per class")
    print("     especially partial (hardest class to distinguish)")
print()
