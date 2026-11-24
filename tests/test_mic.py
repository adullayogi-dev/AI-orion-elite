#!/usr/bin/env python3
"""Mic level + device test. Speak and watch the level climb above 0.30."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import sounddevice as sd

from orion.audio import AudioEngine

if __name__ == "__main__":
    a = AudioEngine()
    print(a.describe_devices())
    print("\nSpeaking? Watch the level (target > 0.30). CTRL+C to stop.\n")
    try:
        with sd.InputStream(samplerate=a.samplerate, channels=1,
                            dtype="float32", device=a.device) as stream:
            while True:
                data, _ = stream.read(a.samplerate // 10)
                level = float(np.max(np.abs(data)))
                bar = "#" * min(60, int(level * 100))
                print(f"level {level:.4f} |{bar}", end="\r", flush=True)
                time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nMic test complete.")
