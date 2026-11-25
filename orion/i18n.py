"""
i18n — language detection, switching and natural replies for Orion.

Whisper auto-detects the spoken language, but the fast "local tool" replies
are written in English. This module detects Telugu / Hindi / English from the
user's text and localises those short confirmations into natural, spoken-style
Telugu or Hindi. It also stores an explicit language preference so a user can
say "speak in Telugu" once and keep talking in English while Orion replies in
Telugu. Long answers (web results, Wikipedia) are left alone because the LLM
system prompt already tells llama3 to match the user's language.
"""
from __future__ import annotations

import json
import re

import config
from orion.logger import log

# Unicode scripts: Telugu U+0C00-0C7F, Devanagari U+0900-097F.
_TELUGU_SCRIPT = re.compile(r"[\u0c00-\u0c7f]")
_DEVANAGARI_SCRIPT = re.compile(r"[\u0900-\u097f]")

# Words that indicate Telugu / Hindi even when the text is transliterated.
_TELUGU_HINTS = (
    "నమస్తే", "ఎలా ఉన్నారు", "ఎవరు", "ఏమిటి", "ఎక్కడ", "చేయి", "ఓపెన్ చేయి",
    "తెరుచు", "మూసి", "సంగీతం", "వాల్యూమ్", "బ్యాటరీ", "స్క్రీన్ షాట్",
    "మాట్లాడు", "ఇంగ్లీష్", "తెలుగులో",
)
_HINDI_HINTS = (
    "नमस्ते", "कैसे हो", "कौन है", "क्या है", "कहाँ", "खोलो", "बंद करो",
    "संगीत", "वॉल्यूम", "बैटरी", "स्क्रीनशॉट", "धन्यवाद",
    "बोलो", "बात करो", "हिंदी में",
)

# Persistent explicit preference (set by "speak in Telugu" etc.).
_PREF_FILE = config.DATA_DIR / "language_pref.json"
_VALID_LANGS = ("en", "hi", "te")

# ---------------------------------------------------------------- switching
# Language names in English, Romanised Indian speech and native scripts.
_LANG_WORDS = {
    "en": r"english|ఇంగ్లీష్|ఇంగ్లిష్|अंग्रेज़ी|अंग्रेजी|angrezi",
    "hi": r"hindi|हिंदी|हिन्दी|హిందీ",
    "te": r"telugu|తెలుగు|तेलुगु",
}
_SWITCH_VERBS = (
    r"speak|talk|reply|respond|converse|switch|change"
    r"|matladu|matla|bolo|bolna|chalo"
)
# Softer verbs only count as commands when they start the utterance.
_SOFT_VERBS = r"use|choose|select"
# Confirmations are spoken in the newly selected language.
_SWITCH_REPLIES = {
    "en": "Okay, I will speak in English.",
    "hi": "ठीक है, अब मैं हिंदी में बोलूँगा।",
    "te": "సరే, ఇక నేను తెలుగులో మాట్లాడుతాను.",
}


def get_language_pref() -> str:
    """Return the explicit language preference ('en' by default)."""
    try:
        data = json.loads(_PREF_FILE.read_text(encoding="utf-8"))
        lang = str(data.get("language", "en")).lower()
        return lang if lang in _VALID_LANGS else "en"
    except Exception:
        return "en"


def set_language_pref(lang: str) -> str:
    """Persist an explicit language choice and return the normalised code."""
    lang = lang if lang in _VALID_LANGS else "en"
    try:
        _PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREF_FILE.write_text(
            json.dumps({"language": lang}, ensure_ascii=False), encoding="utf-8"
        )
        log.info("Language preference set to %s", lang)
    except Exception as exc:
        log.debug("Could not save language preference: %s", exc)
    return lang


def reset_language_pref() -> None:
    """Forget any explicit preference (back to auto / English)."""
    try:
        if _PREF_FILE.exists():
            _PREF_FILE.unlink()
    except Exception as exc:
        log.debug("Could not reset language preference: %s", exc)


def parse_language_switch(text: str) -> str | None:
    """Detect "speak in Telugu", "talk in Hindi", "switch to English", etc."""
    if not text:
        return None
    low = re.sub(r"\s+", " ", text.strip().lower())
    for code, words in _LANG_WORDS.items():
        # "speak in Telugu" / "switch to Hindi" / "change language to English"
        if re.search(rf"\b(?:{_SWITCH_VERBS})\b[^.!?]{{0,24}}\b(?:{words})\b", low):
            return code
        if re.search(rf"^(?:please\s+)?(?:{_SOFT_VERBS})\s+(?:{words})\b", low):
            return code
        # "Telugu lo matladu" / "Hindi mein bolo" / "English lo"
        if re.search(rf"\b(?:{words})\s+(?:lo|mein|me|లో|में)\b", low):
            return code
        # "తెలుగులో మాట్లాడు" / "हिंदी में बोलो"
        if re.search(rf"(?:{words})\s*(?:లో|में)\s*(?:మాట్లాడ|చెప్ప|बोल|बात)", low):
            return code
    return None


