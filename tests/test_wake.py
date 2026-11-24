#!/usr/bin/env python3
"""
Watch wake-word scores and keyword detection for 30 seconds.
Say 'Hey Orion' and watch the acoustic score / keyword phrase.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from orion.audio import AudioEngine
from orion.speech import SpeechEngine
from orion.wake import WakeDetector

if __name__ == "__main__":
    a, s = AudioEngine(), SpeechEngine()
    w = WakeDetector(a, s)
    print("Loading models ...")
    s.warmup()
    print(f"Acoustic model available: {w.load_acoustic()}")
    print(f"Threshold: {config.WAKE['score_threshold']} | Keyword: '{config.WAKE['keyword']}'")
    print("Listening 30 seconds — say 'Hey Orion' ...\n")

    result = w.wait(timeout=30, mode="auto")
    if result.triggered:
        print(f"\nACTIVATED via {result.method} — '{result.text}' score={result.score:.3f}")
    else:
        print("\nNo activation detected in 30 s. Check mic level with tests/test_mic.py")
