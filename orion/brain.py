"""
Orion Brain — local Ollama reasoning with tool routing and memory.
The LLM is never required for simple actions (open app, search, status),
so Orion stays fast and still answers when Ollama is offline.
"""
from __future__ import annotations

import re

import config
from orion.i18n import (
    detect_language,
    get_language_pref,
    hint_language,
    language_switch_reply,
    localize_reply,
    parse_language_switch,
    script_language,
    set_language_pref,
)
from orion.logger import log
from orion.memory import Memory
from orion.tools import ToolRegistry


class OrionBrain:
    def __init__(self, memory: Memory | None = None, tools: ToolRegistry | None = None):
        self.memory = memory or Memory()
        self.tools = tools or ToolRegistry()
        self._model: str | None = None
        self._checked = False

    # ---------------------------------------------------------------- model
    def _resolve_model(self) -> str:
        if self._model:
            return self._model
        wanted = config.BRAIN["ollama_model"]
        try:
            import ollama

            available = [m["name"] if isinstance(m, dict) else getattr(m, "model", "")
                         for m in ollama.list().models]
            if available:
                if any(wanted in a for a in available):
                    self._model = wanted
                else:
                    fallback = config.BRAIN.get("fallback_model", "")
                    if fallback and any(fallback in a for a in available):
                        self._model = fallback
                    else:
                        self._model = available[0]
                    log.warning("Model '%s' not found — using '%s'", wanted, self._model)
            else:
                self._model = wanted
        except Exception as exc:
            log.debug("Ollama model check skipped: %s", exc)
            self._model = wanted
        self._checked = True
        return self._model

    def set_model(self, name: str) -> None:
        self._model = name
        self._checked = True
        log.info("Brain model set to %s", name)

    # ---------------------------------------------------------------- chat
    def chat(self, text: str, use_tools: bool = True) -> str:
        """Process a user command and return Orion's reply (also stored in memory)."""
        if not text or not text.strip():
            return ""
        text = text.strip()

        low = text.lower()

        # 0. Explicit language switch — before memory/tools/LLM.
        switch = parse_language_switch(text)
        if switch:
            chosen = set_language_pref(switch)
            reply = language_switch_reply(chosen)
            self.memory.add_exchange(text, reply)
            return reply

        lang = detect_language(text)
        # Clear Telugu/Hindi speech auto-switches to that language.
        strong = script_language(text) or hint_language(text)
        if strong and strong != get_language_pref():
            set_language_pref(strong)

        def say(reply: str) -> str:
            """Localise to the user's language, store it, then return it."""
            reply = localize_reply(reply, lang)
            self.memory.add_exchange(text, reply)
            return reply

        # 1. Explicit memory instruction — handled before tools/LLM.
        # Accepts both "remember that X" and "remember X".
        if low.startswith("remember "):
            fact = text[len("remember "):].strip()
            if fact.lower().startswith("that "):
                fact = fact[5:].strip()
            if fact:
                self.memory.remember(fact)
                return say(f"Noted, sir. I will remember that {fact}")

        # 2. Learn simple facts from natural speech, then answer memory
        # questions from memory BEFORE any tool route can steal them.
        self._learn_from(text, low)
        memory_reply = self._memory_reply(low)
        if memory_reply:
            return say(memory_reply)

        # 3. Fast local tools (diagram: 'analyse the command' -> act).
        if use_tools:
            tool_reply = self.tools.route(low)
            if tool_reply:
                return say(tool_reply)

        # 4. Local LLM reasoning with memory.
        return say(self._think(text))

    # ------------------------------------------------------------- memory Q&A
    @staticmethod
    def _clean_value(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip(" .?!,;:\"'").title()

    def _learn_from(self, text: str, low: str) -> None:
        """Store simple identity/preference facts said in normal conversation."""
        name_match = re.search(
            r"\b(?:my name is|i am|call me)\s+([a-z][a-z' -]{0,30})", low
        )
        if name_match:
            value = self._clean_value(name_match.group(1))
            if value and len(value.split()) <= 4:
                self.memory.remember(f"name={value}")

        like_match = re.search(r"\bi (?:like|love)\s+([a-z][a-z' -]{0,30})", low)
        if like_match:
            value = self._clean_value(like_match.group(1))
            if value and len(value.split()) <= 4:
                self.memory.remember(f"likes={value}")

        fav_match = re.search(
            r"\bmy favou?rite ([a-z ]{1,20}?)\s+is\s+([a-z][a-z' -]{0,30})", low
        )
        if fav_match:
            kind = self._clean_value(fav_match.group(1))
            value = self._clean_value(fav_match.group(2))
            self.memory.remember(f"favorite {kind}={value}")

    def _memory_reply(self, low: str) -> str | None:
        """Answer identity / people / college questions from stored memory."""
        facts = self.memory.recall()

        # Team members — answered from memory, never from Wikipedia/search.
        # Whisper misspellings (Abinay, Abhiny, Akshay, ...) are handled too.
        if any(k in low for k in ("abhinay", "abinay", "abhinai", "abhina",
                                  "abhinoy", "abhiney", "abhinav", "abhiny",
                                  "abinai", "akshaya", "akshay", "aksha",
                                  "టీమ్ మెంబర్", "టీమ్ మెంబర్లు", "టీమ్",
                                  "అభినయ్", "అభినయ", "అబినయ్", "అక్షయ",
                                  "टीम मेंबर", "टीम मेंबर्स", "अभिनय", "अक्षय",
                                  "team member")):
            return "They are your team members, Yogi."

        # Project guide (including Whisper's Jyoti/Jyothi variants).
        if any(k in low for k in ("aruna", "aroona", "jyothi", "jyoti",
                                  "jothi", "project guide", "ప్రాజెక్ట్ గైడ్",
                                  "అరుణ", "జ్యోతి", "ज्योति", "अरुणा",
                                  "प्रोजेक्ट गाइड")):
            return "She is your project guide."

        # College / course.
        if any(k in low for k in ("matrusri", "which college", "what college",
                                  "where do we study", "where do you study",
                                  "it students", "what are we", "మాత్రుస్రీ",
                                  "ఎక్కడ చదువు", "కాలేజీ", "मातृस्री", "कॉलेज",
                                  "कहाँ पढ़")):
            return "You are IT students at Matrusri Engineering College, Yogi."

        # User identity.
        if any(k in low for k in ("who am i", "who is yogi", "what is my name",
                                  "whats my name", "do you know my name")):
            return "Your name is Yogi, sir. You are one of the team members."

        if any(k in low for k in ("what is my name", "whats my name", "who am i",
                                  "what am i called", "do you know my name")):
            name = next((f.split("=", 1)[1] for f in facts
                         if f.startswith("name=")), None)
            if not name:
                for msg in reversed([m["content"] for m in self.memory.all_history()
                                     if m["role"] == "user"]):
                    found = re.search(
                        r"\b(?:my name is|i am|call me)\s+([A-Za-z][A-Za-z'-]{0,30})",
                        msg,
                        re.IGNORECASE,
                    )
                    if found:
                        name = self._clean_value(found.group(1))
                        self.memory.remember(f"name={name}")
                        self.memory.save()
                        break
            return (f"Your name is {name}, sir." if name else
                    "I don't know your name yet, sir. Tell me 'I am ...'.")

        if any(k in low for k in ("do you remember", "what did i tell you",
                                  "what did i say", "what do you remember",
                                  "do you know me")):
            if not facts:
                return "I don't have anything saved about you yet, sir."
            plain = [f.replace("=", ": ", 1) for f in facts]
            return "I remember: " + "; ".join(plain) + ", sir."

        return None

    def _think(self, text: str) -> str:
        try:
            import ollama

            messages = self.memory.messages + [{"role": "user", "content": text}]
            # Keep the LLM's prose in the chosen language so long answers and
            # the TTS voice agree, even if the user wrote in English.
            pref = get_language_pref()
            if pref != "en":
                label = {"te": "Telugu", "hi": "Hindi"}.get(pref, "English")
                messages.insert(1, {
                    "role": "system",
                    "content": (f"Reply ONLY in natural, conversational {label}, "
                                "using spoken-style phrasing. Do not switch "
                                "language unless the user explicitly asks."),
                })
            response = ollama.chat(
                model=self._resolve_model(),
                messages=messages,
                options={"timeout": config.BRAIN["timeout"] * 1000},
            )
            if isinstance(response, dict):
                content = response.get("message", {}).get("content", "")
            else:
                message = getattr(response, "message", None)
                content = getattr(message, "content", "") if message else ""
            content = str(content).strip()
            if not content:
                raise ValueError("empty model response")
            return content
        except Exception as exc:
            log.error("Ollama reasoning failed: %s", exc)
            return config.BRAIN["offline_reply"]

    # ---------------------------------------------------------------- status
    def status(self) -> dict:
        try:
            import ollama

            ok = True
            _ = ollama.list()
        except Exception:
            ok = False
        return {
            "ollama_online": ok,
            "model": self._resolve_model(),
            "history_length": len(self.memory.messages),
            "facts": len(self.memory.recall()),
        }
