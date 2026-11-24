#!/usr/bin/env python3
"""Record 3 seconds, transcribe with Whisper, then speak it back."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orion.audio import AudioEngine
from orion.speech import SpeechEngine

if __name__ == "__main__":
    a, s = AudioEngine(), SpeechEngine()
    print("Loading Whisper ...")
    s.warmup()
    print("Recording 3 seconds ... speak now!")
    audio = a.record(3)
    print(f"Peak level: {a.level(audio):.4f}")
    text = s.transcribe(audio)
    print(f"You said: {text!r}")
    if text:
        print("Speaking it back ...")
        s.speak(text, blocking=True)