def language_switch_reply(lang: str) -> str:
    return _SWITCH_REPLIES.get(lang, _SWITCH_REPLIES["en"])


# ---------------------------------------------------------------- detection
def script_language(text: str) -> str | None:
    """Strong signal: clear Telugu / Devanagari script in the utterance."""
    if not text:
        return None
    te = len(_TELUGU_SCRIPT.findall(text))
    hi = len(_DEVANAGARI_SCRIPT.findall(text))
    if te >= 2 and te >= hi:
        return "te"
    if hi >= 2:
        return "hi"
    return None


def hint_language(text: str) -> str | None:
    """Weaker signal: Telugu / Hindi words in transliterated speech."""
    if not text:
        return None
    low = text.lower()
    te_hits = sum(1 for h in _TELUGU_HINTS if h in low)
    hi_hits = sum(1 for h in _HINDI_HINTS if h in low)
    if te_hits and te_hits >= hi_hits:
        return "te"
    if hi_hits:
        return "hi"
    return None


def detect_language(text: str) -> str:
    """Return 'te', 'hi' or 'en' for the given user text.

    A clear Telugu/Hindi utterance wins immediately. Otherwise the explicit
    preference applies, so the user can switch once and keep talking.
    """
    if not text:
        return get_language_pref()
    return script_language(text) or hint_language(text) or get_language_pref()


def reply_language(text: str) -> str:
    """Language of a REPLY (no preference) — used to choose the TTS voice."""
    return script_language(text) or hint_language(text) or "en"


