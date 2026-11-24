# ORION ELITE v1.0

A local-first, offline-capable AI voice assistant built from the **J.A.R.V.I.S. reference series (Episodes 2–10)** and the **Orion architecture diagrams**, rebranded, modularised and hardened.

> No API keys. No cloud brain. Everything runs on your PC with Ollama + Whisper + pyttsx3.

---

## 1. Architecture (from your diagrams)

| Diagram | What it described | Where it lives here |
|---|---|---|
| **Image 1** — *orion AI-Assistant* | mic always listening → 80 ms chunks → OpenWakeWord score 0–1 → `if score > 0.5 → Activate` → record command → next stage | `orion/audio.py`, `orion/wake.py` |
| **Image 2** — *Orion-Brain.py* | memory / chat-history, installed tools (DuckDuckGo, Wikipedia), analyse command, take over browser (Selenium, keyboard) | `orion/memory.py`, `orion/tools.py`, `orion/brain.py` |
| **Image 3** — *body of orion / neon lights* | Streamlit + psutil HUD, Flask + pyngrok mobile control, `orion-Mobile → templates → index.html` | `apps/hud.py`, `apps/mobile_server.py`, `templates/index.html` |
| **Image 4** — *ngrok method* | ngrok account → authtoken → run app → copy public link → open on phone | `config.MOBILE`, `README §6` |

Episode mapping: **Ep2** brain setup → **Ep3** ears/voice → **Ep4** wake word → **Ep5** conversation loop → **Ep6** memory → **Ep7** agent tools → **Ep8** browser + spacebar → **Ep9** HUD → **Ep10** mobile control.

---

## 2. Folder structure

```
AI orion-elite/
├─ .venv/                    isolated Python environment (do not edit)
├─ apps/
│  ├─ voice_assistant.py     main voice core (wake → STT → brain → TTS)
│  ├─ hud.py                 Iron-Man style Streamlit dashboard
│  └─ mobile_server.py       Flask + ngrok phone controller
├─ orion/
│  ├─ audio.py               mic, fixed/dynamic recording, level metering
│  ├─ speech.py              Whisper STT + pyttsx3 TTS (lazy loaded)
│  ├─ wake.py                acoustic / keyword / keyboard activation
│  ├─ memory.py              persistent chat history + facts
│  ├─ tools.py               Wikipedia, web search, browser, PC control
│  ├─ brain.py               Ollama reasoning + tool routing
│  ├─ system.py              helpers
│  └─ logger.py              console + rotating file logs
├─ templates/index.html      neon mobile UI
├─ tests/                    mic / STT / wake diagnostics
├─ data/                     memory JSON + optional custom wake model
├─ logs/                     rotating logs
├─ config.py                 ALL settings live here
├─ requirements.txt
├─ setup.ps1                 one-time / repeatable setup
├─ run_voice.ps1  run_hud.ps1  run_mobile.ps1
└─ README.md
```

---

## 3. Quick start

```powershell
cd "C:\Users\adull\OneDrive\Documents\Default Project\AI orion-elite"

# one-time (safe to re-run)
.\setup.ps1

# verify hardware + models
.\run_voice.ps1 --selftest

# start talking
.\run_voice.ps1
```

Then say **“Hey Orion”** (keyword mode) or tap **SPACE** in the console.

---

## 4. Modes & useful commands

```powershell
.\run_voice.ps1 --mode auto        # acoustic + "Hey Orion" + spacebar (default)
.\run_voice.ps1 --mode keyword     # Whisper verifies "Orion" in short audio windows
.\run_voice.ps1 --mode acoustic    # raw OpenWakeWord scores (diagram behaviour)
.\run_voice.ps1 --mode keyboard    # spacebar only — quiet rooms / testing
.\run_voice.ps1 --model qwen3:4b   # switch brain model
.\run_voice.ps1 --fixed            # fixed 5-second command window
.\run_voice.ps1 --no-tts           # text-only output
```

Say things like:
`open youtube` · `search for latest AI news` · `what is quantum computing` · `system status` · `remember that my code is Orion-7` · `open notepad`

---

## 5. HUD (Episode 9)

```powershell
.\run_hud.ps1
```
Open **http://localhost:8501**. Cyan/amber Orion theme, live CPU/RAM/disk/battery, voice button, typed commands, mission log, memory reset.

