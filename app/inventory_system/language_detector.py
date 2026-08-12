"""
language_detector.py
===================

Deterministic language detection — NO LLM. Returns one of:

    "english" | "hindi" | "hinglish" | "marathi"

Method (in order):
  1. Devanagari present?  -> Hindi vs Marathi, decided by distinctive marker
     tokens (e.g. Marathi `आहे`, `मिळ`, `नाही`, `तुम्ही`; Hindi `है`, `क्या`,
     `मिलेगा`, `नहीं`).
  2. Latin script -> Hinglish if romanised Hindi/Marathi tokens are present
     (`hai`, `milega`, `bhejo`, `karoge`, …); Marathi-latin tokens (`ahe`,
     `kiti`, …) -> Marathi; otherwise English.

Distinctive markers are chosen to avoid the ambiguous ones (e.g. Devanagari
`का` means "of" in Hindi but is a question particle in Marathi, so it is NOT
used as a Marathi signal — `आहे`/`मिळ` carry the decision instead).
"""

from __future__ import annotations

import re

ENGLISH, HINDI, HINGLISH, MARATHI = "english", "hindi", "hinglish", "marathi"

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Distinctive Devanagari markers (substring match on raw text)
_MARATHI_DEVA = [
    "आहे", "आहेत", "नाही", "नाहीये", "मिळ", "तुम्ही", "तुला", "किती", "कुठे",
    "कुठं", "आणि", "मला", "दाखव", "पाठव", "येऊ", "बघा", "बघायच", "सवलत",
    "कधी", "वाजता", "उघड", "चालेल", "हवी", "हवंय", "गाडी", "नका", "करा",
]
_HINDI_DEVA = [
    "है", "हैं", "क्या", "नहीं", "मिलेगा", "मिलेगी", "मिलेंगे", "कितने",
    "कितना", "कहाँ", "कहां", "और", "मुझे", "भेजो", "भेज", "कब", "छूट",
    "दिखाओ", "दिखा", "देंगे", "कीमत", "चाहिए", "खुला", "वाली", "वाला",
    "गाड़ी", "हाँ", "दाम",
]

# Romanised Hindi/Hinglish tokens (word-boundary match on lowercased text).
# Deliberately excludes short tokens that collide with English (do/le/ka/ki/ke).
_HINGLISH_LATIN = [
    "hai", "hain", "kya", "kyaa", "milega", "milegi", "milenge", "bhejo",
    "bhej", "karo", "karoge", "karna", "karenge", "kitne", "kitna", "chahiye",
    "nahi", "nahin", "kaise", "kahan", "kahaan", "kab", "mein", "wala", "wali",
    "batao", "dikhao", "dikha", "sakta", "sakti", "sasta", "chalega", "hoga",
    "gaadi", "gadi", "daam", "paisa", "aau", "aana", "aaun", "aaj", "bhav",
    "mol", "kam karo", "le lo", "dedo", "de do",
]
# Romanised Marathi tokens — checked BEFORE the English fallback.
# When >= 1 of these is present AND no strong Hinglish marker fires, → Marathi.
# Chosen to be distinctive (minimal English / Hindi collision).
_MARATHI_LATIN = [
    # Copula / existence
    "aahe", "aahet",       # is / are  (distinct from Hindi "hai/hain")
    "ahe",                 # short form
    "nahiye", "nahit",     # is not / are not
    # Verb forms distinctive to Marathi
    "milel",               # will be available
    "vikli", "vikla", "vikle",  # sold (fem/masc/pl)
    "zali", "zala", "zale",     # happened / became
    "gheun",               # having taken
    "thevu", "theva",      # keep / hold
    "dakhva", "dakhavlele",     # show
    "pathva", "pathvun",   # send
    "sanga", "sangal",     # tell me
    # Question + availability
    "kiti",                # how much
    "kuthe", "kuthay",     # where
    "kasa", "kashi",       # how (masc/fem)
    "sadhya",              # currently / right now
    "ajun",                # still / yet
    # Possessive markers
    "cha", "chi", "che", "chya",   # of / 's  (short but very frequent)
    "madhe",               # in / inside
    # Want / need
    "pahije", "havi", "hava", "hava",
    # Temporal / directional
    "paryant",             # until
    "sandhyakali",         # evening
    # Social address (Marathi-specific)
    "maajhyasathi",        # for me
    "maajha", "maajhi",    # my (masc/fem)
    "tumhi",               # you (plural / formal)
    "bagha", "bagh",       # look / see
    # Compound phrases
    "vikli geli",          # was sold
    "sold zali",           # got sold
    "piece aahe",          # piece/unit is there
    "reel madhe",          # in the reel
]


def _count_markers(text: str, markers) -> int:
    return sum(1 for m in markers if m in text)


def _has_word(text: str, token: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


def detect_language(message: str) -> str:
    """Return english | hindi | hinglish | marathi. Defaults to english."""
    if not message or not message.strip():
        return ENGLISH
    text = message.strip()

    # ── 1) Devanagari script -> Hindi or Marathi ──
    if _DEVANAGARI.search(text):
        marathi_score = _count_markers(text, _MARATHI_DEVA)
        hindi_score = _count_markers(text, _HINDI_DEVA)
        if marathi_score > 0 and marathi_score >= hindi_score:
            return MARATHI
        if hindi_score > 0:
            return HINDI
        return HINDI  # Devanagari but ambiguous -> default Hindi

    # ── 2) Latin script -> Marathi-latin / Hinglish / English ──
    low = text.lower()

    # Score both Marathi and Hinglish markers
    marathi_score = sum(1 for tok in _MARATHI_LATIN if _has_word(low, tok))
    hinglish_score = sum(1 for tok in _HINGLISH_LATIN if _has_word(low, tok))

    # Marathi wins if it has at least 1 distinctive marker AND outscores Hinglish
    # (or ties but has a strong Marathi marker).
    # This prevents Hinglish from swallowing Marathi queries that also contain
    # common tokens like "milel" / "piece".
    if marathi_score > 0:
        if marathi_score >= hinglish_score:
            return MARATHI
        # Marathi loses on count but has strong unique markers -> still Marathi
        _STRONG_MARATHI = {
            "aahe", "aahet", "vikli", "vikla", "zali", "zala",
            "sandhyakali", "maajhyasathi", "paryant", "thevu",
            "sadhya", "vikli geli", "sold zali", "piece aahe", "reel madhe",
        }
        if any(_has_word(low, tok) for tok in _STRONG_MARATHI):
            return MARATHI

    if hinglish_score > 0:
        return HINGLISH
    return ENGLISH


if __name__ == "__main__":
    samples = [
        "Finance available?", "Loan milega?", "Last price?", "Discount?",
        "Address bhejo", "Location send karo", "Exchange karoge?",
        "आज ओपन आहे का?", "फायनान्स मिळेल का?", "गाड़ी का दाम क्या है?",
        "क्या फाइनेंस मिलेगा?",
    ]
    for s in samples:
        print(f"{detect_language(s):9} <- {s}")