# Exact canned replies -> natural spoken translations.
_EXACT = {
    "They are your team members, Yogi.":
        {"te": "వాళ్లు మీ టీమ్ మెంబర్లు, యోగి.",
         "hi": "वे आपके टीम मेंबर हैं, योगी।"},
    "She is your project guide.":
        {"te": "ఆమె మీ ప్రాజెక్ట్ గైడ్.",
         "hi": "वे आपकी प्रोजेक्ट गाइड हैं।"},
    "You are IT students at Matrusri Engineering College, Yogi.":
        {"te": "మీరు మాత్రుస్రీ ఇంజనీరింగ్ కాలేజీలో IT చదువుతున్నారు, యోగి.",
         "hi": "आप मातृस्री इंजीनियरिंग कॉलेज में IT पढ़ रहे हैं, योगी।"},
    "Your name is Yogi, sir. You are one of the team members.":
        {"te": "మీ పేరు యోగి, మీరు కూడా టీమ్ మెంబరే.",
         "hi": "आपका नाम योगी है, आप भी टीम मेंबर हैं।"},
    "Volume raised, sir.":
        {"te": "వాల్యూమ్ పెంచాను, యోగి.", "hi": "वॉल्यूम बढ़ा दिया, योगी।"},
    "Volume lowered, sir.":
        {"te": "వాల్యూమ్ తగ్గించాను, యోగి.", "hi": "वॉल्यूम घटा दिया, योगी।"},
    "Volume muted, sir.":
        {"te": "వాల్యూమ్ మ్యూట్ చేశాను, యోగి.", "hi": "वॉल्यूम म्यूट कर दिया, योगी।"},
    "Playing music, sir.":
        {"te": "సంగీతం ప్లే చేస్తున్నాను, యోగి.", "hi": "संगीत चला रहा हूँ, योगी।"},
    "Music paused, sir.":
        {"te": "సంగీతం పాజ్ చేశాను, యోగి.", "hi": "संगीत रोक दिया, योगी।"},
    "Screenshot captured and saved, sir.":
        {"te": "స్క్రీన్ షాట్ తీసి సేవ్ చేశాను, యోగి.",
         "hi": "स्क्रीनशॉट लेकर सेव कर दिया, योगी।"},
    "Closed the active window, sir.":
        {"te": "ఆ విండో మూసేశాను, యోగి.", "hi": "वह विंडो बंद कर दी, योगी।"},
    "Which app should I open, sir?":
        {"te": "ఏ యాప్ తెరవాలి, యోగి?", "hi": "कौन-सा ऐप खोलूँ, योगी?"},
    "I don't have a close rule for that, sir.":
        {"te": "దాన్ని మూసేయడానికి నాకు రూల్ లేదు, యోగి.",
         "hi": "इसे बंद करने का मेरे पास कोई नियम नहीं है, योगी।"},
    "Playing the next track, sir.":
        {"te": "తర్వాతి పాట ప్లే చేస్తున్నాను, యోగి.",
         "hi": "अगला गाना चला रहा हूँ, योगी।"},
    "Playing the previous track, sir.":
        {"te": "మునుపటి పాట ప్లే చేస్తున్నాను, యోగి.",
         "hi": "पिछला गाना चला रहा हूँ, योगी।"},
    "Locking the screen, sir.":
        {"te": "స్క్రీన్ లాక్ చేస్తున్నాను, యోగి.",
         "hi": "स्क्रीन लॉक कर रहा हूँ, योगी।"},
    "Showing the desktop, sir.":
        {"te": "డెస్క్ టాప్ చూపిస్తున్నాను, యోగి.",
         "hi": "डेस्कटॉप दिखा रहा हूँ, योगी।"},
    "Minimizing the window, sir.":
        {"te": "విండోని మినిమైజ్ చేస్తున్నాను, యోగి.",
         "hi": "विंडो को मिनिमाइज़ कर रहा हूँ, योगी।"},
    "Orion standing by, sir. Press SPACE or say Hey Orion when you need me.":
        {"te": "ఓరియన్ రెడీగా ఉంది, యోగి. కావాల్సినప్పుడు స్పేస్ నొక్కండి లేదా 'హే ఓరియన్' అనండి.",
         "hi": "ओरियन तैयार है, योगी। ज़रूरत हो तो स्पेस दबाएँ या 'हे ओरियन' कहें।"},
    # Routines, reminders, notes and undo/repeat.
    "Which routine should I start, sir?":
        {"te": "ఏ రూటిన్ మొదలుపెట్టాలి, యోగి?", "hi": "कौन-सा रूटीन शुरू करूँ, योगी?"},
    "There is nothing to undo, sir.":
        {"te": "వెనక్కి తీయడానికి ఏ పనీ లేదు, యోగి.", "hi": "वापस करने के लिए कोई काम नहीं है, योगी।"},
    "I cannot undo that action, sir.":
        {"te": "ఆ పనిని వెనక్కి తీయలేను, యోగి.", "hi": "मैं वह काम वापस नहीं कर सकता, योगी।"},
    "All reminders cancelled, sir.":
        {"te": "అన్ని రిమైండర్లు రద్దు చేశాను, యోగి.", "hi": "सभी रिमाइंडर रद्द कर दिए, योगी।"},
    "There are no reminders to cancel, sir.":
        {"te": "రద్దు చేయడానికి రిమైండర్లు లేవు, యోగి.", "hi": "रद्द करने के लिए कोई रिमाइंडर नहीं है, योगी।"},
    "Please tell me when to remind you, sir.":
        {"te": "ఎప్పుడు గుర్తు చేయాలో చెప్పండి, యోగి.", "hi": "कब याद दिलाना है, यह बताएँ, योगी।"},
    "You have no notes yet, sir.":
        {"te": "మీ దగ్గర ఇంకా నోట్స్ లేవు, యోగి.", "hi": "आपके पास अभी कोई नोट नहीं है, योगी।"},
    "Notes cleared, sir.":
        {"te": "నోట్స్ తొలగించాను, యోగి.", "hi": "नोट्स हटा दिए, योगी।"},
    "What should I note down, sir?":
        {"te": "ఏమి రాయాలి, యోగి?", "hi": "क्या लिखूँ, योगी?"},
    # Window snapping.
    "Maximizing the window, sir.":
        {"te": "విండోని పెద్దది చేస్తున్నాను, యోగి.", "hi": "विंडो को बड़ा कर रहा हूँ, योगी।"},
    "Restoring the window, sir.":
        {"te": "విండోని పాత పరిమాణంలోకి తెస్తున్నాను, యోగి.", "hi": "विंडो को पहले जैसा कर रहा हूँ, योगी।"},
    "Snapping the window to the left, sir.":
        {"te": "విండోని ఎడమ వైపు పెడుతున్నాను, యోగి.", "hi": "विंडो को बाईं ओर रख रहा हूँ, योगी।"},
    "Snapping the window to the right, sir.":
        {"te": "విండోని కుడి వైపు పెడుతున్నాను, యోగి.", "hi": "विंडो को दाईं ओर रख रहा हूँ, योगी।"},
    # Instant local small-talk replies (handled without the LLM).
    "Hello, Yogi. How can I help?":
        {"te": "హలో యోగి, ఎలా సాయం చేయాలి?", "hi": "नमस्ते योगी, क्या मदद चाहिए?"},
    "I'm doing well, Yogi. Ready when you are.":
        {"te": "నేను బాగున్నాను యోగి, మీరు చెప్పండి.",
         "hi": "मैं ठीक हूँ योगी, बताइए क्या करना है।"},
    "You're welcome, Yogi.":
        {"te": "అదేం పర్లేదు, యోగి.", "hi": "कुछ नहीं, योगी।"},
    "Good morning, Yogi.":
        {"te": "శుభోదయం, యోగి.", "hi": "सुप्रभात, योगी।"},
    "Good evening, Yogi.":
        {"te": "శుభ సాయంత్రం, యోగి.", "hi": "शुभ संध्या, योगी।"},
    "Good night, Yogi.":
        {"te": "శుభ రాత్రి, యోగి.", "hi": "शुभ रात्रि, योगी।"},
}

