#!/usr/bin/env python3
"""
ORION ELITE — mobile command server (Episode 10, rebuilt).
Run:  python apps/mobile_server.py
Then open http://<PC-IP>:5000 on your phone (same Wi-Fi).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, render_template, request

import config
from orion.brain import OrionBrain
from orion.logger import log
from orion.speech import SpeechEngine

app = Flask(__name__, template_folder=str(config.TEMPLATES_DIR))
speech = SpeechEngine()
brain = OrionBrain()


def _say(text: str) -> None:
    threading.Thread(target=speech.speak, args=(text, True), daemon=True).start()


def _respond(text: str, action: str = "") -> tuple:
    reply = brain.chat(text)
    log.info("mobile action=%s text=%r -> %r", action, text, reply[:120])
    _say(reply)
    return jsonify({"status": "success", "action": action, "reply": reply})


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/command/<action>")
def command(action: str):
    """Quick action buttons from the neon mobile UI."""
    actions = {
        "youtube": "open youtube",
        "google": "open google",
        "calculator": "open calculator",
        "notepad": "open notepad",
        "morning": "good morning sir, give me a system status report",
        "status": "system status",
    }
    text = actions.get(action.lower(), action.replace("-", " "))
    return _respond(text, action)


@app.route("/api/command", methods=["POST"])
def api_command():
    """Free-form text command from the phone."""
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({"status": "error", "reply": "Empty command, sir."}), 400
    return _respond(text, "text")


@app.route("/api/status")
def api_status():
    return jsonify({"status": "online", **brain.status()})


def main() -> None:
    print("\n\U0001F680 ORION ELITE — MOBILE COMMAND SERVER")
    print("=" * 52)
    tunnel = None
    if config.MOBILE["ngrok_enabled"]:
        try:
            from pyngrok import ngrok

            token = config.MOBILE["ngrok_token"]
            if token:
                ngrok.set_auth_token(token)
            tunnel = ngrok.connect(config.MOBILE["port"])
            print(f"\U0001F310 PUBLIC URL : {tunnel.public_url}")
        except Exception as exc:
            log.error("ngrok failed: %s", exc)
            print("ngrok unavailable — LAN mode still works.")

    print(f"\U0001F4F1 Local URL   : http://<PC-IP>:{config.MOBILE['port']}")
    print("Same Wi-Fi required for LAN mode. CTRL+C to stop.")
    print("=" * 52)
    try:
        app.run(
            host=config.MOBILE["host"],
            port=config.MOBILE["port"],
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    finally:
        brain.tools.close()


if __name__ == "__main__":
    main()
