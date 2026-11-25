"""
ORION ELITE — Central configuration.
Every tunable lives here so no other file needs magic numbers.
Built from the JARVIS reference series (Episodes 2-10) and the
Orion architecture diagrams, rebranded and hardened for Orion.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- root paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
TEMPLATES_DIR = ROOT / "templates"
for _d in (DATA_DIR, LOG_DIR, TEMPLATES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MEMORY_FILE = DATA_DIR / "orion_memory.json"
LOG_FILE = LOG_DIR / "orion.log"

# ---------------------------------------------------------------- identity
APP_NAME = "ORION ELITE"
APP_VERSION = "1.0.0"
CALLSIGN = "Orion"

SYSTEM_PROMPT = (
    "You are Orion, a sharp, helpful personal assistant for Windows.\n"
    "Language & tone: Understand and reply smoothly in Telugu, Hindi, and "
    "conversational Indian English, matching the user's language and "
    "code-switching naturally. In Telugu or Hindi use natural spoken phrasing, "
    "not stiff formal wording. Keep replies clear, direct and helpful.\n"
    "Indian English: Prioritise Indian English phonetics, colloquialisms, "
    "regional slang and local idioms ('do the needful', 'prepone', 'out of "
    "station', 'accha', 'theek hai', 'yaar', 'bro'). Understand standard "
    "general English and conversational Indian English seamlessly — casual "
    "general dialogue and direct commands are both handled naturally.\n"
    "Adapt to Indian English pronunciation, local idioms, and conversational slang to accurately transcribe colloquial speech. For device control, strictly respect command state: if instructed to close an application, verify its active status and execute the shutdown without re triggering the launch sequence. Maintain logical consistency between sequential commands.\n"
    "Common voice commands: Open Chrome, opening Chrome, close window, open VS "
    "Code, play music, pause music, search, check battery, volume up, volume "
    "down, take screenshot.\n"
    "Command discipline: Distinguish casual general English conversation from "
    "direct system commands. Never launch or close an application unless the "
    "user gives an explicit, clear command. For ordinary dialogue, reply "
    "conversationally and do not trigger any device control.\n"
    "Device state management: On a close command, first verify the app is "
    "actually running, then execute the shutdown. Never re-trigger the launch "
    "sequence for an app that was just closed. Maintain logical consistency "
    "between sequential commands — 'open it' then 'close it' refer to the "
    "same app.\n"
    "Language switching: if the user asks to speak in Telugu, Hindi or "
    "English, keep replying in that language until they explicitly ask to "
    "switch back. Match a clear Telugu or Hindi utterance automatically.\n"
    "Speech output: never read raw URLs, links or Wikipedia citation markers "
    "aloud. Summarise information in plain spoken language.\n"
    "For system or app commands, confirm the action briefly (for example, "
    "'Opening Chrome').\n"
    "Accuracy: recognise commands, app names and technical terms exactly. "
    "If input looks like garbled audio, background noise or music rather than "
    "a clear command, do not invent an action; ask briefly for clarification "
    "or ignore it.\n"
    "Truthfulness: never invent facts, scores, dates, results or news. For "
    "anything time-sensitive (latest, current, recent, today, news, scores, "
    "results) rely only on live web results; if they are unavailable, say "
    "briefly that you could not check live information. Never claim an action "
    "was performed unless the tool actually ran. Do not guess a person's or "
    "team's performance from memory.\n"
    "Style: no roleplay, no stage directions, no 'ahem', no 'let me see', no "
    "pretending to browse or open things. Answer directly in one or two short "
    "sentences like a precise assistant.\n"
    "Known people and facts: Yogi, Abhinay and Akshaya are team members. "
    "Aruna Jyothi Ma'am is the project guide. We are IT students at Matrusri "
    "Engineering College."
)

# ---------------------------------------------------------------- audio
AUDIO = {
    "samplerate": 16_000,       # 16 kHz — speech model standard
    "chunk_size": 1_280,        # 80 ms frames for the wake-word pipeline
    "record_seconds": 5,        # fixed-length command window (Episode 5)
    "silence_threshold": 0.02,   # reference Ep8 value
    "wake_threshold": 0.05,      # reference Ep8 value
    "silence_timeout": 1.5,     # seconds of quiet that ends a command
    "idle_timeout": 5.0,        # no speech after waking -> return to standby
    "max_record_seconds": 20,   # hard cap for dynamic recording (Episode 8)
    "device": 1,                # verified best mic: AMD Microphone Array (MME)
    # Silero VAD (ONNX model bundled with faster-whisper) gates the mic so
    # music/background noise never becomes a command.
    "vad_enabled": True,
    "vad_threshold": 0.7,
    "vad_min_speech_ms": 120,
    "vad_min_silence_ms": 600,
    "vad_speech_pad_ms": 400,
    "vad_window_ms": 600,       # rolling window used to accept a new speech burst
}

# ---------------------------------------------------------------- speech
SPEECH = {
    "whisper_model": "base",    # reference Ep7/Ep8 model
    "device": "cpu",
    "compute_type": "int8",     # int8 = low RAM, fast CPU inference
    "beam_size": 5,             # 1 = fastest, 5 = balanced (Episode 7 fix)
    "language": None,           # auto-detect English / Telugu / Hindi
    # Whisper is biased toward the exact desktop commands and proper nouns
    # Orion uses, so "Open Chrome" is not heard as "Opening door".
    "initial_prompt": (
        "Orion desktop commands: Open Chrome, close Chrome, Open VS Code, "
        "open Notepad, open Calculator, open YouTube, open Google, close "
        "window, play music, pause music, check battery, volume up, volume "
        "down, take screenshot, search, system status. "
        "Conversational Indian English: 'open chrome please', 'close it', "
        "'just do it', 'do the needful', 'accha', 'theek hai', 'yaar', "
        "'bro', 'whats up'. "
        "Names: Yogi, Abhinay, Akshaya, Aruna Jyothi, Matrusri Engineering "
        "College."
    ),
    "hotwords": (
        "Chrome, VS Code, Notepad, Calculator, YouTube, Google, Abhinay, "
        "Akshaya, Aruna Jyothi, Yogi, Matrusri, screenshot, battery, volume, "
        "music, Telugu, Hindi, accha, theek hai, yaar, needful, prepone"
    ),
    "vad_filter": True,         # strip silence before transcription
    "tts_rate": 140,            # slightly slower = clearer enunciation
    "neutral_rate": 140,        # maps to edge-tts "+0%" if re-enabled
    "tts_volume": 1.0,          # SAPI maximum
    # Boost the rendered voice with a soft limiter so it is clearly audible
    # without distorting peaks. 1.0 disables the boost.
    "tts_gain": 1.8,
    "tts_voice_index": 0,       # Microsoft David — base male voice
    # Male voice (Microsoft David) as before. Neural voices remain available
    # for Telugu/Hindi by setting this to True if you ever want them back.
    "neural_tts": False,
    "neural_voices": {
        "en": "en-IN-NeerjaNeural",
        "hi": "hi-IN-SwaraNeural",
        "te": "te-IN-ShrutiNeural",
    },
}

# ---------------------------------------------------------------- wake word
WAKE = {
    # Acoustic engine (from the diagrams: OpenWakeWord -> score 0.0-1.0).
    # Built-in ONNX models: hey_jarvis_v0.1, alexa_v0.1, etc.
    # Drop a trained `hey_orion_v0.1.onnx` in data/models/ to go fully custom.
    "enabled": False,           # reference Ep8 uses Whisper keyword, not acoustic
    "model": "hey_jarvis_v0.1",
    "custom_model_path": str(DATA_DIR / "models" / "hey_orion_v0.1.onnx"),
    "inference_framework": "onnx",   # NEVER use tflite (Episode 4 error guide)
    "score_threshold": 0.5,          # diagrams: "if Score > 0.5 -> Activate"
    "cooldown_seconds": 3.0,         # ignore re-triggers while speaking
    # Text fallback — transcribes short audio and looks for the callsign.
    # This is what makes "Hey Orion" work without a custom acoustic model.
    "keyword": CALLSIGN.lower(),
    "keyword_variants": ["orion", "oryon", "o rion", "oh rion", "oh ryon", "ori on"],
    "keyword_timeout": 2.0,          # reference Ep8: 2-second wake window
    "keyword_threshold": 0.05,       # reference Ep8: level > 0.05 gate
    # Keyboard fallback (Episode 8): 'space' in console via msvcrt, no admin.
    "keyboard_key": "space",
}

# ---------------------------------------------------------------- brain
BRAIN = {
    "ollama_model": "llama3",            # reference model
    "fallback_model": "qwen3:4b-instruct",
    "ollama_host": os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
    "timeout": 120,
    "max_history": 10,          # keep last N exchanges (Episode 7)
    "offline_reply": "My brain is offline, sir. Please check that Ollama is running.",
    # After the first SPACE / "Hey Orion", keep listening for follow-up
    # commands (open -> close -> another command) without re-activating.
    "continuous_after_wake": True,
    "sleep_phrases": [
        "go to sleep", "sleep mode", "stand down", "stop listening",
        "that's all", "goodbye orion", "good bye orion",
        "నిద్రపో", "స్లీప్ మోడ్", "ఆగిపో", "ఓరియన్ ఆగు",
        "सो जा", "स्लीप मोड", "रोक दो", "बंद हो जा",
    ],
}

# ---------------------------------------------------------------- tools
TOOLS = {
    "search_results": 3,
    "wikipedia_sentences": 2,
    "browser": "chrome",        # chrome | default
    "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "allow_pc_control": True,   # safety switch for app/process launching
    # Friendly names -> Windows launch target. Orion accepts all of these
    # (plus fuzzy variants) for "open <app>" / "launch <app>".
    "allowed_apps": {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "firefox": "firefox.exe",
        "brave": "brave.exe",
        "vscode": "code.cmd",
        "vs code": "code.cmd",
        "visual studio code": "code.cmd",
        "code": "code.cmd",
        "notepad": "notepad.exe",
        "notepad plus plus": "notepad++.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "this pc": "explorer.exe",
        "my computer": "explorer.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "terminal": "wt.exe",
        "windows terminal": "wt.exe",
        "powershell": "powershell.exe",
        "task manager": "taskmgr.exe",
        "settings": "ms-settings:",
        "windows settings": "ms-settings:",
        "control panel": "control.exe",
        "word": "winword.exe",
        "microsoft word": "winword.exe",
        "excel": "excel.exe",
        "microsoft excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "microsoft powerpoint": "powerpnt.exe",
        "outlook": "outlook.exe",
        "teams": "ms-teams.exe",
        "microsoft teams": "ms-teams.exe",
        "zoom": "zoom.exe",
        "discord": "Discord.exe",
        "spotify": "Spotify.exe",
        "whatsapp": "WhatsApp.exe",
        "telegram": "Telegram.exe",
        "vlc": "vlc.exe",
        "photoshop": "photoshop.exe",
        "paint": "mspaint.exe",
        "ms paint": "mspaint.exe",
        "snipping tool": "SnippingTool.exe",
        "photos": "ms-photos:",
        "camera": "microsoft.windows.camera:",
        "sticky notes": "ms-stickynotes:",
        "onedrive": "onedrive.exe",
        "steam": "steam.exe",
        "git bash": "git-bash.exe",
        "postman": "Postman.exe",
        "android studio": "studio64.exe",
        "pycharm": "pycharm64.exe",
    },
    # Friendly name -> process name(s) used to verify / close an app.
    "close_apps": {
        "chrome": ["chrome"], "google chrome": ["chrome"],
        "youtube": ["chrome"], "tube": ["chrome"],
        "browser": ["chrome", "msedge", "firefox"],
        "edge": ["msedge"], "microsoft edge": ["msedge"],
        "firefox": ["firefox"], "brave": ["brave"],
        "vscode": ["Code"], "vs code": ["Code"], "code": ["Code"],
        "visual studio code": ["Code"],
        "notepad": ["notepad"], "notepad plus plus": ["notepad++"],
        "calculator": ["Calculator", "calc"], "calc": ["Calculator", "calc"],
        "explorer": ["explorer"], "file explorer": ["explorer"],
        "file manager": ["explorer"],
        "this pc": ["explorer"], "my computer": ["explorer"],
        "cmd": ["cmd"], "command prompt": ["cmd"],
        "terminal": ["WindowsTerminal"], "windows terminal": ["WindowsTerminal"],
        "powershell": ["powershell"], "task manager": ["Taskmgr"],
        "word": ["WINWORD"], "microsoft word": ["WINWORD"],
        "excel": ["EXCEL"], "microsoft excel": ["EXCEL"],
        "powerpoint": ["POWERPNT"], "microsoft powerpoint": ["POWERPNT"],
        "outlook": ["OUTLOOK"], "teams": ["ms-teams", "Teams"],
        "zoom": ["zoom"], "discord": ["Discord"], "spotify": ["Spotify"],
        "whatsapp": ["WhatsApp"], "telegram": ["Telegram"],
        "vlc": ["vlc"], "photoshop": ["photoshop"],
        "paint": ["mspaint"], "ms paint": ["mspaint"],
        "snipping tool": ["SnippingTool"], "photos": ["Photos"],
        "camera": ["Camera"], "sticky notes": ["StickyNotes"],
        "onedrive": ["OneDrive"], "steam": ["steam"],
        "git bash": ["bash"], "postman": ["Postman"],
    },
    # One spoken command runs a whole local routine — something cloud
    # assistants need a separate "shortcuts" app to do.
    "routines": {
        "study mode": ["open vs code", "open youtube", "volume down"],
        "work mode": ["open vs code", "open gmail", "check battery"],
        "coding mode": ["open vs code", "open github", "volume down"],
        "movie mode": ["open netflix", "volume up"],
        "good morning": ["what is the time", "check battery", "system status"],
        "focus mode": ["close youtube", "close spotify", "volume mute"],
    },
    # "undo that" inverts the previous device action; "do that again" repeats it.
    "undo_pairs": {
        "volume up": "volume down", "volume down": "volume up",
        "volume mute": "volume mute",
        "play music": "pause music", "pause music": "play music",
    },
    "timer_check_seconds": 1.0,
    # Friendly site names -> URL (opened on explicit "open <site>" commands).
    "allowed_urls": {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://www.github.com",
        "chatgpt": "https://chatgpt.com",
        "gemini": "https://gemini.google.com",
        "gmail": "https://mail.google.com",
        "wikipedia": "https://www.wikipedia.org",
        "netflix": "https://www.netflix.com",
        "stackoverflow": "https://stackoverflow.com",
        "stack overflow": "https://stackoverflow.com",
        "amazon": "https://www.amazon.com",
        "flipkart": "https://www.flipkart.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "linkedin": "https://www.linkedin.com",
        "reddit": "https://www.reddit.com",
        "spotify": "https://open.spotify.com",
        "hotstar": "https://www.hotstar.com",
        "prime video": "https://www.primevideo.com",
        "canva": "https://www.canva.com",
        "google drive": "https://drive.google.com",
        "google docs": "https://docs.google.com",
        "google sheets": "https://sheets.google.com",
        "google meet": "https://meet.google.com",
        "google maps": "https://maps.google.com",
        "maps": "https://maps.google.com",
        "translate": "https://translate.google.com",
        "news": "https://news.google.com",
        "weather": "https://weather.google.com",
        "geeksforgeeks": "https://www.geeksforgeeks.org",
        "leetcode": "https://leetcode.com",
        "udemy": "https://www.udemy.com",
        "coursera": "https://www.coursera.org",
        "tutedude": "https://tutedude.com",
    },
}

# ---------------------------------------------------------------- servers
HUD = {
    "port": 8501,
    "title": "ORION ELITE // COMMAND CENTER",
    "theme": {
        "primary": "#00e5ff",   # Orion cyan
        "accent": "#ff8a00",    # Elite amber
        "danger": "#ff0066",
        "bg": "#05070d",
        "panel": "#0b1018",
    },
}

MOBILE = {
    "host": "0.0.0.0",          # required for phone access
    "port": 5000,
    "ngrok_enabled": False,     # flip to True after adding your authtoken
    "ngrok_token": os.getenv("NGROK_AUTHTOKEN", ""),
}

# ---------------------------------------------------------------- logging
LOG_LEVEL = "INFO"