# Regex patterns -> templates with {app} / {rest} placeholders.
_PATTERNS = [
    (r"^Opening (.+?), sir\.$",
     {"te": "{app} ని తెరుస్తున్నాను, యోగి.", "hi": "{app} खोल रहा हूँ, योगी।"}, "app"),
    (r"^Opened (.+?)(?: in your browser)?, sir\.$",
     {"te": "{app} తెరిచాను, యోగి.", "hi": "{app} खोल दिया, योगी।"}, "app"),
    (r"^Closed (.+?), sir\.$",
     {"te": "{app} మూసేశాను, యోగి.", "hi": "{app} बंद कर दिया, योगी।"}, "app"),
    (r"^(.+?) is not running, sir\. Nothing to close\.$",
     {"te": "{app} రన్ అవ్వడం లేదు, యోగి. మూసేదేం లేదు.",
      "hi": "{app} चल नहीं रहा है, योगी। बंद करने की ज़रूरत नहीं है।"}, "app"),
    (r"^(.+?) is still running, sir\. I could not close it\.$",
     {"te": "{app} ఇంకా రన్ అవుతోంది, యోగి. మూసేయడం కుదరలేదు.",
      "hi": "{app} अभी भी चल रहा है, योगी। इसे बंद नहीं कर पाया।"}, "app"),
    (r"^Noted, sir\. I will remember that (.+)$",
     {"te": "గుర్తుంచుకున్నాను, యోగి — {rest}",
      "hi": "याद रख लिया, योगी — {rest}"}, "rest"),
    (r"^Battery is at (.+), sir\.$",
     {"te": "బ్యాటరీ {rest}, యోగి.", "hi": "बैटरी {rest}, योगी।"}, "rest"),
    (r"^System nominal, sir — (.+)\.$",
     {"te": "సిస్టమ్ బాగుంది, యోగి — {rest}.",
      "hi": "सिस्टम ठीक है, योगी — {rest}."}, "rest"),
    (r"^You have (\d+) reminder\(s\) set, sir\.$",
      {"te": "మీకు {rest} రిమైండర్లు ఉన్నాయి, యోగి.",
       "hi": "आपके पास {rest} रिमाइंडर हैं, योगी।"}, "rest"),
    (r"^Noted: (.+)$",
      {"te": "గుర్తుంచుకున్నాను: {rest}", "hi": "याद रख लिया: {rest}"}, "rest"),
    (r"^Starting (.+?), sir\..*$",
      {"te": "{app} మొదలుపెట్టాను, యోగి.", "hi": "{app} शुरू कर दिया, योगी।"}, "app"),
    (r"^Undoing (.+?), sir\..*$",
      {"te": "{app} వెనక్కి తీస్తున్నాను, యోగి.",
       "hi": "{app} वापस कर रहा हूँ, योगी।"}, "app"),
]

 
def localize_reply(reply: str, lang: str) -> str:
    """Translate a short canned reply into the user's language."""
    if not reply or lang == "en":
        return reply

    exact = _EXACT.get(reply.strip())
    if exact and lang in exact:
        return exact[lang]

    for pattern, templates, group in _PATTERNS:
        m = re.match(pattern, reply.strip(), re.IGNORECASE)
        if m and lang in templates:
            return templates[lang].format(**{group: m.group(1)})

    # Anything longer already comes from the LLM, which follows SYSTEM_PROMPT.
    return reply
