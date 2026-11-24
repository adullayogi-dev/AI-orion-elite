"""
Agent tools — the 'installed tools' box in the Orion diagram.
Wikipedia, live web search, browser automation, PC control, system status.
Every external action is guarded and fails soft so Orion never crashes.
"""
from __future__ import annotations

import difflib
import html
import json
import re
import subprocess
import threading
import time
import urllib.parse
import warnings
import webbrowser
from datetime import datetime
from typing import Callable

import config
from orion.logger import log

# TTS must never read raw URLs or Wikipedia citation markers aloud.
_URL_RE = re.compile(r"https?://\S+|www\.\S+|ftp://\S+", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[\s*\d+\s*\]")


def clean_spoken(text: str) -> str:
    """Strip URLs / citations and collapse whitespace before speech output."""
    if not text:
        return text
    text = _URL_RE.sub(" ", str(text))
    text = _CITATION_RE.sub(" ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)  # no "word ."
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" |")


def resolve_alias(name: str, mapping: dict) -> tuple[str, object] | None:
    """Resolve a friendly name (or near-miss) against a config alias map."""
    if not name:
        return None
    key = re.sub(r"\s+", " ", name.strip().lower()).strip(" .?!,")
    if key in mapping:
        return key, mapping[key]
    for alias, value in mapping.items():
        if alias in key or key in alias:
            return alias, value
    match = difflib.get_close_matches(key, list(mapping), n=1, cutoff=0.62)
    if match:
        return match[0], mapping[match[0]]
    return None


# Wikipedia's dependency emits a noisy "guess the HTML parser" warning.
try:
    from bs4.builder import GuessedAtParserWarning
    warnings.filterwarnings("ignore", category=GuessedAtParserWarning)
except Exception:
    warnings.filterwarnings("ignore", message="No parser was explicitly specified")


# ---------------------------------------------------------------- command fixes
# Whisper (base) sometimes turns a clean command into a similar-sounding
# phrase ("Open Chrome" -> "Opening door"). Deterministic aliases catch the
# known cases; a conservative fuzzy match catches the rest. Free-form
# questions are left untouched so the LLM still handles them.
COMMAND_ALIASES = {
    "opening door": "open chrome",
    "opening for": "open chrome",
    "opening chrome": "open chrome",
    "open the chrome": "open chrome",
    "opening window": "open chrome",
    "close grown": "close chrome",
    "close groan": "close chrome",
    "closing chrome": "close chrome",
    "close the chrome": "close chrome",
    "open vscode": "open vs code",
    "opening vs code": "open vs code",
    "open visual studio code": "open vs code",
    "play some music": "play music",
    "play a song": "play music",
    "pause the music": "pause music",
    "pause the song": "pause music",
    "check the battery": "check battery",
    "battery status": "check battery",
    "how much battery": "check battery",
    "turn up the volume": "volume up",
    "turn down the volume": "volume down",
    "mute the volume": "volume mute",
    "take a screenshot": "take screenshot",
    "take screen shot": "take screenshot",
    "capture screenshot": "take screenshot",
    # Whisper mangles "ChatGPT" in predictable ways. Map the clear ones to a
    # REAL launch instead of letting the LLM pretend it opened something.
    "penchad gpt": "open chatgpt",
    "penchat gpt": "open chatgpt",
    "pencil gpt": "open chatgpt",
    "chennai gpt": "open chatgpt",
}

CANONICAL_COMMANDS = [
    "open chrome", "close chrome", "close window",
    "open vs code", "open notepad", "open calculator",
    "play music", "pause music", "check battery",
    "volume up", "volume down", "volume mute",
    "take screenshot", "search", "system status", "go to sleep",
]


def command_intent(text: str) -> str:
    """Coarse action class of an utterance — used to prevent close->open flips."""
    low = text.strip().lower()
    if re.match(r"^(close|closing|exit|quit|shut)\b", low):
        return "close"
    if re.match(r"^(open|opening|launch|launching|start|starting)\b", low):
        return "open"
    if re.match(r"^(play|pause|resume|stop)\b", low):
        return "music"
    if re.match(r"^volume\b", low):
        return "volume"
    if re.match(r"^(take|capture)\b", low):
        return "screenshot"
    if re.match(r"^check\b", low):
        return "check"
    return "other"


def canonicalize_command(text: str) -> str:
    """Repair Whisper mishearings/casual phrasing before tool routing."""
    if not text or not text.strip():
        return text
    original = re.sub(r"\s+", " ", text.strip().lower()).strip(" .?!,")
    intent = command_intent(original)
    low = original

    # 1. Known mishearings first (substring replacement keeps any extra words).
    for wrong, right in COMMAND_ALIASES.items():
        if wrong in low:
            low = low.replace(wrong, right)

    # 2. A repair must never flip the action: "close notepad" must not become
    #    "open notepad" and re-launch a window the user asked to shut down.
    if intent != "other" and command_intent(low) != intent:
        return original

    # 3. Conservative fuzzy match, restricted to the SAME intent, for short
    #    command-like utterances. Questions are never rewritten.
    if len(low.split()) <= 5:
        candidates = [c for c in CANONICAL_COMMANDS
                      if command_intent(c) == intent]
        if candidates:
            match = difflib.get_close_matches(low, candidates, n=1, cutoff=0.78)
            if match:
                return match[0]
    return low


# Imperative verbs that count as a clear, explicit device command.
_COMMAND_VERBS = (
    "open", "close", "launch", "start", "shut", "exit", "quit",
    "play", "pause", "resume", "stop", "take", "capture", "check",
    "search", "volume", "mute", "unmute", "system status", "system check",
    # window / media controls
    "lock", "show", "minimize", "skip", "next", "previous",
    # routines, reminders, notes, undo/repeat, window snapping
    "remind", "set", "cancel", "note", "write", "read", "clear",
    "activate", "run", "undo", "repeat", "maximize", "restore", "snap",
)
# Polite / wake prefixes that do not change an imperative into dialogue.
_PREFIXES = (
    "hey ", "ok ", "okay ", "orion ", "please ", "pls ", "plz ",
    "can you ", "could you ", "would you ", "will you ", "just ",
    # Indian-English discourse markers at the start of an utterance.
    "accha ", "accha, ", "achha ", "achha, ", "aacha ",
    "theek hai ", "thik hai ", "ok then ", "అచ్చా ", "अच्छा ",
)
# Casual Indian-English tags at the END of an utterance, stripped before the
# imperative check ("open chrome yaar", "close it bro", "check battery sir").
_TRAILING = {
    "yaar", "yaar,", "bro", "bhai", "sir", "please", "pls", "plz",
    "accha", "achha", "theek", "thik", "hai", "okay", "ok", "అచ్చా",
    "अच्छा", "ठीक",
}
# Narration markers mean the user is talking *about* a command, not giving it.
_NARRATION = (
    " i said ", " he said ", " she said ", " they said ", " said that ",
    " my friend ", " someone ", " the movie ", " in the story ",
)


def is_explicit_command(text: str) -> bool:
    """True only for clear imperatives; casual dialogue must not move devices."""
    if not text or not text.strip():
        return False
    low = re.sub(r"\s+", " ", text.strip().lower())
    if any(m in low for m in _NARRATION):
        return False
    if "?" in text:
        return False

    changed = True
    while changed:
        changed = False
        for pre in _PREFIXES:
            if low.startswith(pre):
                low = low[len(pre):].strip()
                changed = True

    words = low.split()
    while words and words[-1].strip(" ,") in _TRAILING:
        words.pop()
    low = " ".join(words)

    # A bare routine name ("study mode") is a deliberate command, not dialogue.
    if low in config.TOOLS.get("routines", {}):
        return True
    # "should I open Chrome?" / "do you think..." are conversation, not orders.
    # The exception is "do that again" — the one 'do' phrase that IS a command.
    if not re.match(r"^do (that|it) again\b", low) and re.match(
            r"^(should|would|could|can|do|did|is|are|will|what|why|how|when|where|who)\b", low):
        return False
    # "do" alone is not a command verb (so "do you know..." stays dialogue),
    # but "do that again" is an explicit repeat instruction.
    return (bool(re.match(r"^do (that|it) again\b", low))
            or any(re.match(rf"^{verb}\b", low) for verb in _COMMAND_VERBS))


class ToolRegistry:
    def __init__(self) -> None:
        self._driver = None
        self._last_app: str | None = None  # for "close it" / "open it"
        self._last_command: str | None = None  # for "undo that" / "do that again"
        self._routes: list[tuple[str, Callable[[str], str | None]]] = []
        # Reminders: in-memory schedule persisted to data/orion_timers.json.
        self._timers: list[dict] = []
        self._timer_lock = threading.Lock()
        self._notifier: Callable[[str], None] | None = None
        self._timer_thread: threading.Thread | None = None
        self._load_timers()
        self._register()

    # ---------------------------------------------------------------- registry
    def _register(self) -> None:
        self._routes = [
            ("routine", self._route_routine),
            ("timer", self._route_timer),
            ("notes", self._route_notes),
            ("undo", self._route_undo),
            ("screenshot", self._route_screenshot),
            ("close", self._route_close),
            ("media", self._route_media),
            ("window", self._route_window),
            ("music", self._route_music),
            ("volume", self._route_volume),
            ("battery", self._route_battery),
            # Apps before websites: "open spotify" means the desktop app, while
            # "open youtube"/"open gmail" fall through to the browser route.
            ("app", self._route_app),
            ("browser", self._route_browser),
            ("help", self._route_help),
            ("time", self._route_time),
            ("search", self._route_search),
            ("wiki", self._route_wiki),
            ("system", self._route_system),
        ]

    # ---------------------------------------------------------------- browser
    def _ensure_driver(self):
        if self._driver is not None or config.TOOLS["browser"] != "chrome":
            return self._driver
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager

            options = webdriver.ChromeOptions()
            options.add_argument("--start-maximized")
            self._driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=options
            )
            log.info("Selenium Chrome driver ready.")
        except Exception as exc:
            log.warning("Selenium unavailable (%s) — using default browser.", exc)
        return self._driver

    def open_url(self, url: str, label: str | None = None, verb: str = "Opening") -> str:
        """Open a URL. Returns a spoken-friendly reply (never raw URLs)."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        # Labels are spoken aloud — never let a URL or citation leak into TTS.
        what = clean_spoken(label) if label else "the page"
        # Remember the site so "close it" can close the browser afterwards.
        if label:
            self._last_app = what.lower()
        driver = self._ensure_driver()
        try:
            if driver is not None:
                driver.get(url)
                log.info("Opened %s", url)
                return f"{verb} {what}, sir."
            webbrowser.open(url)
            log.info("Opened %s", url)
            return f"{verb} {what} in your browser, sir."
        except Exception as exc:
            log.error("Browser open failed: %s", exc)
            try:
                webbrowser.open(url)
                return f"Opening {what} in your browser, sir."
            except Exception:
                return f"I could not open {what}, sir."

    @staticmethod
    def _clean_query(query: str) -> str:
        """Remove command filler so 'open youtube and play a song' stays clean."""
        filler = {"open", "play", "a", "an", "the", "and", "in", "on",
                  "browser", "chrome", "youtube", "song", "for", "me", "please"}
        words = [w for w in re.findall(r"[a-z0-9']+", query.lower()) if w not in filler]
        return " ".join(words).strip()

    def _youtube(self, query: str = "") -> str:
        clean = self._clean_query(query)
        if not clean:
            return self.open_url(config.TOOLS["allowed_urls"]["youtube"],
                                 label="YouTube")
        encoded = urllib.parse.quote(clean)
        return self.open_url(
            f"https://www.youtube.com/results?search_query={encoded}",
            label=f"YouTube for {clean}",
            verb="Searching",
        )

    def _google(self, query: str = "") -> str:
        clean = self._clean_query(query)
        if not clean:
            return self.open_url(config.TOOLS["allowed_urls"]["google"],
                                 label="Google")
        return self.open_url(
            "https://www.google.com/search?q=" + urllib.parse.quote(clean),
            label=f"Google for {clean}",
            verb="Searching",
        )

    # ---------------------------------------------------------------- PC control
    def open_app(self, name: str) -> str:
        if not config.TOOLS["allow_pc_control"]:
            return "PC control is disabled in config, sir."
        found = resolve_alias(name, config.TOOLS["allowed_apps"])
        if found is None:
            return f"I don't have a launch rule for '{name}', sir."
        key, target = found
        try:
            # Windows: paths with spaces (Chrome) need quoting, and UWP aliases
            # like calc.exe only resolve through `start`. Popen(target,
            # shell=True) silently failed for both while still reporting success.
            subprocess.Popen(f'start "" "{target}"', shell=True)
            log.info("Launched %s (%s)", key, target)
            # Remember the resolved name so "close it" targets the same app.
            self._last_app = key
            return f"Opening {key}, sir."
        except Exception as exc:
            log.error("App launch failed: %s", exc)
            return f"I could not open {key}, sir."

    # ---------------------------------------------------------------- Wikipedia
    @staticmethod
    def wikipedia(query: str) -> str:
        if not query:
            return "Please tell me what to look up, sir."
        try:
            import wikipedia

            wikipedia.set_user_agent("ORION-ELITE/1.0 (local AI assistant)")
            summary = wikipedia.summary(
                query,
                sentences=config.TOOLS["wikipedia_sentences"],
                auto_suggest=True,
                redirect=True,
            )
            if summary:
                # Remove web addresses before Orion speaks the summary.
                summary = re.sub(r'http\S+|www\S+', '', summary).strip()
                summary = clean_spoken(summary)
                return f"Here is what I found: {summary}"
        except BaseException as exc:  # includes native-library panics
            log.debug("Wikipedia lookup failed: %s", exc)
        # Fallback: live web results when Wikipedia has no article.
        return ToolRegistry.web_search(query)

    # ---------------------------------------------------------------- web search
    @staticmethod
    def web_search(query: str) -> str:
        """DuckDuckGo search with an HTML fallback for API/version changes.

        DDGS.__init__ calls warnings.simplefilter("always") globally, which
        re-enables every NumPy/sounddevice deprecation warning *after* a search.
        catch_warnings() restores the project's filters on exit, so searching
        can never make unrelated warnings reappear in the voice terminal.
        """
        if not query:
            return "Please tell me what to search for, sir."
        n = config.TOOLS["search_results"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # DDGS resets the filter to "always" before emitting its own
            # rename warning, so filters alone cannot silence it.
            warnings.showwarning = lambda *args, **kwargs: None
            try:
                from duckduckgo_search import DDGS

                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=n))
                if results:
                    # Short snippets carry the actual current information.
                    # clean_spoken removes URLs so nothing is ever read aloud.
                    lines = []
                    for i, r in enumerate(results[:n], 1):
                        title = clean_spoken(html.unescape(r.get("title", "")))
                        body = clean_spoken(html.unescape(
                            r.get("body") or r.get("snippet") or ""))
                        if len(body) > 120:
                            body = body[:117].rsplit(" ", 1)[0] + "..."
                        lines.append(f"{i}. {title}" + (f" - {body}" if body else ""))
                    return clean_spoken("Here are the top results: " + " | ".join(lines))
            except BaseException as exc:  # primp/pyo3 panics are not Exceptions
                log.debug("DDGS library search failed: %s", exc)

            # Fallback: scrape the lightweight DuckDuckGo HTML endpoint.
            try:
                import requests

                response_text = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (ORION ELITE)"},
                    timeout=15,
                ).text
                titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', response_text, re.S)
                titles = [html.unescape(re.sub(r"<.*?>", "", t)).strip() for t in titles]
                titles = [t for t in titles if t][:n]
                snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>',
                                      response_text, re.S)
                snippets = [clean_spoken(html.unescape(re.sub(r"<.*?>", "", s)))
                            for s in snippets]
                lines = []
                for i, title in enumerate(titles, 1):
                    body = snippets[i - 1] if i - 1 < len(snippets) else ""
                    if len(body) > 120:
                        body = body[:117].rsplit(" ", 1)[0] + "..."
                    lines.append(f"{i}. {clean_spoken(title)}" +
                                 (f" - {body}" if body else ""))
                if lines:
                    return clean_spoken("Here are the top results: " + " | ".join(lines))
            except BaseException as exc:
                log.debug("HTML search fallback failed: %s", exc)
        return ""

    # ---------------------------------------------------------------- system
    @staticmethod
    def system_status() -> str:
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.4)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            batt = psutil.sensors_battery()
            parts = [
                f"CPU {cpu:.0f}%",
                f"RAM {ram.percent:.0f}%",
                f"disk {disk.percent:.0f}%",
            ]
            if batt:
                parts.append(f"battery {batt.percent:.0f}%"
                             + (" (charging)" if batt.power_plugged else ""))
            return "System nominal, sir — " + ", ".join(parts) + "."
        except Exception as exc:
            log.debug("System stats failed: %s", exc)
            return "I could not read system stats, sir."

    # ---------------------------------------------------------------- routing
    @staticmethod
    def _route_screenshot(txt: str) -> str | None:
        if not any(k in txt for k in ("screenshot", "capture screen", "take a shot",
                                      "grab the screen", "screen capture")):
            return None
        try:
            from datetime import datetime as _dt
            from PIL import ImageGrab
            from pathlib import Path

            folder = config.DATA_DIR / "screenshots"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"orion_{_dt.now():%Y%m%d_%H%M%S}.png"
            ImageGrab.grab().save(path)
            log.info("Screenshot saved: %s", path)
            return "Screenshot captured and saved, sir."
        except Exception as exc:
            log.error("Screenshot failed: %s", exc)
            return "I could not capture the screen, sir."

    @staticmethod
    def _app_running(exe: str | list[str]) -> bool:
        """Verify a process's active status before and after a shutdown.

        Counts only processes with a real window: Chrome keeps background
        helpers alive after the window is gone, so a raw process count would
        falsely report "still running".
        """
        names = [exe] if isinstance(exe, str) else list(exe)
        if not names:
            return False
        name_list = ", ".join(f"'{n}'" for n in names)
        try:
            ps = (f"$p = @(Get-Process -Name {name_list} -ErrorAction SilentlyContinue | "
                  "Where-Object { $_.MainWindowTitle -ne '' }); "
                  "Write-Output $p.Count")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=10)
            lines = (out.stdout or "0").strip().splitlines()
            return int(lines[0]) > 0 if lines else False
        except Exception as exc:
            log.debug("Process check failed for %s: %s", names, exc)
            return True  # cannot verify -> still attempt the close

    def _close_target(self, txt: str) -> tuple[str, list[str]] | None:
        """Resolve a close utterance to a display name + process names."""
        close_apps = config.TOOLS["close_apps"]
        # Longest aliases first: "google chrome" before "chrome", etc.
        for alias in sorted(close_apps, key=len, reverse=True):
            if alias in txt:
                return alias, list(close_apps[alias])
        # Whisper sometimes hears "chrome" as "grown"/"groan".
        if any(w in txt for w in ("grown", "groan", "cr home")):
            return "chrome", list(close_apps["chrome"])
        # "close it" / "close that" -> the app from the previous command.
        if any(k in txt for k in ("it", "that", "this", "the app",
                                  "the application")) and self._last_app:
            found = resolve_alias(self._last_app, close_apps)
            if found:
                return found
            return self._last_app, [self._last_app]
        return None

    def _route_close(self, txt: str) -> str | None:
        """Verify the app is live, shut it down, and NEVER re-launch it."""
        if not re.match(r"^(close|exit|quit|shut)\b", txt):
            return None
        target = self._close_target(txt)
        if target is None:
            if "window" in txt:
                try:
                    import keyboard

                    keyboard.send("alt+f4")
                    return "Closed the active window, sir."
                except Exception as exc:
                    log.debug("Close window failed: %s", exc)
                    return "I could not close the window, sir."
            return "I don't have a close rule for that, sir."

        key, procs = target
        # 1. Verify active status. No launch path exists from here.
        if not self._app_running(procs):
            self._last_app = None
            return f"{key} is not running, sir. Nothing to close."
        # 2. Execute the shutdown only.
        try:
            name_list = ", ".join(f"'{n}'" for n in procs)
            ps = (f"Get-Process -Name {name_list} -ErrorAction SilentlyContinue | "
                  "Where-Object { $_.MainWindowHandle -ne 0 } | "
                  "ForEach-Object { $_.CloseMainWindow() | Out-Null }")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=15)
        except Exception as exc:
            log.debug("Close failed: %s", exc)
            return f"I could not close {key}, sir."
        # 3. Confirm the state actually changed (CloseMainWindow is async).
        time.sleep(1.2)
        if self._app_running(procs):
            return f"{key} is still running, sir. I could not close it."
        self._last_app = None
        return f"Closed {key}, sir."

    @staticmethod
    def _route_media(txt: str) -> str | None:
        """Next / previous track for any player registered with media keys."""
        if any(k in txt for k in ("next track", "next song", "skip song",
                                  "skip track", "play next", "forward song")):
            try:
                import keyboard

                keyboard.press("next track")
                return "Playing the next track, sir."
            except Exception as exc:
                log.debug("Next track failed: %s", exc)
                return "I could not skip the track, sir."
        if any(k in txt for k in ("previous track", "previous song",
                                  "last song", "go back a song")):
            try:
                import keyboard

                keyboard.press("previous track")
                return "Playing the previous track, sir."
            except Exception as exc:
                log.debug("Previous track failed: %s", exc)
                return "I could not go back a track, sir."
        return None

    @staticmethod
    def _route_window(txt: str) -> str | None:
        """Lock the PC or show the desktop with plain Windows shortcuts."""
        if any(k in txt for k in ("lock screen", "lock the screen", "lock pc",
                                  "lock computer", "lock windows")):
            try:
                import keyboard

                keyboard.send("win+l")
                return "Locking the screen, sir."
            except Exception as exc:
                log.debug("Lock failed: %s", exc)
                return "I could not lock the screen, sir."
        if any(k in txt for k in ("show desktop", "go to desktop",
                                  "minimize all windows", "minimize all")):
            try:
                import keyboard

                keyboard.send("win+d")
                return "Showing the desktop, sir."
            except Exception as exc:
                log.debug("Show desktop failed: %s", exc)
                return "I could not show the desktop, sir."
        if any(k in txt for k in ("maximize window", "maximize this window",
                                  "maximize it", "full screen window")):
            try:
                import keyboard

                keyboard.send("win+up")
                return "Maximizing the window, sir."
            except Exception as exc:
                log.debug("Maximize failed: %s", exc)
                return "I could not maximize the window, sir."
        if any(k in txt for k in ("restore window", "restore this window",
                                  "unmaximize window", "un maximize window")):
            try:
                import keyboard

                keyboard.send("win+down")
                return "Restoring the window, sir."
            except Exception as exc:
                log.debug("Restore failed: %s", exc)
                return "I could not restore the window, sir."
        if any(k in txt for k in ("snap left", "snap window left", "move window left",
                                  "left half", "put window left")):
            try:
                import keyboard

                keyboard.send("win+left")
                return "Snapping the window to the left, sir."
            except Exception as exc:
                log.debug("Snap left failed: %s", exc)
                return "I could not snap the window left, sir."
        if any(k in txt for k in ("snap right", "snap window right", "move window right",
                                  "right half", "put window right")):
            try:
                import keyboard

                keyboard.send("win+right")
                return "Snapping the window to the right, sir."
            except Exception as exc:
                log.debug("Snap right failed: %s", exc)
                return "I could not snap the window right, sir."
        if any(k in txt for k in ("minimize window", "minimize this window")):
            try:
                import keyboard

                keyboard.send("win+down")
                return "Minimizing the window, sir."
            except Exception as exc:
                log.debug("Minimize failed: %s", exc)
                return "I could not minimize the window, sir."
        return None

    @staticmethod
    def _route_help(txt: str) -> str | None:
        """Tell the user what Orion can do (no device action)."""
        if re.search(r"\b(open|close|launch|play|pause|search|take|check)\b", txt):
            return None  # a real command containing "help" — let it through
        if not any(k in txt for k in ("help", "what can you do", "list commands",
                                      "show commands", "your commands")):
            return None
        return (
            "I can open and close apps and websites, play, pause and skip music, "
            "adjust volume, take screenshots, check battery and system status, "
            "search the web, answer your questions, and speak in Telugu, Hindi "
            "or English. I also run routines like study mode, set reminders, "
            "save notes, snap windows, and undo or repeat your last action. "
            "Say 'speak in Telugu' to switch languages, and 'go to sleep' when "
            "you are done, sir."
        )

    # ------------------------------------------------------------- routines
    def _route_routine(self, txt: str) -> str | None:
        """One command runs several local actions (study/work/movie mode)."""
        routines = config.TOOLS.get("routines", {})
        name = next((key for key in sorted(routines, key=len, reverse=True)
                     if key in txt), None)
        if name is None:
            if any(k in txt for k in ("start routine", "run routine", "activate routine")):
                return "Which routine should I start, sir?"
            return None
        done = []
        for action in routines[name]:
            try:
                answer = self.route(action, _internal=True)
                if answer:
                    done.append(answer)
            except Exception as exc:
                log.debug("Routine step '%s' failed: %s", action, exc)
        self._last_command = f"start {name}"
        return clean_spoken(f"Starting {name}, sir. " + " ".join(done))

    # ------------------------------------------------------------- reminders
    @staticmethod
    def _timer_file():
        return config.DATA_DIR / "orion_timers.json"

    def _load_timers(self) -> None:
        try:
            now = time.time()
            data = json.loads(self._timer_file().read_text(encoding="utf-8"))
            self._timers = [t for t in data if t.get("due", 0) > now]
        except Exception:
            self._timers = []

    def _save_timers(self) -> None:
        try:
            self._timer_file().parent.mkdir(parents=True, exist_ok=True)
            self._timer_file().write_text(
                json.dumps(self._timers), encoding="utf-8"
            )
        except Exception as exc:
            log.debug("Could not save timers: %s", exc)

    def set_notifier(self, fn: Callable[[str], None]) -> None:
        """Register how a fired reminder should be announced (e.g. speech)."""
        self._notifier = fn

    def _ensure_timer_thread(self) -> None:
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._timer_thread = threading.Thread(
            target=self._timer_loop, name="orion-timers", daemon=True
        )
        self._timer_thread.start()

    def _timer_loop(self) -> None:
        interval = config.TOOLS.get("timer_check_seconds", 1.0)
        while True:
            with self._timer_lock:
                now = time.time()
                due = [t for t in self._timers if t["due"] <= now]
                if due:
                    self._timers = [t for t in self._timers if t["due"] > now]
                    self._save_timers()
            for timer in due:
                log.info("Reminder fired: %s", timer["label"])
                if self._notifier:
                    try:
                        self._notifier(f"Reminder: {timer['label']}, sir.")
                    except Exception as exc:
                        log.debug("Reminder notifier failed: %s", exc)
            time.sleep(interval)

    @staticmethod
    def _parse_duration(txt: str) -> int | None:
        m = re.search(r"\b(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
                      txt, re.IGNORECASE)
        if not m:
            return None
        n = int(m.group(1))
        unit = m.group(2).lower()
        mult = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        return n * mult

    def _route_timer(self, txt: str) -> str | None:
        if (re.search(r"\b(cancel|clear|delete|remove|stop)\b", txt)
                and re.search(r"\b(reminders?|timers?)\b", txt)):
            with self._timer_lock:
                count = len(self._timers)
                self._timers = []
            self._save_timers()
            return ("All reminders cancelled, sir." if count else
                    "There are no reminders to cancel, sir.")
        if (re.search(r"\b(list|show|my|what|check)\b", txt)
                and re.search(r"\b(reminders?|timers?)\b", txt)):
            with self._timer_lock:
                count = len(self._timers)
            return f"You have {count} reminder(s) set, sir."
        if not any(k in txt for k in ("remind me", "set a timer", "set timer",
                                      "start a timer", "timer for")):
            return None
        secs = self._parse_duration(txt)
        if not secs:
            return "Please tell me when to remind you, sir."
        label = re.sub(r"\b(?:remind me|set a timer|set timer|start a timer|timer for)\b",
                       " ", txt)
        label = re.sub(r"\b\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
                       " ", label, flags=re.IGNORECASE)
        while True:
            trimmed = re.sub(r"^(?:in|to|about|for|please|that)\s+", "", label.strip())
            if trimmed == label:
                break
            label = trimmed
        label = re.sub(r"\s+", " ", label).strip(" .?,") or "Reminder"
        with self._timer_lock:
            self._timers.append({"due": time.time() + secs, "label": label})
            self._timers.sort(key=lambda t: t["due"])
        self._save_timers()
        self._ensure_timer_thread()
        human = (f"{secs // 60} minute(s)" if secs >= 60 else f"{secs} second(s)")
        self._last_command = "set reminder"
        return f"I will remind you in {human}, sir. {label}"

    # ------------------------------------------------------------- notes
    @staticmethod
    def _notes_file():
        return config.DATA_DIR / "orion_notes.txt"

    def _route_notes(self, txt: str) -> str | None:
        if any(k in txt for k in ("read my notes", "show my notes", "read notes",
                                  "list notes", "what are my notes")):
            try:
                lines = [x.strip() for x in self._notes_file().read_text(
                    encoding="utf-8").splitlines() if x.strip()]
            except Exception:
                lines = []
            if not lines:
                return "You have no notes yet, sir."
            return clean_spoken("Your notes: " + " | ".join(lines[-3:]))
        if any(k in txt for k in ("clear notes", "delete notes", "erase notes")):
            try:
                self._notes_file().write_text("", encoding="utf-8")
            except Exception as exc:
                log.debug("Clear notes failed: %s", exc)
            return "Notes cleared, sir."
        m = re.match(r"^(?:take a note|note this|write a note|note down)\s*"
                     r"(?:that\s*)?[:,-]?\s*(.+)$", txt)
        if not m:
            return None
        note = clean_spoken(m.group(1)).strip(" .?,")
        if not note:
            return "What should I note down, sir?"
        try:
            path = self._notes_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(existing + note + "\n", encoding="utf-8")
        except Exception as exc:
            log.debug("Save note failed: %s", exc)
            return "I could not save that note, sir."
        self._last_command = "take note"
        return f"Noted: {note}"

    # ------------------------------------------------------------- undo/repeat
    @staticmethod
    def _undo_command(cmd: str) -> str | None:
        pairs = config.TOOLS.get("undo_pairs", {})
        if cmd in pairs:
            return pairs[cmd]
        m = re.match(r"^(open|close)\s+(.+)$", cmd)
        if m:
            verb = "close" if m.group(1) == "open" else "open"
            return f"{verb} {m.group(2)}"
        return None

    def _route_undo(self, txt: str) -> str | None:
        if not any(k in txt for k in ("undo that", "undo last", "undo it",
                                      "do that again", "repeat that", "do it again")):
            return None
        last = self._last_command
        if not last:
            return "There is nothing to undo, sir."
        if any(k in txt for k in ("again", "repeat")):
            answer = self.route(last, _internal=True)
            return answer or "Done, sir."
        # Undoing a routine reverses each of its steps, last one first.
        name = last.replace("start ", "", 1).strip()
        steps = config.TOOLS.get("routines", {}).get(name)
        if steps:
            done = []
            for action in reversed(steps):
                inverse = self._undo_command(action)
                if inverse:
                    answer = self.route(inverse, _internal=True)
                    if answer:
                        done.append(answer)
            return (clean_spoken(f"Undoing {name}, sir. " + " ".join(done))
                    if done else "I cannot undo that routine, sir.")
        inverse = self._undo_command(last)
        if not inverse:
            return "I cannot undo that action, sir."
        answer = self.route(inverse, _internal=True)
        return answer or "Done, sir."

    def _route_browser(self, txt: str) -> str | None:
        # Whitespace-insensitive match: "chat gpt" -> "chatgpt".
        compact = re.sub(r"\s+", "", txt)
        if "youtube" in txt:
            q = self._strip(txt, ["play", "search for", "on youtube", "youtube",
                                  "open", "in chrome", "in browser"])
            return self._youtube(q)
        if "google" in txt and not re.match(r"^(open|go to)\b", txt):
            return self._google(self._strip(txt, ["search for", "on google", "google"]))
        for key, url in config.TOOLS["allowed_urls"].items():
            if key in compact:
                return self.open_url(url, label=key.replace("stack overflow", "Stack Overflow"))
        # Fuzzy site names on explicit open commands ("open pen chad gpt").
        # Short keys like "x" are excluded so they cannot swallow any phrase.
        explicit = re.match(r"^(?:open|go to|launch)\s+(.+)$", txt)
        if explicit:
            raw = re.sub(r"\s+", "", explicit.group(1))
            compact_urls = {
                re.sub(r"\s+", "", key): value
                for key, value in config.TOOLS["allowed_urls"].items()
                if len(re.sub(r"\s+", "", key)) >= 4
            }
            found = resolve_alias(raw, compact_urls)
            if found:
                key, url = found
                return self.open_url(url, label=key)
        # Any explicit domain: "open example.com" / "go to site.org".
        domain = re.search(r"\b(?:open|go to|launch)\s+([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", txt)
        if domain:
            site = domain.group(1)
            return self.open_url(f"https://{site}", label=site)
        # "open chat gpt on chrome" etc. already matched above; anything else
        # with an open-intent becomes a Google search rather than a refusal.
        if re.match(r"^(open|go to|launch)\s+", txt):
            q = self._strip(txt, ["open", "go to", "launch", "on chrome",
                                  "in chrome", "in browser", "please"])
            return self._google(q) if q else None
        return None

    def _route_app(self, txt: str) -> str | None:
        # A shutdown command must never fall through into a launch sequence.
        if re.match(r"^(close|exit|quit|shut|stop)\b", txt):
            return None
        # "open it" / "launch that" -> the app from the previous command.
        if any(k in txt for k in ("open it", "open that", "open the app",
                                  "launch it", "launch that", "start it")):
            if self._last_app:
                return self.open_app(self._last_app)
            return "Which app should I open, sir?"
        if not any(k in txt for k in ("open ", "launch ", "start ")):
            return None
        if any(k in txt for k in ("youtube", "google", "browser")):
            return None  # browser routes own these
        name = re.sub(r"^(please\s+)?(open|launch|start)\s+", "", txt).strip()
        if "." in name:  # a domain, not a local app — let the browser handle it
            return None
        # Only claim names we actually know; websites and unknown phrases fall
        # through to the browser/search routes instead of a canned refusal.
        if resolve_alias(name, config.TOOLS["allowed_apps"]) is None:
            return None
        return self.open_app(name)

    @staticmethod
    def _route_time(txt: str) -> str | None:
        """Answer local date/time questions without a web lookup."""
        if not any(k in txt for k in ("date today", "today's date", "what date",
                                      "what is the date", "what is today's date",
                                      "what day is it", "what day is today",
                                      "what time", "what is the time",
                                      "whats the time", "current time",
                                      "current date", "tell me the time",
                                      "tell me the date", "today is",
                                      "date and time")):
            return None
        now = datetime.now()
        date_part = now.strftime("%A, %d %B %Y")
        time_part = now.strftime("%I:%M %p").lstrip("0")
        if "time" in txt and "date" not in txt:
            return f"It is {time_part}, sir."
        if "date" in txt and "time" not in txt:
            return f"Today is {date_part}, sir."
        return f"It is {date_part}, {time_part}, sir."

    def _route_search(self, txt: str) -> str | None:
        # Freshness questions MUST reach live search. The old blanket "what is"
        # guard sent "What is the latest ...?" to Wikipedia/the LLM, which then
        # invented cricket results instead of reporting real ones.
        fresh_terms = (
            "latest", "newest", "recent", "updated", "updates", "today",
            "current", "news", "score", "scores", "result", "results",
            "live", "happening",
        )
        fresh = any(k in txt for k in fresh_terms)
        triggers = ("search", "find me", "look up", "weather") + fresh_terms
        if not any(k in txt for k in triggers):
            return None
        if not fresh and any(k in txt for k in
                             ("wikipedia", "what is", "who is", "define")):
            return None  # wiki / memory handles it
        # Build a clean query: "what is the latest updated regarding cricket"
        # -> "latest cricket", not "what is the updated regarding cricket".
        q = re.sub(
            r"^(?:what(?:\s+is)?|whats|who(?:\s+is)?|how(?:\s+is)?)\s+(?:the\s+)?",
            "", txt, flags=re.IGNORECASE,
        )
        q = re.sub(r"\b(?:regarding|about|updated|please|sir|tell me|give me)\b",
                   " ", q, flags=re.IGNORECASE)
        q = re.sub(r"\s+", " ", q).strip(" .?,")
        answer = self.web_search(q) if q else ""
        if answer:
            return answer
        # Never let the LLM improvise fresh information when search fails.
        if fresh:
            return "I could not fetch live updates right now, sir. Please try again."
        return None

    def _route_wiki(self, txt: str) -> str | None:
        # Local factual questions are never Wikipedia lookups. Without this
        # guard, "what is the time" becomes a web search and can stall Orion.
        if any(k in txt for k in ("time", "date", "battery", "volume",
                                  "system", "screenshot", "weather")):
            return None
        if any(k in txt for k in ("my name", "who am i", "do you remember",
                                  "what did i", "do you know me",
                                  "abhinay", "abinay", "abhinai", "abhina",
                                  "abhinoy", "abhiney", "abhinav", "abhiny",
                                  "abinai", "akshaya", "akshay", "aksha", "aruna",
                                  "aroona", "jyothi", "jyoti", "jothi",
                                  "matrusri", "team member", "project guide",
                                   "టీమ్", "అభినయ్", "అభినయ", "అక్షయ", "అరుణ",
                                   "జ్యోతి", "మాత్రుస్రీ", "టీమ్ మెంబర్",
                                   "टीम", "अभिनय", "अक्षय", "अरुणा", "ज्योति",
                                   "मातृस्री", "टीम मेंबर")):
            return None
        if not any(k in txt for k in ("what is", "who is", "define", "explain")):
            return None
        q = self._strip(txt, ["what is", "who is", "define", "explain", "please"])
        return self.wikipedia(q) or None

    def _route_system(self, txt: str) -> str | None:
        if any(k in txt for k in ("system status", "system check", "diagnostics",
                                  "how is the system", "cpu usage", "ram usage")):
            return self.system_status()
        return None

    @staticmethod
    def _route_battery(txt: str) -> str | None:
        if not any(k in txt for k in ("check battery", "battery status", "battery level",
                                      "battery percent", "how much battery",
                                      "battery remaining")):
            return None
        try:
            import psutil

            batt = psutil.sensors_battery()
            if not batt:
                return "I could not read the battery, sir."
            state = "charging" if batt.power_plugged else "on battery"
            left = ""
            secs = getattr(batt, "secsleft", -1)
            if isinstance(secs, (int, float)) and secs > 0:
                left = f", about {int(secs // 60)} minutes left"
            return f"Battery is at {batt.percent:.0f}%, {state}{left}, sir."
        except Exception as exc:
            log.debug("Battery check failed: %s", exc)
            return "I could not read the battery, sir."

    @staticmethod
    def _route_volume(txt: str) -> str | None:
        triggers = ("volume up", "volume down", "volume mute", "mute volume",
                    "unmute", "increase volume", "decrease volume",
                    "turn up volume", "turn down volume")
        if not any(k in txt for k in triggers):
            return None
        try:
            import keyboard

            if "mute" in txt or "unmute" in txt:
                key, reply = "volume mute", "Volume muted, sir."
            elif any(k in txt for k in ("volume down", "decrease volume",
                                        "turn down volume")):
                key, reply = "volume down", "Volume lowered, sir."
            else:
                key, reply = "volume up", "Volume raised, sir."
            for _ in range(4):
                keyboard.press(key)
            return reply
        except Exception as exc:
            log.debug("Volume control failed: %s", exc)
            return "I could not change the volume, sir."

    @staticmethod
    def _route_music(txt: str) -> str | None:
        if not any(k in txt for k in ("play music", "pause music", "resume music",
                                      "stop music", "play the music",
                                      "pause the music")):
            return None
        try:
            import keyboard

            # Media-key toggle works with any player that registers for keys.
            keyboard.press("play/pause")
            if "pause" in txt or "stop" in txt:
                return "Music paused, sir."
            return "Playing music, sir."
        except Exception as exc:
            log.debug("Music control failed: %s", exc)
            return "I could not control the music, sir."

    def _route_memory(self, txt: str) -> str | None:
        if txt.startswith("remember that "):
            return "noted"  # brain stores it; tool just acknowledges routing
        return None

    @staticmethod
    def _strip(txt: str, words: list[str]) -> str:
        out = txt
        for w in words:
            out = out.replace(w, " ")
        return re.sub(r"\s+", " ", out).strip(" .?,")

    def route(self, text: str, _internal: bool = False) -> str | None:
        """Return a tool answer for 'text', or None if the LLM should answer.

        Internal calls come from routines / undo / repeat, whose outer command
        was already an explicit instruction, so they skip the command gate.
        """
        if not text or not text.strip():
            return None
        # Repair common Whisper mishearings ("opening door" -> "open chrome")
        # before any handler sees the command.
        txt = canonicalize_command(text)
        # Final safety net: a close command must never reach a launcher.
        original_intent = command_intent(text.strip().lower())
        if original_intent == "close" and command_intent(txt) == "open":
            log.warning("Blocked close->open flip: %r -> %r", text, txt)
            txt = text.strip().lower()
        explicit = _internal or is_explicit_command(txt)
        # Device controls require a clear command. Informational routes
        # (time, search, wiki, system, battery, timer, notes) still answer
        # questions; undo/repeat and routines do move devices, so they need one.
        controls = {"screenshot", "close", "media", "window", "music",
                    "volume", "app", "browser", "routine", "undo"}
        log.debug("Routed command: %r -> %r (explicit=%s)", text.strip().lower(), txt, explicit)
        for _name, handler in self._routes:
            if _name in controls and not explicit:
                continue
            try:
                answer = handler(txt)
                if answer:
                    log.info("Tool route -> %s", _name)
                    # Remember the last real action for "undo that" / "repeat".
                    # Routines, timers, notes and undo set their own value.
                    if _name not in ("routine", "undo", "timer", "notes"):
                        self._last_command = txt
                    return answer
            except Exception as exc:
                log.error("Tool '%s' failed: %s", _name, exc)
        return None

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
