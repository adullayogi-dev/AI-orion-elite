"""
Audio engine — the 'ears' of Orion.
Handles device discovery, fixed-length recording, silence-detected recording
and level metering. All audio returned to callers is float32 in [-1, 1].
"""
from __future__ import annotations

import queue
import time
from collections import deque
from typing import Iterator

import numpy as np
import sounddevice as sd

import config
from orion.logger import log


class AudioEngine:
    def __init__(self) -> None:
        self.samplerate: int = config.AUDIO["samplerate"]  # 16 kHz for Whisper
        self.device = config.AUDIO["device"]
        self._vad_broken = False   # fail open if the ONNX model ever errors
        # WDM-KS / Bluetooth mics only open at their native rate, so capture at
        # that rate and resample down to 16 kHz for the models.
        self.capture_samplerate: int = self.samplerate
        if self.device is not None:
            try:
                native = int(sd.query_devices(self.device)["default_samplerate"])
                if native > 0:
                    self.capture_samplerate = native
            except Exception:
                pass

    @property
    def stream_chunk_size(self) -> int:
        """Wake-stream block size in samples at the capture sample rate."""
        return max(1, int(round(config.AUDIO["chunk_size"] *
                                self.capture_samplerate / self.samplerate)))

    @staticmethod
    def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
        """Lightweight linear resample (no extra dependency)."""
        if src == dst or audio.size == 0:
            return audio.astype(np.float32) if audio.size else audio
        n = max(1, int(round(audio.size * dst / src)))
        x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)

    # ---------------------------------------------------------------- devices
    def list_devices(self) -> list[dict]:
        """Return all PortAudio devices with their index and channel counts."""
        try:
            devices = sd.query_devices()
            result = []
            for i, d in enumerate(devices):
                result.append(
                    {
                        "index": i,
                        "name": d.get("name", "?"),
                        "in_channels": d.get("max_input_channels", 0),
                        "out_channels": d.get("max_output_channels", 0),
                        "samplerate": d.get("default_samplerate", 0),
                    }
                )
            return result
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.error("Could not query audio devices: %s", exc)
            return []

    def input_devices(self) -> list[dict]:
        return [d for d in self.list_devices() if d["in_channels"] > 0]

    def describe_devices(self) -> str:
        lines = ["IDX | IN | OUT | NAME"]
        for d in self.list_devices():
            lines.append(
                f"{d['index']:>3} | {d['in_channels']:>2} | {d['out_channels']:>3} | {d['name']}"
            )
        return "\n".join(lines)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def level(audio: np.ndarray) -> float:
        """Peak absolute amplitude of a buffer."""
        if audio is None or audio.size == 0:
            return 0.0
        return float(np.max(np.abs(audio)))

    # ------------------------------------------------------------------ VAD
    def _vad_options(self):
        from faster_whisper.vad import VadOptions

        return VadOptions(
            threshold=config.AUDIO["vad_threshold"],
            min_speech_duration_ms=config.AUDIO["vad_min_speech_ms"],
            min_silence_duration_ms=config.AUDIO["vad_min_silence_ms"],
            speech_pad_ms=config.AUDIO["vad_speech_pad_ms"],
        )

    def speech_segments(self, audio: np.ndarray) -> list[dict]:
        """Silero VAD (ONNX, bundled with faster-whisper) speech timestamps."""
        if (not config.AUDIO["vad_enabled"] or audio is None
                or not isinstance(audio, np.ndarray) or audio.size == 0):
            return []
        try:
            from faster_whisper.vad import get_speech_timestamps

            return get_speech_timestamps(
                np.asarray(audio, dtype=np.float32),
                self._vad_options(),
                sampling_rate=self.samplerate,
            )
        except Exception as exc:
            # A broken VAD must never make Orion deaf — fall back to the
            # energy gate instead of rejecting every command.
            self._vad_broken = True
            log.warning("Silero VAD unavailable (%s) — using energy gate", exc)
            return []

    def contains_speech(self, audio: np.ndarray) -> bool:
        if self._vad_broken or not config.AUDIO["vad_enabled"]:
            return True
        return bool(self.speech_segments(audio))

    def vad_filter(self, audio: np.ndarray) -> np.ndarray:
        """Keep only speech segments; fall back to the original if uncertain."""
        segments = self.speech_segments(audio)
        if not segments:
            return audio
        pieces = []
        for seg in segments:
            start = max(0, int(seg["start"]))
            end = min(len(audio), int(seg["end"]))
            if end > start:
                pieces.append(audio[start:end])
        if not pieces:
            return audio
        return np.concatenate(pieces).astype(np.float32)

    @staticmethod
    def to_float32(raw: np.ndarray, int16: bool = False) -> np.ndarray:
        """Flatten and normalise recorded samples for Whisper."""
        a = np.asarray(raw).reshape(-1)
        if int16:
            return a.astype(np.float32) / 32768.0
        return a.astype(np.float32)

    # ---------------------------------------------------------------- record
    def record(self, seconds: float | None = None) -> np.ndarray:
        """Record a fixed-length command window (Episode 5 style)."""
        seconds = seconds if seconds is not None else config.AUDIO["record_seconds"]
        log.debug("Recording %.1fs of audio", seconds)
        try:
            recording = sd.rec(
                int(seconds * self.capture_samplerate),
                samplerate=self.capture_samplerate,
                channels=1,
                dtype="float32",
                device=self.device,
            )
            sd.wait()
            raw = np.asarray(recording).reshape(-1)
            # Some WDM-KS drivers return garbage floats instead of audio.
            # Reject them and fall back to the system default microphone.
            if raw.size and float(np.max(np.abs(raw))) > 2.0:
                log.error("Mic device %s returned invalid audio — using default input",
                          self.device)
                self.device = None
                self.capture_samplerate = self.samplerate
                config.AUDIO["device"] = None
                return np.array([], dtype=np.float32)
            return self.resample(raw, self.capture_samplerate, self.samplerate)
        except Exception as exc:
            log.error("Recording failed: %s", exc)
            return np.array([], dtype=np.float32)

    def record_until_silence(
        self,
        threshold: float | None = None,
        silence_timeout: float | None = None,
        max_seconds: float | None = None,
    ) -> np.ndarray:
        """
        Dynamic recording using ONE continuous input stream.

        Opening a fresh sd.rec() stream every 0.2 s makes Windows MME drivers
        return silence on every chunk (the stream never settles). Keeping the
        stream open is what makes live speech actually get captured.
        """
        threshold = threshold if threshold is not None else config.AUDIO["silence_threshold"]
        silence_timeout = silence_timeout or config.AUDIO["silence_timeout"]
        max_seconds = max_seconds or config.AUDIO["max_record_seconds"]
        idle_timeout = float(config.AUDIO.get("idle_timeout", 5.0))
        block_seconds = 0.2
        block_samples = max(1, int(round(block_seconds * self.capture_samplerate)))
        chunks: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                log.debug("Record stream: %s", status)
            audio = indata[:, 0].astype(np.float32)
            audio = self.resample(audio, self.capture_samplerate, self.samplerate)
            chunks.put(audio.copy())

        def next_chunk(timeout: float) -> np.ndarray | None:
            try:
                return chunks.get(timeout=timeout)
            except queue.Empty:
                return None

        stream = None
        for attempt in range(2):
            try:
                stream = sd.InputStream(
                    samplerate=self.capture_samplerate,
                    channels=1,
                    blocksize=block_samples,
                    dtype="float32",
                    device=self.device,
                    callback=callback,
                )
                stream.start()
                break
            except Exception as exc:
                log.warning("Could not open mic %s (%s) — trying default input",
                            self.device, exc)
                self.device = None
                self.capture_samplerate = self.samplerate
                config.AUDIO["device"] = None
                block_samples = max(1, int(round(block_seconds * self.capture_samplerate)))
        if stream is None:
            log.error("No microphone stream could be opened")
            return np.array([], dtype=np.float32)

        frames: list[np.ndarray] = []
        preroll: deque[np.ndarray] = deque(maxlen=3)
        pending: list[np.ndarray] = []          # candidates awaiting VAD check
        vad_buffer = np.array([], dtype=np.float32)
        vad_samples = int(
            config.AUDIO["vad_window_ms"] / 1000.0 * self.samplerate
        )
        peak = 0.0
        silence_start: float | None = None
        speaking = False
        started = time.monotonic()
        gate = threshold

        try:
            # First handful of chunks calibrate the room's noise floor.
            noise_levels = []
            for _ in range(3):
                chunk = next_chunk(1.0)
                if chunk is not None:
                    noise_levels.append(self.level(chunk))
            # Median ignores speech that leaks into calibration; cap prevents
            # a loud moment from making the gate impossible to cross.
            noise_floor = float(np.median(noise_levels)) if noise_levels else 0.0
            gate = max(threshold, min(noise_floor * 3.0, 0.15))
            log.info("Listening (noise %.4f, voice gate %.4f) ...", noise_floor, gate)
            print("Speak now ...")
            last_activity = time.monotonic()

            while True:
                # Do not sit in a 20-second empty recording when the user
                # activated Orion but did not actually speak. Return to the
                # wake loop quickly so the next SPACE / "Hey Orion" is instant.
                if (not speaking
                        and time.monotonic() - last_activity > idle_timeout):
                    log.debug("No speech after activation — returning to standby")
                    break
                chunk = next_chunk(0.5)
                if chunk is None:
                    if time.monotonic() - started > max_seconds:
                        break
                    continue

                invalid = bool(chunk.size and float(np.max(np.abs(chunk))) > 2.0)
                level = 0.0 if invalid else self.level(chunk)
                peak = max(peak, level)
                bars = "#" * min(30, int(level / gate * 12)) if gate else ""
                print(f"\r  mic {level:.4f} | gate {gate:.4f} |{bars}", end="", flush=True)

                if invalid:
                    log.error("Mic returned invalid audio — falling back to default input")
                    self.device = None
                    self.capture_samplerate = self.samplerate
                    config.AUDIO["device"] = None
                    continue

                if level >= gate:
                    last_activity = time.monotonic()
                    if speaking:
                        # Speech already accepted — keep streaming without
                        # re-checking every chunk (avoids clipping syllables).
                        frames.append(chunk)
                        silence_start = None
                    else:
                        # Energy alone also catches music/fan noise. Collect a
                        # short window and let Silero VAD decide if it is voice.
                        pending.append(chunk)
                        vad_buffer = (np.concatenate((vad_buffer, chunk))
                                      if vad_buffer.size else chunk.copy())
                        if vad_buffer.size >= vad_samples:
                            if self.contains_speech(vad_buffer):
                                frames.extend(preroll)  # recover first syllable
                                preroll.clear()
                                frames.extend(pending)
                                speaking = True
                                silence_start = None
                                log.debug("VAD accepted speech burst")
                            else:
                                log.debug("VAD rejected non-speech burst")
                            pending.clear()
                            vad_buffer = np.array([], dtype=np.float32)
                elif speaking:
                    if pending:
                        frames.extend(pending)
                        pending.clear()
                        vad_buffer = np.array([], dtype=np.float32)
                    if silence_start is None:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start > silence_timeout:
                        log.debug("Silence detected — finalising command")
                        break
                else:
                    preroll.append(chunk)
                    # A loud burst that never passed VAD is noise — discard it.
                    pending.clear()
                    vad_buffer = np.array([], dtype=np.float32)

                if time.monotonic() - started > max_seconds:
                    log.debug("Max recording time reached")
                    break
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        print(f"\r  peak mic level: {peak:.4f} (gate {gate:.4f}){' ':20}")
        final = (np.concatenate(frames) if frames
                 else np.array([], dtype=np.float32))
        # Final pass: drop any non-speech that slipped between accepted bursts.
        return self.vad_filter(final) if final.size else final

    # ---------------------------------------------------------------- stream
    def stream(self, chunk_size: int | None = None) -> Iterator[np.ndarray]:
        """
        Generator yielding live mono float32 chunks from the microphone.
        Used by the acoustic wake-word pipeline (diagram: 'always listen').
        """
        chunk_size = chunk_size or config.AUDIO["chunk_size"]
        block = max(1, int(round(chunk_size * self.capture_samplerate / self.samplerate)))
        queue: list[np.ndarray] = []

        def callback(indata, frames, time_info, status):
            if status:
                log.debug("Audio stream status: %s", status)
            chunk = indata[:, 0].astype(np.float32)
            queue.append(self.resample(chunk, self.capture_samplerate, self.samplerate))

        try:
            with sd.InputStream(
                samplerate=self.capture_samplerate,
                channels=1,
                blocksize=block,
                dtype="float32",
                device=self.device,
                callback=callback,
            ):
                while True:
                    if queue:
                        yield queue.pop(0)
                    else:
                        sd.sleep(5)
        except Exception as exc:
            log.error("Audio stream failed: %s", exc)
