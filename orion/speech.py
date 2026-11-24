"""
Speech engine — Whisper for STT (ears) and neural TTS for the mouth.

Natural voices come from Microsoft Edge's online neural voices via edge-tts
(en-IN-Neerja, hi-IN-Swara, te-IN-Shruti). If the network is unavailable, or
anything fails, it falls back to the installed offline pyttsx3 (SAPI) voice.
Models are loaded lazily so importing this module stays instant.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading

import numpy as np

import config
from orion.logger import log

# Final safety net: raw URLs / Wikipedia citations must never reach the speaker.
_URL_RE = re.compile(r"https?://\S+|www\.\S+|ftp://\S+", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[\s*\d+\s*\]")


def _spoken(text: str) -> str:
    text = _URL_RE.sub(" ", str(text))
    text = _CITATION_RE.sub(" ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" |")


class SpeechEngine:
    def __init__(self) -> None:
        self._whisper = None
        self._tts_lock = threading.Lock()
        self._speak_threads: list[threading.Thread] = []
        self._last_tts_engine = "none"

    # ---------------------------------------------------------------- STT
    @property
    def whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel

            log.info(
                "Loading Whisper '%s' (%s/%s) ...",
                config.SPEECH["whisper_model"],
                config.SPEECH["device"],
                config.SPEECH["compute_type"],
            )
            self._whisper = WhisperModel(
                config.SPEECH["whisper_model"],
                device=config.SPEECH["device"],
                compute_type=config.SPEECH["compute_type"],
            )
            log.info("Whisper ready.")
        return self._whisper

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        beam_size: int | None = None,
    ) -> str:
        """Transcribe a float32 mono buffer to text. Empty audio -> ''."""
        if audio is None or len(audio) == 0:
            return ""
        try:
            # Bias Whisper toward Orion's exact commands / app names / people
            # so "Open Chrome" is not transcribed as "Opening door". language
            # is None -> auto-detect so Telugu / Hindi are understood too.
            use_language = language if language is not None else config.SPEECH["language"]
            segments, _info = self.whisper.transcribe(
                np.asarray(audio, dtype=np.float32).reshape(-1),
                beam_size=beam_size or config.SPEECH["beam_size"],
                language=use_language,
                vad_filter=config.SPEECH["vad_filter"],
                initial_prompt=config.SPEECH.get("initial_prompt"),
                hotwords=config.SPEECH.get("hotwords"),
            )
            text = "".join(sg.text for sg in segments if sg.avg_logprob >-1.0).strip()
            log.debug("Transcribed: %r", text)
            return text
        except Exception as exc:
            log.error("Transcription failed: %s", exc)
            return ""

    # ---------------------------------------------------------------- TTS
    @staticmethod
    def _reply_language(text: str) -> str:
        """Pick a voice from the reply's own script (not the user's preference)."""
        try:
            from orion.i18n import reply_language

            return reply_language(text)
        except Exception:
            if re.search(r"[\u0c00-\u0c7f]", text):
                return "te"
            if re.search(r"[\u0900-\u097f]", text):
                return "hi"
            return "en"

    @staticmethod
    def _edge_rate() -> str:
        """Map pyttsx3 words/min (150 = neutral) onto edge-tts percent."""
        base = config.SPEECH.get("neutral_rate", 150)
        rate = config.SPEECH.get("tts_rate", 150)
        pct = int((rate / base - 1) * 100) if base else 0
        return f"{pct:+d}%"

    def _new_tts(self):
        """Offline fallback voice (Microsoft David / Zira on Windows)."""
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", config.SPEECH["tts_rate"])
        engine.setProperty("volume", config.SPEECH["tts_volume"])
        idx = config.SPEECH["tts_voice_index"]
        if idx is not None:
            voices = engine.getProperty("voices")
            if 0 <= idx < len(voices):
                engine.setProperty("voice", voices[idx].id)
        return engine

    def _speak_neural(self, text: str, lang: str) -> bool:
        """Synthesize with an online neural voice. False -> use local fallback."""
        try:
            import asyncio

            import edge_tts
            import sounddevice as sd
            import soundfile as sf

            voices = config.SPEECH["neural_voices"]
            voice = voices.get(lang, voices["en"])
            path = os.path.join(
                tempfile.gettempdir(), f"orion_tts_{threading.get_ident()}.mp3"
            )

            async def synth() -> None:
                comm = edge_tts.Communicate(
                    text, voice, rate=self._edge_rate(), volume="+0%"
                )
                await comm.save(path)

            asyncio.run(asyncio.wait_for(synth(), timeout=12))
            data, samplerate = sf.read(path, dtype="float32")
            try:
                os.remove(path)
            except OSError:
                pass
            sd.play(data, samplerate)
            sd.wait()
            self._last_tts_engine = f"neural:{voice}"
            log.debug("Neural TTS: %s", voice)
            return True
        except Exception as exc:
            log.debug("Neural TTS unavailable (%s) — using local voice", exc)
            return False

    def _speak_local(self, text: str) -> None:
        """Microsoft David, rendered to WAV and softly amplified for clarity."""
        engine = None
        try:
            engine = self._new_tts()
            gain = float(config.SPEECH.get("tts_gain", 1.0))
            if gain > 1.0:
                path = os.path.join(
                    tempfile.gettempdir(),
                    f"orion_david_{threading.get_ident()}.wav",
                )
                try:
                    os.remove(path)
                except OSError:
                    pass
                engine.save_to_file(text, path)
                engine.runAndWait()
                import sounddevice as sd
                import soundfile as sf

                data, samplerate = sf.read(path, dtype="float32")
                try:
                    os.remove(path)
                except OSError:
                    pass
                # tanh lifts quiet syllables while softly capping peaks —
                # louder and clearer than SAPI's volume alone (capped at 1.0).
                import numpy as np

                boosted = np.tanh(data * gain).astype("float32")
                sd.play(boosted, samplerate)
                sd.wait()
                self._last_tts_engine = "local-boosted"
                return
            engine.say(text)
            engine.runAndWait()
            self._last_tts_engine = "local"
        except Exception as exc:
            log.debug("Boosted local TTS failed (%s) — plain voice", exc)
            try:
                if engine is not None:
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                else:
                    self._new_tts().say(text)
                self._last_tts_engine = "local"
            except Exception as exc2:
                log.error("TTS failed: %s", exc2)
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception:
                    pass

    def voices(self) -> list[str]:
        try:
            local = [f"{i}: {v.name}"
                     for i, v in enumerate(self._new_tts().getProperty("voices"))]
        except Exception as exc:
            log.error("Could not list voices: %s", exc)
            local = []
        neural = [f"neural:{v}" for v in config.SPEECH["neural_voices"].values()]
        return local + neural

    def speak(self, text: str, blocking: bool = False, lang: str | None = None) -> None:
        """Speak text aloud. Non-blocking by default so the loop stays responsive."""
        if not text or not str(text).strip():
            return
        text = _spoken(text)
        if not text:
            return
        lang = lang or self._reply_language(text)

        def _run() -> None:
            with self._tts_lock:
                if config.SPEECH.get("neural_tts", True):
                    if self._speak_neural(text, lang):
                        return
                self._speak_local(text)

        if blocking:
            _run()
            return
        t = threading.Thread(target=_run, name="orion-tts", daemon=True)
        t.start()
        self._speak_threads.append(t)
        self._speak_threads = [x for x in self._speak_threads if x.is_alive()]

    # ---------------------------------------------------------------- warmup
    def warmup(self) -> None:
        """Eagerly load models — call from --selftest before the mic opens."""
        _ = self.whisper
        log.info("Speech engine warmed up.")
