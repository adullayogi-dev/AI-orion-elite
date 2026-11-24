"""
ORION ELITE core package.

Modules
-------
audio   : microphone capture, fixed/dynamic recording, level metering
speech  : offline Whisper STT + pyttsx3 TTS
wake    : wake-word activation (acoustic / keyword / keyboard)
memory  : persistent conversation memory
tools   : search, Wikipedia, browser and PC automation
brain   : local Ollama reasoning + tool routing
system  : cross-cutting helpers (stats, safe subprocess)
"""
import os
import warnings

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Dependency-level noise (NumPy 2.5 + sounddevice, renamed DDGS package).
# These fire before logger.py loads, so suppress them here at package import.
warnings.filterwarnings(
    "ignore",
    message="Setting the shape on a NumPy array has been deprecated",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message="This package",
    category=RuntimeWarning,
)

__version__ = "1.0.0"
