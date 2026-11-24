#!/usr/bin/env python3
"""
ORION ELITE — cinematic HUD (Episode 9, rebuilt).
Run:  python -m streamlit run apps/hud.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

import config
from orion.audio import AudioEngine
from orion.brain import OrionBrain
from orion.logger import log
from orion.speech import SpeechEngine

st.set_page_config(
    page_title=config.HUD["title"],
    page_icon="\U0001F916",
    layout="wide",
    initial_sidebar_state="expanded",
)

C = config.HUD["theme"]
st.markdown(
    f"""
    <style>
      .stApp {{ background: radial-gradient(circle at 20% 0%, #0d1826 0%, {C['bg']} 55%); color: #d8f6ff; }}
      h1, h2, h3 {{ color: {C['primary']}; text-shadow: 0 0 14px {C['primary']}88; }}
      .stButton > button {{
        background: transparent; color: {C['primary']}; font-weight: 700;
        border: 1px solid {C['primary']}; border-radius: 8px;
        box-shadow: 0 0 12px {C['primary']}55; transition: .25s;
      }}
      .stButton > button:hover {{
        background: {C['primary']}; color: #001018; box-shadow: 0 0 22px {C['primary']};
      }}
      div[data-testid="stMetricValue"] {{ color: {C['accent']}; text-shadow: 0 0 10px {C['accent']}; }}
      div[data-testid="stMetricLabel"] {{ color: #7fa6b8; }}
      .stTextInput input {{ background: #0b1018; color: {C['primary']}; border: 1px solid {C['primary']}55; }}
      .block-container {{ padding-top: 1.6rem; }}
      .stCaption, .stMarkdown p {{ color: #7fa6b8; }}
      hr {{ border-color: {C['primary']}33; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ resources
@st.cache_resource(show_spinner="Initialising Orion core ...")
def get_core():
    audio = AudioEngine()
    speech = SpeechEngine()
    brain = OrionBrain()
    speech.warmup()
    return audio, speech, brain


def stats() -> dict:
    try:
        import psutil

        battery = psutil.sensors_battery()
        return {
            "cpu": psutil.cpu_percent(interval=0.15),
            "ram": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage("/").percent,
            "battery": f"{battery.percent:.0f}%" if battery else "n/a",
        }
    except Exception:
        return {"cpu": 0, "ram": 0, "disk": 0, "battery": "n/a"}


if "history" not in st.session_state:
    st.session_state.history = []
if "last_reply" not in st.session_state:
    st.session_state.last_reply = ""

audio, speech, brain = get_core()
s = stats()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("\U0001F916 ORION OS")
    st.caption(f"ELITE BUILD // v{config.APP_VERSION}")
    st.markdown("---")
    st.subheader("\U0001F4BB System Diagnostics")
    c1, c2 = st.columns(2)
    c1.metric("CPU", f"{s['cpu']:.0f}%")
    c2.metric("RAM", f"{s['ram']:.0f}%")
    c3, c4 = st.columns(2)
    c3.metric("DISK", f"{s['disk']:.0f}%")
    c4.metric("BATT", s["battery"])
    st.markdown("---")
    status = brain.status()
    st.caption(f"{'🟢' if status['ollama_online'] else '🔴'} Brain: "
               f"{'ONLINE' if status['ollama_online'] else 'OFFLINE'}")
    st.caption(f"\U0001F9E0 Model: {status['model']}")
    st.caption(f"\U0001F4AC Memory: {status['history_length']} turns / {status['facts']} facts")
    st.caption("\U0001F310 Network: local-first")
    st.markdown("---")
    if st.button("\U0001F9F9 Reset Memory"):
        brain.memory.clear_history()
        st.session_state.history = []
        st.success("Memory cleared.")
        st.rerun()

# ------------------------------------------------------------------ header
st.title("\U0001F3AF ORION COMMAND CENTER")
st.caption("Voice and text interface // local AI, zero cloud dependency")
st.markdown("---")

col_voice, col_log = st.columns([1, 1], gap="large")

with col_voice:
    st.subheader("\U0001F3A4 Voice Interface")
    if st.session_state.last_reply:
        last_user = st.session_state.history[-1][0] if st.session_state.history else ""
        st.info(f"**You:** {last_user}")
        st.success(f"**Orion:** {st.session_state.last_reply}")

    activate = st.button("\U0001F3A4 ACTIVATE MIC", use_container_width=True, type="primary")

    if activate:
        with st.spinner("Listening ... speak now"):
            audio_data = audio.record_until_silence()
        if len(audio_data) == 0:
            st.warning("No speech detected, sir.")
        else:
            text = speech.transcribe(audio_data)
            if not text:
                st.warning("I could not make out the words. Try again, sir.")
            else:
                reply = brain.chat(text)
                st.session_state.history.append((text, reply))
                st.session_state.last_reply = reply
                speech.speak(reply)
                st.rerun()

    st.markdown("##### or type a command")
    with st.form("text_command", clear_on_submit=True):
        typed = st.text_input("Command", placeholder="e.g. system status, search latest AI news")
        send = st.form_submit_button("SEND")
    if send and typed.strip():
        reply = brain.chat(typed.strip())
        st.session_state.history.append((typed.strip(), reply))
        st.session_state.last_reply = reply
        speech.speak(reply)
        st.rerun()

with col_log:
    st.subheader("\U0001F4DC Mission Log")
    box = st.container(height=430, border=True)
    with box:
        if not st.session_state.history:
            st.caption("Awaiting input, sir ...")
        for user, reply in st.session_state.history[-12:]:
            st.markdown(f"**\U0001F464 You:** {user}")
            st.markdown(f"**\U0001F916 Orion:** {reply}")
            st.markdown("---")

st.markdown("---")
st.caption(f"\U0001F916 ORION ELITE SYSTEM // {config.APP_VERSION} // all systems nominal")
