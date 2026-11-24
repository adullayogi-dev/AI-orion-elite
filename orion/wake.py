"""
Wake-word activation — the 'always listening' guard from the diagrams.

Pipeline:  microphone -> 80 ms chunks -> OpenWakeWord score (0.0-1.0)
           -> if score > threshold : ACTIVATE
           -> send to next stage.

Because a trained `hey_orion` acoustic model is not shipped by OpenWakeWord,
Orion Elite also verifies the phrase with Whisper (keyword mode) and accepts
an instant spacebar trigger (keyboard mode). All three can run at once.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

import config
from orion.audio import AudioEngine
from orion.logger import log
from orion.speech import SpeechEngine


@dataclass
class Activation:
    triggered: bool = False
    method: str = ""
    text: str = ""
    score: float = 0.0


class WakeDetector:
    def __init__(self, audio: AudioEngine, speech: SpeechEngine) -> None:
        self.audio = audio
        self.speech = speech
        self._oww = None
        self._oww_ready = False
        self._last_trigger = 0.0
        self._space_pressed = False

    # ---------------------------------------------------------------- acoustic
    def load_acoustic(self) -> bool:
        """Load the OpenWakeWord ONNX model. Never uses tflite (Ep. 4 guide)."""
        if self._oww_ready:
            return True
        try:
            from openwakeword.model import Model

            custom = config.WAKE.get("custom_model_path")
            models = [custom] if custom and __import__("pathlib").Path(custom).is_file() \
                else [config.WAKE["model"]]

            try:
                self._oww = Model(
                    wakeword_models=models,
                    inference_framework=config.WAKE["inference_framework"],
                )
            except Exception:
                log.warning("Wake model missing — downloading ONNX resources ...")
                from openwakeword import utils

                utils.download_models()
                self._oww = Model(
                    wakeword_models=models,
                    inference_framework=config.WAKE["inference_framework"],
                )
            self._oww_ready = True
            log.info("Wake-word model loaded (%s)", models[0])
            return True
        except Exception as exc:
            log.warning("Acoustic wake word unavailable: %s", exc)
            self._oww = None
            return False

    def acoustic_scores(self, chunk: np.ndarray) -> dict[str, float]:
        if not self._oww_ready or self._oww is None:
            return {}
        try:
            preds = self._oww.predict(chunk)
            return {str(k): float(v) for k, v in preds.items()}
        except Exception as exc:
            log.debug("Wake predict error: %s", exc)
            return {}

    def reset_acoustic(self) -> None:
        """Clear the model's rolling state so it cannot double-trigger."""
        if self._oww is not None:
            try:
                self._oww.reset()
            except Exception:
                pass

    # ---------------------------------------------------------------- keyboard
    @staticmethod
    def _keyboard_hit() -> bool:
        """Non-blocking spacebar check. No admin rights required (msvcrt)."""
        try:
            import msvcrt

            if msvcrt.kbhit():
                ch = msvcrt.getch()
                return ch in (b" ", b"\r", b"\n")
        except Exception:
            pass
        return False

    # ---------------------------------------------------------------- main loop
    def wait(
        self,
        timeout: float | None = None,
        mode: str = "auto",
        speech_gate: float | None = None,
    ) -> Activation:
        """
        Block until activation. Uses ONE microphone stream for every mode.

        mode = 'auto'      -> acoustic + keyword + keyboard (recommended)
               'acoustic'  -> OpenWakeWord scores only (diagram behaviour)
               'keyword'   -> Whisper verifies 'Orion' in short audio windows
               'keyboard'  -> spacebar only (silent rooms / testing)
        """
        mode = mode.lower()
        use_acoustic = mode in ("auto", "acoustic") and config.WAKE["enabled"]
        if use_acoustic:
            use_acoustic = self.load_acoustic()

        use_keyword = mode in ("auto", "keyword")
        use_keyboard = mode in ("auto", "keyboard")

        samplerate = self.audio.samplerate  # 16 kHz for Whisper / wake model
        chunk_size = config.AUDIO["chunk_size"]
        input_block = self.audio.stream_chunk_size
        keyword_seconds = config.WAKE["keyword_timeout"]
        needed = int(keyword_seconds * samplerate / chunk_size)
        gate = speech_gate if speech_gate is not None else config.WAKE["keyword_threshold"]

        window: deque[np.ndarray] = deque(maxlen=needed)
        result = Activation()
        started = time.monotonic()
        cooldown = config.WAKE["cooldown_seconds"]

        def fire(method: str, text: str = "", score: float = 0.0) -> None:
            nonlocal result
            if time.monotonic() - self._last_trigger < cooldown:
                return
            if result.triggered:
                return
            result = Activation(True, method, text, score)
            self._last_trigger = time.monotonic()
            self.reset_acoustic()

        def callback(indata, frames, time_info, status):
            if status:
                log.debug("Wake stream: %s", status)
            chunk = indata[:, 0].astype(np.float32)
            chunk = self.audio.resample(chunk, self.audio.capture_samplerate, samplerate)
            window.append(chunk.copy())

            if use_acoustic:
                scores = self.acoustic_scores(chunk)
                if scores:
                    name, score = max(scores.items(), key=lambda kv: kv[1])
                    if score > 0.05:
                        log.debug("%s score %.3f", name, score)
                    if score >= config.WAKE["score_threshold"]:
                        fire("acoustic", name, score)

        # Fail gracefully if a selected microphone disappears (e.g. Bluetooth
        # headset asleep) instead of looping forever on PaErrorCode -9996.
        chosen = self.audio.device
        if chosen is not None:
            try:
                info = sd.query_devices(chosen)
                if info.get("max_input_channels", 0) <= 0:
                    raise ValueError("device has no input channels")
            except Exception as exc:
                log.warning("Mic device %s unavailable (%s) — using default input", chosen, exc)
                chosen = None
                self.audio.device = None
                self.audio.capture_samplerate = self.audio.samplerate
                config.AUDIO["device"] = None

        log.info("Wake mode=%s — awaiting '%s' ...", mode, config.WAKE["keyword"])
        try:
            with sd.InputStream(
                samplerate=self.audio.capture_samplerate,
                channels=1,
                blocksize=input_block,
                dtype="float32",
                device=chosen,
                callback=callback,
            ):
                while not result.triggered:
                    if timeout and time.monotonic() - started > timeout:
                        break

                    if use_keyboard and self._keyboard_hit():
                        fire("keyboard", "spacebar")

                    if use_keyword and len(window) >= needed:
                        candidate = np.concatenate(list(window))
                        window.clear()
                        if self.audio.level(candidate) >= gate:
                            # Background music / noise must never trigger wake.
                            # Only transcribe the window when Silero VAD says it
                            # contains real speech, then keep speech segments.
                            if config.AUDIO["vad_enabled"]:
                                if not self.audio.contains_speech(candidate):
                                    sd.sleep(20)
                                    continue
                                candidate = self.audio.vad_filter(candidate)
                            text = self.speech.transcribe(candidate)
                            low = text.lower()
                            variants = config.WAKE.get("keyword_variants") or [config.WAKE["keyword"]]
                            if any(v in low for v in variants):
                                fire("keyword", text, self.audio.level(candidate))

                    sd.sleep(20)
        except KeyboardInterrupt:
            log.info("Wake wait interrupted by user")
        except Exception as exc:
            log.error("Wake loop error: %s", exc)

        return result
