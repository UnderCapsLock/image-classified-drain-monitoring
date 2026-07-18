"""
classify.py
───────────
Standalone classifier module. Import this into server.py.

Usage in server.py:
    from classify import DrainClassifier
    classifier = DrainClassifier()   # loads model once on startup
    label, confidence = classifier.predict(image_bytes)
"""

import numpy as np
from pathlib import Path

class DrainClassifier:
    def __init__(self,
                 model_path="drain_model.tflite",
                 labels_path="labels.txt"):

        # Load labels
        labels_file = Path(labels_path)
        if not labels_file.exists():
            raise FileNotFoundError(f"labels.txt not found at {labels_path}")
        self.labels = [l.strip() for l in labels_file.read_text().splitlines() if l.strip()]

        # Load TFLite model
        model_file = Path(model_path)
        if not model_file.exists():
            raise FileNotFoundError(f"Model not found at {model_path}")

        import tflite_runtime.interpreter as tflite
        self.interpreter = tflite.Interpreter(model_path=str(model_file))
        self.interpreter.allocate_tensors()

        self.input_details  = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        # Expected input size from model
        shape = self.input_details[0]["shape"]
        self.img_h = shape[1]
        self.img_w = shape[2]

        print(f"  DrainClassifier loaded: {model_path}")
        print(f"  Classes: {self.labels}")
        print(f"  Input size: {self.img_w}x{self.img_h}")

    def predict(self, image_bytes):
        """
        image_bytes: raw JPEG bytes (not base64)
        Returns: (label_string, confidence_float_0_to_100)
        """
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = img.resize((self.img_w, self.img_h))
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = np.expand_dims(arr, axis=0)   # add batch dimension

        self.interpreter.set_tensor(self.input_details[0]["index"], arr)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

        idx        = int(np.argmax(output))
        label      = self.labels[idx]
        confidence = round(float(output[idx]) * 100, 1)
        return label, confidence


# ── Fallback if tflite_runtime not installed ──────────────
# Tries tensorflow.lite as backup
try:
    import tflite_runtime.interpreter
except ImportError:
    try:
        import tensorflow as tf
        # monkey-patch so DrainClassifier still works
        import types, sys
        mod = types.ModuleType("tflite_runtime.interpreter")
        mod.Interpreter = tf.lite.Interpreter
        sys.modules["tflite_runtime"] = types.ModuleType("tflite_runtime")
        sys.modules["tflite_runtime.interpreter"] = mod
    except ImportError:
        pass


if __name__ == "__main__":
    # Quick test — pass an image path as argument
    import sys, base64
    if len(sys.argv) < 2:
        print("Usage: python3 classify.py image.jpg")
        sys.exit(1)
    clf = DrainClassifier()
    with open(sys.argv[1], "rb") as f:
        label, conf = clf.predict(f.read())
    print(f"\n  Result: {label}  ({conf}% confidence)")
