"""
marathi_response.py  —  Phase 7O.5
==================================

Response-LANGUAGE post-processor (NO LLM). When a customer is detected as
Marathi, the deterministic reply paths (response_formatter inventory/attribute
frames + the short crisp chat_service replies) are emitted in Hinglish. FAQ
templates are already Marathi; only these remaining paths leak.

`to_marathi(text)` converts the known Hinglish reply FRAMES to Marathi by
ordered (longest-first) phrase replacement. It changes ONLY the language — the
logic, the data values (model / colour / fuel / price number / address / RC /
NOC / EMI proper nouns) and the structure are untouched. Applied at a single
chokepoint in `chat_service.handle()` and gated on `language == "marathi"`, so
no other language is affected.
"""
from __future__ import annotations

import re

# Hinglish frame  ->  Marathi. Order is applied longest-first so a longer phrase
# is converted before any shorter substring of it.
_MAP = {
    # ── visit pivot / hedges ──
    "aap aaj aa ke dekh lo": "आज येऊन बघा",
    "(abhi available hai, visit pe confirm kar dete hain)":
        "(सध्या उपलब्ध आहे, भेटीत कन्फर्म करतो)",
    "Yeh hamari team aapko visit pe confirm kar degi —":
        "ही माहिती आमची टीम भेटीत कन्फर्म करेल —",

    # ── media multi-match numbered-list trailer ──
    "Number, year, ya reg number bata do.": "नंबर, साल किंवा रजिस्ट्रेशन सांगा.",

    # ── general search: single / multi / not-found / segment / clarify ──
    "Woh abhi available nahi lagti — lekin similar gaadi dikha doon? "
    "Model ya budget bata do, main best nikaal deta hoon.":
        "ती सध्या उपलब्ध नाही — पण तत्सम गाडी दाखवू का? "
        "मॉडेल किंवा बजेट सांगा, मी सर्वोत्तम काढतो.",
    "Kaunsi gaadi pasand aayi — model ya budget bata do, main check karta hoon.":
        "कोणती गाडी आवडली — मॉडेल किंवा बजेट सांगा, मी बघतो.",
    "Konsi dekhni hai — saal ya budget bata do?":
        "कोणती बघायची आहे — साल किंवा बजेट सांगा?",
    "options hain — jaise": "गाड्या आहेत — जसे",
    "abhi available nahi, lekin same type mein": "सध्या उपलब्ध नाही, पण याच प्रकारात",
    "hai — dikha doon?": "आहे — दाखवू का?",
    "dikha doon?": "दाखवू का?",
    "available hai": "उपलब्ध आहे",

    # ── "gaadi nahi mili" variants (attribute not-found) ──
    "Gaadi nahi mili — model ya budget bata do, main check karta hoon.":
        "गाडी सापडली नाही — मॉडेल किंवा बजेट सांगा, मी बघतो.",
    "Gaadi nahi mili — model ya budget bata do.":
        "गाडी सापडली नाही — मॉडेल किंवा बजेट सांगा.",
    "Gaadi nahi mili — model ya registration bata do.":
        "गाडी सापडली नाही — मॉडेल किंवा रजिस्ट्रेशन सांगा.",

    # ── price clause ──
    "iska exact best price main confirm kar ke bata deta hoon":
        "याची नेमकी किंमत मी कन्फर्म करून सांगतो",
    "exact best price main confirm kar ke bata deta hoon":
        "नेमकी किंमत मी कन्फर्म करून सांगतो",

    # ── downpayment / EMI ──
    "Downpayment/EMI visit pe team confirm karegi —":
        "डाउनपेमेंट/EMI भेटीत टीम कन्फर्म करेल —",
    "ke liye estimated downpayment": "साठी अंदाजे डाउनपेमेंट",
    "hoga — exact EMI/terms visit pe confirm.":
        "असेल — नेमकं EMI/अटी भेटीत कन्फर्म.",

    # ── relax note ──
    "thoda adjust kiya": "थोडं ऍडजस्ट केलं",
    "exact colour": "नेमका रंग",
    "exact gear": "नेमका गिअर",
    "exact saal": "नेमका साल",
    "owner count": "मालक संख्या",

    # ── attribute labels ──
    "Insurance type:": "विमा प्रकार:",
    "Insurance details —": "विमा माहिती —",
    "Valid till:": "वैध:",
    "Zero dep:": "झिरो डेप:",
    "Claim history:": "क्लेम हिस्ट्री:",
    "Service history:": "सर्व्हिस हिस्ट्री:",
    "Last service date:": "शेवटची सर्व्हिस तारीख:",
    "Service center:": "सर्व्हिस सेंटर:",
    "Accident free:": "अपघातमुक्त:",
    "Flood damage:": "पूर नुकसान:",
    "Repainted:": "रिपेंट:",
    "Body condition:": "बॉडी अवस्था:",
    "Engine condition:": "इंजिन अवस्था:",
    "Interior condition:": "इंटीरियर अवस्था:",
    "RC status:": "RC स्थिती:",
    "Hypothecation bank:": "हायपोथिकेशन बँक:",
    "Loan closed:": "कर्ज बंद:",
    "NOC available:": "NOC उपलब्ध:",
    "Finance eligible:": "फायनान्स पात्र:",
    "Warranty:": "वॉरंटी:",
    "Expires:": "संपते:",
    "Provider:": "प्रोव्हायडर:",
    "Tyre condition:": "टायर अवस्था:",
    "Brake condition:": "ब्रेक अवस्था:",
    "Clutch condition:": "क्लच अवस्था:",

    # ── yn values (longest first within map ordering) ──
    "No — accident history on record": "नाही — अपघात इतिहास आहे",
    "Yes, flood damage recorded": "हो, पूर नुकसान नोंद",
    "Yes, warranty available": "हो, वॉरंटी उपलब्ध",
    "Yes, accident free": "हो, अपघातमुक्त",
    "No flood damage": "पूर नुकसान नाही",
    "No repainting": "रिपेंट नाही",
    "Yes, repainted": "हो, रिपेंट केलेली",
    "Yes, claim made": "हो, क्लेम केला",
    "No claims": "क्लेम नाही",
    "Yes, available": "हो, उपलब्ध",
    "Not available": "उपलब्ध नाही",
    "Yes, loan closed": "हो, कर्ज बंद",
    "Loan still open": "कर्ज सुरू",
    "Yes, NOC available": "हो, NOC उपलब्ध",
    "NOC not available": "NOC उपलब्ध नाही",
    "No warranty": "वॉरंटी नाही",
    "Data not available.": "माहिती उपलब्ध नाही.",

    # ── media crisp (chat_service Phase 7O.3) ──
    "ke Instagram par photos/reels available hain.":
        "चे Instagram वर फोटो/रील्स उपलब्ध आहेत.",
    "ke Instagram photos/reels abhi available nahi — visit pe dikha denge.":
        "चे Instagram फोटो/रील्स सध्या उपलब्ध नाहीत — भेटीत दाखवू.",
    "ka YouTube video available hai.": "चा YouTube व्हिडिओ उपलब्ध आहे.",
    "ka YouTube video abhi available nahi — visit pe dikha denge.":
        "चा YouTube व्हिडिओ सध्या उपलब्ध नाही — भेटीत दाखवू.",
    "ke photos available hain.": "चे फोटो उपलब्ध आहेत.",
    "ka video available hai.": "चा व्हिडिओ उपलब्ध आहे.",
    "ke photos abhi available nahi — visit pe dikha denge.":
        "चे फोटो सध्या उपलब्ध नाहीत — भेटीत दाखवू.",
    "ka video abhi available nahi — visit pe dikha denge.":
        "चा व्हिडिओ सध्या उपलब्ध नाही — भेटीत दाखवू.",
    # media clarify (chat_service)
    "Kaunsi gaadi ke Instagram photos/reels chahiye?":
        "कोणत्या गाडीचे Instagram फोटो/रील्स हवेत?",
    "Kaunsi gaadi ka YouTube video chahiye?": "कोणत्या गाडीचा YouTube व्हिडिओ हवा?",
    "Kaunsi gaadi ke photos chahiye?": "कोणत्या गाडीचे फोटो हवेत?",
    "Kaunsi gaadi ka video chahiye?": "कोणत्या गाडीचा व्हिडिओ हवा?",

    # ── attribute clarify (chat_service Phase 7O.2) ──
    "Kaunsi gaadi ki insurance details chahiye?": "कोणत्या गाडीची विमा माहिती हवी?",
    "Service history kis gaadi ki dekhni hai?": "कोणत्या गाडीची सर्व्हिस हिस्ट्री बघायची?",
    "Warranty kis gaadi ki dekhni hai?": "कोणत्या गाडीची वॉरंटी बघायची?",
    "RC / loan status kis gaadi ka chahiye?": "कोणत्या गाडीची RC / कर्ज स्थिती हवी?",
    "Owner details kis gaadi ke chahiye?": "कोणत्या गाडीचे मालक तपशील हवेत?",
    "Flood/condition details kis gaadi ki chahiye?":
        "कोणत्या गाडीची पूर/अवस्था माहिती हवी?",
    "Condition kis gaadi ki dekhni hai?": "कोणत्या गाडीची अवस्था बघायची?",

    # ── price follow-up clarify (chat_service Phase 7O.4) ──
    "Kis gaadi ki price chahiye?": "कोणत्या गाडीची किंमत हवी?",

    # ── catalogue (chat_service) ──
    "Kisi specific model/budget ke baare mein pucho, main detail bata deta hoon.":
        "कोणत्याही मॉडेल/बजेटबद्दल विचारा, मी तपशील सांगतो.",
    "Hamare paas total": "आमच्याकडे एकूण",
    "cars hain:": "गाड्या आहेत:",

    # ── Phase 7O.6: consultative-intro scaffolding (Phase 7P.1) ──
    # The consultative layer builds "{prefix}{model}[ aur {model2}]{suffix}\n\n
    # {question}". Model names are DATA (left untouched); only the fixed Hinglish
    # scaffolding is translated here, so a Marathi customer's broad-entry ask
    # ("फॅमिली कार", "ऑटोमॅटिक", "बजेट") gets a Marathi recommendation too.
    # Longest-first ordering (_ORDERED) ensures these win over generic frames.
    #   prefixes (before the first model name)
    "Family ke liye ": "फॅमिलीसाठी ",
    "Pehli car ke liye ": "पहिल्या गाडीसाठी ",
    "City use ke liye ": "सिटी वापरासाठी ",
    "City ke liye ": "सिटीसाठी ",
    "Automatic mein ": "ऑटोमॅटिकमध्ये ",
    "Budget mein ": "बजेटमध्ये ",
    "Sedan mein ": "सेदानमध्ये ",
    "SUV mein ": "SUV मध्ये ",
    "CNG mein ": "CNG मध्ये ",
    #   suffixes (after the model name(s))
    " easy aur reliable hain.": " सोप्या आणि विश्वासार्ह आहेत.",
    " easy aur reliable hai.": " सोपी आणि विश्वासार्ह आहे.",
    " value ke liye best hain.": " किमतीसाठी उत्तम आहेत.",
    " value ke liye best hai.": " किमतीसाठी उत्तम आहे.",
    " hatchback achi hain.": " हॅचबॅक चांगल्या आहेत.",
    " hatchback achi hai.": " हॅचबॅक चांगली आहे.",
    " achi options hain.": " चांगले पर्याय आहेत.",
    " achi option hai.": " चांगला पर्याय आहे.",
    " achi rahengi.": " चांगल्या आहेत.",
    " achi rahegi.": " चांगली आहे.",
    " perfect hain.": " परफेक्ट आहेत.",
    " perfect hai.": " परफेक्ट आहे.",
    " best rahengi.": " उत्तम आहेत.",
    " best rahegi.": " उत्तम आहे.",
    #   the ONE consultative follow-up question per intent
    "Kitne members hain family mein?": "फॅमिलीमध्ये किती सदस्य आहेत?",
    "Daily traffic use ke liye chahiye?": "रोजच्या ट्रॅफिक वापरासाठी हवी?",
    "Daily city use ke liye chahiye?": "रोजच्या सिटी वापरासाठी हवी?",
    "Roz kitne km chalana hota hai?": "रोज किती किमी चालवायचं असतं?",
    "Budget flexible hai ya strict?": "बजेट फ्लेक्सिबल आहे की ठरलेलं?",
    "Budget kitna soch rahe hain?": "बजेट किती विचार करताय?",
    "Zyada city use ya highway?": "जास्त सिटी वापर की हायवे?",
    "City use ya highway use?": "सिटी वापर की हायवे वापर?",
    "Daily running zyada hai?": "रोजचं रनिंग जास्त आहे?",
    #   inter-model connector (only appears inside a consultative two-model lead)
    " aur ": " आणि ",

    # ── single-word fallbacks (applied last via word boundary) ──
    "options hain": "गाड्या आहेत",
}

# Short alphabetic tokens replaced with word boundaries (so "No" never touches
# "NOC", "Yes" never touches a larger token, etc.). Applied after the phrases.
_WORD_MAP = {
    "Haan": "हो",
    "gaadi": "गाडी",
    "gadi": "गाडी",
    "lakh": "लाख",
    "Yes": "हो",
    "No": "नाही",
}

_ORDERED = sorted(_MAP.items(), key=lambda kv: -len(kv[0]))
_WORD_RES = [(re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in
             sorted(_WORD_MAP.items(), key=lambda kv: -len(kv[0]))]


def to_marathi(text: str) -> str:
    """Convert known Hinglish reply frames in `text` to Marathi. Idempotent on
    text that is already Marathi (Devanagari keys are never matched by Latin
    patterns)."""
    if not text:
        return text
    for k, v in _ORDERED:
        if k in text:
            text = text.replace(k, v)
    for pat, v in _WORD_RES:
        text = pat.sub(v, text)
    return text
