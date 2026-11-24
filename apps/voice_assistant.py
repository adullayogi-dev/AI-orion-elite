#!/usr/bin/env python3
"""
ORION ELITE — principal voice assistant (Episodes 4, 5, 7 & 8 combined).

Usage
-----
    python apps/voice_assistant.py                  # auto activation
    python apps/voice_assistant.py --mode keyword   # "Hey Orion" via Whisper
    python apps/voice_assistant.py --mode acoustic  # wake scores (ONNX model)
    python apps/voice_assistant.py --mode keyboard  # tap SPACE to speak
    python apps/voice_assistant.py --model qwen3:4b
    python apps/voice_assistant.py --selftest
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

# Allow running as `python apps/voice_assistant.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from orion.audio import AudioEngine
from orion.brain import OrionBrain
from orion.i18n import detect_language, localize_reply
from orion.logger import log
from orion.speech import SpeechEngine
from orion.wake import WakeDetector


BANNER = r"""
  ____   ___ -_____   _____   _   .
 |    | |   \   |    |     | | \  |
 |    | |___/   |    |     | |  \ |  ELITE
 |____| | \   __|__  |_____| |   \|
"""


# Set while a background reminder is being spoken. Command mode must not
# transcribe Orion's own voice as a new command.
_REMINDER_PLAYING = threading.Event()


def selftest(audio: AudioEngine, speech: SpeechEngine, brain: OrionBrain) -> None:
    print("\n--- ORION SELFTEST ---")
    try:
        devices = audio.input_devices()
        print(f"[{'OK' if devices else 'WARN'}] Input devices: {len(devices)}")
        for d in devices[:5]:
            print(f"       [{d['index']}] {d['name']}")
    except Exception as exc:
        print(f"[WARN] Device query: {exc}")

    print("[..] Loading Whisper ...")
    speech.warmup()
    print("[OK] Whisper loaded")

    print("[..] Checking Ollama ...")
    print(f"[{'OK' if brain.status()['ollama_online'] else 'WARN'}] "
          f"Ollama online: {brain.status()['ollama_online']}")
    print(f"[i ] Brain model: {brain.status()['model']}")
    print("--- SELFTEST COMPLETE ---\n")


def process_command(audio: AudioEngine, speech: SpeechEngine, brain: OrionBrain,
                    args) -> bool:
    """Record and execute one command. Returns False when user says 'go to sleep'."""
    if _REMINDER_PLAYING.is_set():
        return True  # never listen while Orion itself is talking
    audio_input = audio.record() if args.fixed else audio.record_until_silence()
    if _REMINDER_PLAYING.is_set():
        return True  # a reminder interrupted this recording — discard it
    if len(audio_input) == 0:
        return True  # just silence — stay in command mode, no nagging

    level = audio.level(audio_input)
    if level < config.AUDIO["wake_threshold"]:
        return True

    print("Transcribing ...")
    text = speech.transcribe(audio_input)
    if not text:
        return True
    print(f"You   : {text}")

    low = text.lower().strip().strip(" .?!")
    if any(p in low for p in config.BRAIN["sleep_phrases"]):
        reply = localize_reply(
            "Orion standing by, sir. Press SPACE or say Hey Orion when you need me.",
            detect_language(text),
        )
        print(f"Orion : {reply}")
        if not args.no_tts:
            speech.speak(reply, blocking=True)
        return False

    reply = brain.chat(text)
    print(f"Orion : {reply}")
    # Blocking TTS keeps Orion from transcribing its own answer as a new command.
    if not args.no_tts:
        speech.speak(reply, blocking=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="ORION ELITE voice assistant")
    parser.add_argument("--mode", default="auto",
                        choices=["auto", "keyword", "acoustic", "keyboard"],
                        help="activation method (default: auto)")
    parser.add_argument("--model", default=None, help="override Ollama model name")
    parser.add_argument("--fixed", action="store_true",
                        help="use a fixed 5s record window instead of silence detection")
    parser.add_argument("--no-tts", action="store_true", help="mute speech output")
    parser.add_argument("--timeout", type=float, default=None,
                        help="stop waiting for activation after N seconds")
    parser.add_argument("--selftest", action="store_true", help="verify hardware/models and exit")
    parser.add_argument("--device", type=int, default=None,
                        help="microphone device index (use --list-devices to find it)")
    parser.add_argument("--list-devices", action="store_true",
                        help="print input devices and exit")
    args = parser.parse_args()

    audio_probe = AudioEngine()
    if args.list_devices:
        for d in audio_probe.input_devices():
            print(f"[{d['index']}] {d['name']}")
        return 0

    if args.device is not None:
        valid = {d["index"] for d in audio_probe.input_devices()}
        if args.device not in valid:
            print(f"\n[ERROR] Microphone device {args.device} is not available.\n")
            print("Available input devices:")
            for d in audio_probe.input_devices():
                print(f"  [{d['index']}] {d['name']}")
            print("\nRe-run with a valid index, e.g. .\\run_voice.ps1 --device 1\n")
            return 2
        config.AUDIO["device"] = args.device
        print(f"Microphone: [{args.device}] selected")

    print(BANNER)
    log.info("Starting Orion Elite v%s", config.APP_VERSION)

    audio = AudioEngine()
    speech = SpeechEngine()
    brain = OrionBrain()
    # Reminders fire on a background thread — announce them through the same
    # male voice, and pause command listening until the room is quiet again.
    def announce_reminder(text: str) -> None:
        _REMINDER_PLAYING.set()
        try:
            speech.speak(text, blocking=True)
            time.sleep(0.3)  # let the echo die down before listening again
        finally:
            _REMINDER_PLAYING.clear()

    brain.tools.set_notifier(announce_reminder)
    wake = WakeDetector(audio, speech)

    if args.model:
        brain.set_model(args.model)

    if args.selftest:
        selftest(audio, speech, brain)
        return 0

    try:
        speech.warmup()
    except Exception as exc:
        log.error("Speech warmup failed: %s", exc)
        return 1

    print(f"Activation : {args.mode.upper()}")
    print(f"Brain      : {brain.status()['model']}")
    print("Controls   : SPACE to activate | CTRL+C to exit")
    print("=" * 52)

    try:
        while True:
            activation = wake.wait(timeout=args.timeout, mode=args.mode)
            if not activation.triggered:
                log.debug("No activation (timeout)")
                time.sleep(0.5)  # avoid a tight loop if the mic stream failed
                continue

            how = activation.method
            detail = f" ('{activation.text}')" if activation.text and how == "keyword" else ""
            if how == "acoustic":
                detail = f" [score {activation.score:.2f}]"
            print(f"\n>>> ACTIVATED via {how.upper()}{detail}")
            print("Command mode active — speak normally. Say 'go to sleep' to stop.")
            print("=" * 52)

            if config.BRAIN["continuous_after_wake"]:
                # Stay in command mode: open -> close -> more commands, with
                # no SPACE / wake word between them.
                while process_command(audio, speech, brain, args):
                    pass
            else:
                process_command(audio, speech, brain, args)
            print("-" * 52)

    except KeyboardInterrupt:
        print("\nOrion standing down. Goodbye, sir.")
    finally:
        brain.tools.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