---

## 6. Mobile control (Episode 10)

```powershell
.\run_mobile.ps1
```

**LAN method** — phone and PC on the same Wi-Fi:
1. `ipconfig` → note your PC's IPv4 (e.g. `192.168.1.34`)
2. Phone browser → `http://192.168.1.34:5000`
3. If blocked: Windows Firewall → allow **Python** on Private networks.

**ngrok method (anywhere)**:
1. Sign up at `ngrok.com`, copy your authtoken from the dashboard.
2. Set it in `config.py` → `MOBILE["ngrok_token"]` (or environment variable `NGROK_AUTHTOKEN`).
3. Set `MOBILE["ngrok_enabled"] = True` and run `.\run_mobile.ps1`.
4. Open the printed `https://....ngrok.app` link on your phone.

Port conflict? Change `MOBILE["port"]` to `5001`.

---

## 7. Wake word — important note

OpenWakeWord ships `hey_jarvis_v0.1` and `alexa_v0.1`, **but no `hey_orion` model**. So Orion Elite uses three triggers at once in `auto` mode:

1. **Keyword (primary for “Hey Orion”)** — a short Whisper transcription checks for the callsign. This works out of the box.
2. **Acoustic** — the ONNX wake model emits scores exactly like your diagram. It currently uses `hey_jarvis_v0.1` as the trained acoustic front-end. To go fully custom, train a `hey_orion_v0.1.onnx` model and drop it into `data/models/`; `config.py` picks it up automatically.
3. **Keyboard** — SPACE in the console, no admin rights required.

Tune thresholds in `config.py` → `WAKE`:
- false triggers? raise `score_threshold` to `0.6`
- not triggering? lower it to `0.35`, or use `--mode keyword`

---

## 8. Configuration highlights (`config.py`)

| Key | Default | Meaning |
|---|---|---|
| `BRAIN["ollama_model"]` | `qwen3:4b-instruct` | local brain (already installed) |
| `SPEECH["whisper_model"]` | `tiny` | `base` = more accurate, slower |
| `SPEECH["beam_size"]` | `5` | Episode 7 accuracy fix |
| `AUDIO["silence_timeout"]` | `1.5` | auto-stop recording after quiet |
| `WAKE["score_threshold"]` | `0.5` | diagram’s activation threshold |
| `TOOLS["allow_pc_control"]` | `True` | set `False` to disable app launching |

Environment overrides: `OLLAMA_HOST`, `NGROK_AUTHTOKEN`.

---

## 9. Troubleshooting (from the reference error guides)

| Symptom | Fix |
|---|---|
| `Tried to import tflite runtime` | Already solved — code forces `inference_framework="onnx"`; rerun `.\setup.ps1` |
| `faster_whisper / ctranslate2` import error on Python 3.14 | This build is tested on **Python 3.14** with `ctranslate2 4.9` — use the provided `.venv` |
| `PortAudioError` / level `0.0000` | Windows Settings → Privacy → Microphone → ON; `mmsys.cpl` → set default device; run `python tests/test_mic.py` |
| `No speech detected` | Move 10–15 cm from the mic, speak clearly; lower `AUDIO["silence_threshold"]` |
| Ollama refused | Keep Ollama running; `ollama list` / `ollama pull qwen3:4b-instruct` |
| `streamlit` not recognised | Always use `.\run_hud.ps1` (it runs `python -m streamlit`) |
| Selenium/Chrome fails | Falls back to the default browser automatically; run Windows Update for Chrome |

Diagnostics:
```powershell
& .\.venv\Scripts\python.exe tests\test_mic.py
& .\.venv\Scripts\python.exe tests\test_stt.py
& .\.venv\Scripts\python.exe tests\test_wake.py
```

---

## 10. Status

Verified on this machine: 14 input devices detected, Whisper `tiny` loaded, Ollama `qwen3:4b-instruct` online, wake model loaded, tool routes (system status / Wikipedia / DuckDuckGo) working, HUD HTTP 200, mobile HTTP 200 with working command endpoints.

*Built as a clean-room reimplementation of the provided JARVIS reference material for the Orion Elite project. Existing Orion/JARVIS folders were left untouched.*
