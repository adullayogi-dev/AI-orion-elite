#!/usr/bin/env python3
"""Find which microphone actually hears your voice.

Run from the project folder:
    .\\.venv\\Scripts\\python.exe tests\\find_mic.py

Speak continuously while the test runs. The device with the HIGHEST peak
is the one Orion should use with --device <index>.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from orion.audio import AudioEngine

CANDIDATES = [0, 1, 4, 5, 9, 15, 21, 24, 26, 27, 29]


def main() -> None:
    probe = AudioEngine()
    available = [d["index"] for d in probe.input_devices()]
    print("\n=== MIC FINDER ===")
    print("SPEAK CONTINUOUSLY for the next ~20 seconds.\n")
    results: list[tuple[float, int, str]] = []

    for index in CANDIDATES:
        if index not in available:
            continue
        config.AUDIO["device"] = index
        audio = AudioEngine()
        name = ""
        try:
            import sounddevice as sd
            name = str(sd.query_devices(index)["name"])[:44]
            level = audio.level(audio.record(1.5))
        except Exception as exc:
            print(f"[{index:>2}] ERROR  {str(exc)[:50]}")
            continue
        print(f"[{index:>2}] peak {level:.4f}  {name}")
        results.append((level, index, name))

    print("\n=== BEST MICROPHONE ===")
    if results:
        level, index, name = max(results)
        print(f"[{index}] {name}  (peak {level:.4f})")
        print(f"\nUse it with:  .\\run_voice.ps1 --device {index}")
    else:
        print("No working microphone found. Check Windows microphone privacy settings.")


if __name__ == "__main__":
    main()
