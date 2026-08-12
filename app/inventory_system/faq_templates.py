"""
faq_templates.py
================

All FAQ response text, kept in ONE place (never hard-coded across the codebase).

Structure:
    FAQ_TEMPLATES[template_key][language] -> str

Languages: english | hindi | hinglish | marathi
Placeholders: {address}, {area}, {maps_url}  (filled by `render`).

Business rules encoded here (Phase 3B):
  * Discounts / negotiation  -> prices are FIXED (template `price_fixed`).
  * Finance / loan           -> may be available for 2014+ vehicles, no
                                guarantee (`finance`); pre-2014 -> `finance_ineligible`.
  * Exchange                 -> available, inspection required, no valuation quote.
  * Address / Location       -> configurable dealership address (+ Maps URL,
                                WhatsApp-location support).
  * Every response gently encourages a visit / inspection.

The dealership details are CONFIGURABLE via `DEALERSHIP` / `configure()`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

LANGUAGES = ("english", "hindi", "hinglish", "marathi")
DEFAULT_LANGUAGE = "english"

# ─────────────────────────────────────────────────────────────────────────────
# Configurable dealership profile (address kept out of templates themselves)
# ─────────────────────────────────────────────────────────────────────────────
DEALERSHIP: Dict[str, Any] = {
    "name": "Assad Motors",
    "address": "Assad Motors, proprietor Raj Kumar Nahata, Vasant Oasis BMC Parking, Y4 Pillar, Marol, Andheri East, Mumbai 400059, Phone: 9977720000",
    "area": "Marol, Andheri East, Mumbai",
    "maps_url": "https://goo.gl/maps/S6av9ZEFr4AFBmmD7?g_st=aw",
    # WhatsApp location-share payload (lat/long filled when known) — support only
    "whatsapp_location": {
        "name": "Assad Motors — Vasant Oasis BMC Parking",
        "address": "Vasant Oasis BMC Parking, Y4 Pillar, Marol, Andheri East, Mumbai 400059",
        "latitude": None,
        "longitude": None,
    },
}


def configure(**overrides: Any) -> None:
    """Override dealership fields at runtime (keeps address configurable)."""
    DEALERSHIP.update(overrides)


def maps_url() -> str:
    return DEALERSHIP["maps_url"]


def whatsapp_location() -> Dict[str, Any]:
    return dict(DEALERSHIP["whatsapp_location"])


# ─────────────────────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────────────────────
FAQ_TEMPLATES: Dict[str, Dict[str, str]] = {
    "address": {
        "english": "Our showroom is at {address}. Google Maps: {maps_url} — you're welcome to come and inspect the cars in person.",
        "hindi": "हमारा शोरूम यहाँ है: {address}। Google Maps: {maps_url} — आप आकर गाड़ियाँ खुद देख सकते हैं।",
        "hinglish": "Hamara showroom yahan hai: {address}. Google Maps: {maps_url} — aap aa ke gaadiyan khud dekh sakte ho.",
        "marathi": "आमचे शोरूम इथे आहे: {address}. Google Maps: {maps_url} — तुम्ही येऊन गाड्या स्वतः बघू शकता.",
    },
    "location": {
        "english": "Here's our location: {maps_url} ({address}). I can share it on WhatsApp too — do drop by to take a look.",
        "hindi": "यह रही हमारी लोकेशन: {maps_url} ({address})। मैं इसे WhatsApp पर भी भेज सकता हूँ — आकर देख लीजिए।",
        "hinglish": "Yeh rahi hamari location: {maps_url} ({address}). Main WhatsApp pe bhi bhej deta hoon — aa ke dekh lo.",
        "marathi": "ही आमची लोकेशन: {maps_url} ({address}). मी WhatsApp वर पण पाठवू शकतो — येऊन बघा.",
    },
    "visit": {
        "english": "Absolutely, please visit us at {area}. You can inspect any car at your own pace — no appointment needed.",
        "hindi": "बिलकुल, आप {area} आ सकते हैं। कोई भी गाड़ी आराम से देख और जाँच सकते हैं — अपॉइंटमेंट की ज़रूरत नहीं।",
        "hinglish": "Bilkul, aap {area} aa sakte ho. Koi bhi gaadi aaram se dekh aur check kar sakte ho — appointment ki zaroorat nahi.",
        "marathi": "नक्कीच, तुम्ही {area} येऊ शकता. कोणतीही गाडी निवांत बघू आणि तपासू शकता — अपॉइंटमेंटची गरज नाही.",
    },
    "timing": {
        "english": "You're welcome through the day — do come by and inspect the cars at {area}. I'll confirm the exact timing for you.",
        "hindi": "आप दिन में कभी भी आ सकते हैं — {area} आकर गाड़ियाँ देख लें। सही समय मैं कन्फर्म कर देता हूँ।",
        "hinglish": "Aap din mein kabhi bhi aa sakte ho — {area} aa ke gaadiyan dekh lo. Exact timing main confirm kar deta hoon.",
        "marathi": "तुम्ही दिवसा कधीही येऊ शकता — {area} येऊन गाड्या बघा. नेमकी वेळ मी कन्फर्म करतो.",
    },
    "finance": {
        "english": "Finance options may be available for eligible vehicles from 2014 onwards. Approval depends on the vehicle and your profile — nothing is guaranteed. Do visit and our team will guide you at {area}.",
        "hindi": "2014 या उसके बाद की पात्र गाड़ियों पर फाइनेंस का विकल्प हो सकता है। मंज़ूरी गाड़ी और आपकी प्रोफ़ाइल पर निर्भर है — कोई गारंटी नहीं। {area} आकर टीम से बात करें।",
        "hinglish": "2014 ke baad ki eligible gaadiyon pe finance ka option ho sakta hai. Approval gaadi aur aapki profile pe depend karta hai — guarantee nahi. {area} aa ke team se baat kar lo.",
        "marathi": "2014 नंतरच्या पात्र गाड्यांवर फायनान्सचा पर्याय असू शकतो. मंजुरी गाडी आणि तुमच्या प्रोफाइलवर अवलंबून — गॅरंटी नाही. {area} येऊन टीमशी बोला.",
    },
    "finance_ineligible": {
        "english": "Finance is generally available only for vehicles from 2014 onwards, so this one may not be eligible. Do come and inspect it at {area} — our team can confirm the options.",
        "hindi": "फाइनेंस आम तौर पर 2014 या बाद की गाड़ियों पर ही मिलता है, तो शायद यह पात्र न हो। {area} आकर देख लें — टीम विकल्प बता देगी।",
        "hinglish": "Finance aam taur pe 2014 ke baad ki gaadiyon pe milta hai, toh shayad yeh eligible na ho. {area} aa ke dekh lo — team options bata degi.",
        "marathi": "फायनान्स साधारणतः 2014 नंतरच्या गाड्यांवरच मिळतो, त्यामुळे ही पात्र नसेल. {area} येऊन बघा — टीम पर्याय सांगेल.",
    },
    "exchange": {
        "english": "Yes, exchange is available. We'll need to inspect your current car before sharing any valuation, so please bring it along when you visit {area}.",
        "hindi": "हाँ, एक्सचेंज उपलब्ध है। किसी भी वैल्यूएशन से पहले आपकी गाड़ी की जाँच करनी होगी — {area} आते समय गाड़ी साथ लाएँ।",
        "hinglish": "Haan, exchange available hai. Valuation se pehle aapki gaadi inspect karni hogi — {area} aate time gaadi saath le aao.",
        "marathi": "हो, एक्सचेंज उपलब्ध आहे. किंमत सांगण्याआधी तुमची गाडी तपासावी लागेल — {area} येताना गाडी सोबत आणा.",
    },
    "price_fixed": {  # discount / negotiation
        "english": "Our prices are fixed — there's no negotiation. The value is in the car itself, so do come and inspect it at {area} before deciding.",
        "hindi": "हमारी कीमतें फ़िक्स हैं — कोई मोल-भाव नहीं। गाड़ी की क्वालिटी ही उसकी कीमत है; {area} आकर खुद देख लें।",
        "hinglish": "Hamare price fixed hain — koi mol-bhaav nahi. Gaadi ki quality hi uski value hai; {area} aa ke khud dekh lo.",
        "marathi": "आमच्या किमती ठरलेल्या आहेत — घासाघीस नाही. गाडीची क्वालिटीच तिची किंमत आहे; {area} येऊन स्वतः बघा.",
    },
    "booking": {
        "english": "You can book a car by visiting us at {area} and completing a short formality with our team. Come take a look and we'll help you book it.",
        "hindi": "गाड़ी बुक करने के लिए {area} आएँ और टीम के साथ छोटी सी प्रक्रिया पूरी करें। आकर देख लें, हम बुकिंग में मदद करेंगे।",
        "hinglish": "Gaadi book karne ke liye {area} aao aur team ke saath chhoti si formality complete karo. Aa ke dekh lo, hum booking mein help karenge.",
        "marathi": "गाडी बुक करण्यासाठी {area} या आणि टीमसोबत छोटी प्रक्रिया पूर्ण करा. येऊन बघा, आम्ही बुकिंगमध्ये मदत करू.",
    },
    # ── Phase 4C.1 additions ─────────────────────────────────────────────────
    "rc_transfer": {
        "english": "Yes — full RC transfer and NOC are handled by us. All documents are verified at the showroom itself, so there are no surprises. Come visit us at {area} for the complete paperwork details.",
        "hindi": "हाँ — RC ट्रांसफर और NOC हम ही संभालते हैं। सारे दस्तावेज़ शोरूम पर ही वेरिफ़ाई हो जाते हैं, कोई झंझट नहीं। {area} आकर पूरी जानकारी लें।",
        "hinglish": "Haan — full RC transfer aur NOC hum handle karte hain. Saare documents showroom pe hi verify ho jaate hain — koi tension nahi. {area} aa ke details lo.",
        "marathi": "हो — RC ट्रान्सफर आणि NOC आम्हीच करतो. सगळे कागदपत्र शोरूममध्येच तपासले जातात — कोणतीही अडचण नाही. {area} येऊन संपूर्ण माहिती घ्या.",
    },
    "price_inclusions": {
        "english": "The quoted price is for the car itself. RTO transfer charges and insurance are separate — you'll get a transparent, itemised breakdown when you visit. No hidden charges whatsoever.",
        "hindi": "कोटेड प्राइस गाड़ी का है। RTO ट्रांसफर और इंश्योरेंस अलग से होगा — {area} आने पर पूरा ट्रांसपेरेंट ब्रेकअप मिलेगा। कोई हिडन चार्ज नहीं।",
        "hinglish": "Quoted price car ka hai. RTO transfer aur insurance alag hoga — {area} pe transparent breakup milega. Koi hidden charge nahi.",
        "marathi": "दिलेली किंमत फक्त गाडीची आहे. RTO ट्रान्सफर आणि विमा वेगळा असेल — {area} येताना संपूर्ण तपशील मिळेल. कोणताही छुपा खर्च नाही.",
    },
    "finance_details": {
        "english": "Finance is available through partner banks and NBFCs. The exact EMI depends on tenure and down payment. For a cash deal we offer the best possible price. Come visit us at {area} and our team will work out the numbers with you.",
        "hindi": "पार्टनर बैंकों और NBFC के ज़रिए फाइनेंस उपलब्ध है। EMI टेन्योर और डाउन पेमेंट पर निर्भर करती है। कैश डील पर बेस्ट प्राइस मिलता है। {area} आकर टीम से बात करें।",
        "hinglish": "Partner banks/NBFC se finance available hai. EMI tenure aur down payment pe depend karti hai. Cash deal pe best price milta hai. {area} aa ke team se baat karo.",
        "marathi": "पार्टनर बँका/NBFC द्वारे फायनान्स उपलब्ध आहे. EMI कालावधी आणि डाउन पेमेंटवर अवलंबून असते. कॅश व्यवहारावर सर्वोत्तम किंमत मिळते. {area} येऊन टीमशी बोला.",
    },
    "warranty": {
        "english": "Warranty or assurance options are available on select vehicles — eligibility is confirmed car by car. Come visit us at {area} and our team will let you know what applies to the car you're interested in.",
        "hindi": "कुछ गाड़ियों पर वारंटी / एश्योरेंस का विकल्प होता है — पात्रता गाड़ी के हिसाब से तय होती है। {area} आएँ, टीम बताएगी।",
        "hinglish": "Select gaadiyon pe warranty / assurance option hota hai — eligibility car-wise confirm hoti hai. {area} aa ke pata karo.",
        "marathi": "निवडक गाड्यांवर वॉरंटी/असुरन्स पर्याय असतो — पात्रता गाडीनुसार निश्चित होते. {area} येऊन टीमला विचारा.",
    },
    "trust_reviews": {
        "english": "We are an established dealership at {area} — verified inventory, honest condition disclosure, and RC transfer included. You're welcome to come and inspect any car yourself. Real cars, real prices.",
        "hindi": "हम {area} के एक स्थापित डीलर हैं — वेरिफाइड इनवेंट्री, ईमानदार कंडीशन बताई जाती है, और RC ट्रांसफर शामिल है। खुद आकर देख लें — असली गाड़ियाँ, सही दाम।",
        "hinglish": "Hum {area} ke established dealer hain — verified inventory, honest condition disclosure, RC transfer included. Khud aa ke dekh lo — real cars, real prices.",
        "marathi": "आम्ही {area} चे एक सुस्थापित डीलर आहोत — सत्यापित यादी, प्रामाणिक अवस्था सांगितली जाते, आणि RC ट्रान्सफर समाविष्ट आहे. स्वतः येऊन बघा.",
    },
    "business_age": {
        "english": "We have been operating as an established used-car dealership at {area} for years. Come visit us — our track record speaks for itself.",
        "hindi": "हम {area} में कई सालों से एक स्थापित यूज़्ड-कार डीलर के रूप में काम कर रहे हैं। आकर मिलें — हमारा रिकॉर्ड खुद बोलता है।",
        "hinglish": "Hum {area} mein kaafi saalon se established used-car dealer hain. Aa ke milo — hamara track record khud bolta hai.",
        "marathi": "आम्ही {area} येथे अनेक वर्षांपासून एक सुस्थापित सेकंड-हँड कार डीलर म्हणून कार्यरत आहोत. येऊन भेटा — आमचा रेकॉर्ड स्वतःच सांगतो.",
    },
    "refund_policy": {
        "english": "Booking and return terms are transparent and provided in writing at the showroom. If a booking is cancelled, our team will walk you through the policy on the spot. Visit us at {area} for full details.",
        "hindi": "बुकिंग और रिटर्न की शर्तें पारदर्शी हैं और शोरूम पर लिखित दी जाती हैं। बुकिंग कैंसल हुई तो टीम पॉलिसी बताएगी। {area} आकर पूरी जानकारी लें।",
        "hinglish": "Booking aur return terms transparent hain — showroom pe likhit milte hain. Booking cancel hui toh team policy explain karegi. {area} aa ke pura pata karo.",
        "marathi": "बुकिंग आणि परतीच्या अटी पारदर्शक आहेत — शोरूममध्ये लेखी दिल्या जातात. बुकिंग रद्द झाल्यास टीम धोरण समजावून सांगेल. {area} येऊन संपूर्ण माहिती घ्या.",
    },
    # ── Phase 4C.2 additions ─────────────────────────────────────────────────
    "general_help": {
        "english": "Sure, happy to help! Could you tell me the model, budget, fuel type or body style (SUV/sedan/hatchback) you're looking for? I'll show you matching cars right away.",
        "hindi": "ज़रूर, मदद करते हैं! कृपया मॉडल, बजट, फ्यूल टाइप या बॉडी स्टाइल (SUV/सेडान/हैचबैक) बताएं — मैं तुरंत मिलती-जुलती गाड़ियाँ दिखाता हूँ।",
        "hinglish": "Bilkul, batao! Model, budget, fuel type ya body style (SUV/sedan/hatchback) bata do — main turant matching gaadiyan dikha deta hoon.",
        "marathi": "नक्कीच, सांगा! मॉडेल, बजेट, इंधन प्रकार किंवा बॉडी स्टाईल (SUV/सेदान/हॅचबॅक) सांगा — मी लगेच जुळणाऱ्या गाड्या दाखवतो.",
    },
    "contact_ack": {
        "english": "Thank you! I've noted your contact details — our team will reach out to you shortly. Meanwhile, tell me a model or budget and I'll show you matching cars.",
        "hindi": "धन्यवाद! मैंने आपका नंबर नोट कर लिया है — हमारी टीम जल्द ही आपसे संपर्क करेगी। तब तक कोई मॉडल या बजट बताएं, मैं मिलती-जुलती गाड़ियाँ दिखाता हूँ।",
        "hinglish": "Thank you! Maine aapka number note kar liya hai — hamari team jaldi aapse contact karegi. Tab tak koi model ya budget batao, main matching cars dikha deta hoon.",
        "marathi": "धन्यवाद! मी तुमचा नंबर नोंदवला आहे — आमची टीम लवकरच तुमच्याशी संपर्क करेल. तोपर्यंत मॉडेल किंवा बजेट सांगा, मी जुळणाऱ्या गाड्या दाखवतो.",
    },
    "more_options": {
        "english": "Here are some more options for you:",
        "hindi": "ये रहे कुछ और विकल्प:",
        "hinglish": "Yeh rahe kuch aur options:",
        "marathi": "हे आणखी काही पर्याय:",
    },
    "no_more_options": {
        "english": "That's all I have matching that right now. Want to adjust the budget or try a different model?",
        "hindi": "अभी इतने ही मिलते-जुलते विकल्प हैं। बजट बदलें या कोई और मॉडल देखें?",
        "hinglish": "Filhaal itne hi matching options hain. Budget adjust karein ya koi aur model dekhein?",
        "marathi": "सध्या एवढेच जुळणारे पर्याय आहेत. बजेट बदलायचे का किंवा दुसरे मॉडेल बघायचे?",
    },
    "greeting": {
        "english": "Hello! Welcome to Assad Motors. I can help you find a used car, check prices, or share photos. What kind of car are you looking for?",
        "hindi": "नमस्ते! Assad Motors में आपका स्वागत है। मैं गाड़ी ढूंढने, कीमत बताने या फोटो भेजने में मदद कर सकता हूँ। आपको किस तरह की गाड़ी चाहिए?",
        "hinglish": "Hello! Assad Motors mein aapka swagat hai. Main car dhundhne, price batane ya photo bhejne mein help kar sakta hoon. Aapko kaisi gaadi chahiye?",
        "marathi": "नमस्कार! Assad Motors मध्ये आपले स्वागत आहे. मी गाडी शोधण्यात, किंमत सांगण्यात किंवा फोटो पाठवण्यात मदत करू शकतो. तुम्हाला कशी गाडी हवी आहे?",
    },
    "media_clarify": {
        "english": "Sure! Which car would you like photos or videos of? Just tell me the model name and I'll send them right over.",
        "hindi": "ज़रूर! किस गाड़ी की फोटो या वीडियो चाहिए? मॉडल का नाम बताएं, मैं तुरंत भेजता हूँ।",
        "hinglish": "Bilkul! Kis gaadi ki photo ya video chahiye? Model ka naam batao, main turant bhej deta hoon.",
        "marathi": "नक्कीच! कोणत्या गाडीचे फोटो किंवा व्हिडिओ हवे आहेत? मॉडेलचे नाव सांगा, मी लगेच पाठवतो.",
    },
    "comparison": {
        "english": "Happy to compare! Tell me the two models you're considering (or your budget and fuel preference) and I'll help you pick the better option.",
        "hindi": "तुलना ज़रूर कर देंगे! जिन दो मॉडलों के बारे में सोच रहे हैं वो बताएं (या बजट और फ्यूल पसंद बताएं), मैं बेहतर विकल्प चुनने में मदद करूंगा।",
        "hinglish": "Compare kar dete hain! Jo do models soch rahe ho wo batao (ya budget aur fuel preference batao), main best option choose karne mein help karunga.",
        "marathi": "नक्की तुलना करूया! तुम्ही विचार करत असलेली दोन मॉडेल्स सांगा (किंवा बजेट आणि इंधन पसंती सांगा), मी चांगला पर्याय निवडण्यास मदत करेन.",
    },
}

# Fallback for queries we cannot resolve deterministically (mark_for_future_llm).
UNKNOWN_RESPONSE: Dict[str, str] = {
    "english": "I want to help you correctly — could you tell me the car model or your budget? You're always welcome to visit us at {area} too.",
    "hindi": "मैं आपकी सही मदद करना चाहता हूँ — कृपया गाड़ी का मॉडल या अपना बजट बता दें। आप {area} भी आ सकते हैं।",
    "hinglish": "Main aapki sahi madad karna chahta hoon — gaadi ka model ya budget bata do. Aap {area} bhi aa sakte ho.",
    "marathi": "मला तुमची योग्य मदत करायची आहे — कृपया गाडीचे मॉडेल किंवा बजेट सांगा. तुम्ही {area} पण येऊ शकता.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────
def _fill(text: str) -> str:
    return (text
            .replace("{address}", DEALERSHIP["address"])
            .replace("{area}", DEALERSHIP["area"])
            .replace("{maps_url}", DEALERSHIP["maps_url"]))


def render(template_key: str, language: Optional[str]) -> str:
    lang = language if language in LANGUAGES else DEFAULT_LANGUAGE
    bucket = FAQ_TEMPLATES.get(template_key)
    if not bucket:
        return _fill(UNKNOWN_RESPONSE.get(lang, UNKNOWN_RESPONSE[DEFAULT_LANGUAGE]))
    text = bucket.get(lang) or bucket[DEFAULT_LANGUAGE]
    return _fill(text)


def render_unknown(language: Optional[str]) -> str:
    lang = language if language in LANGUAGES else DEFAULT_LANGUAGE
    return _fill(UNKNOWN_RESPONSE.get(lang, UNKNOWN_RESPONSE[DEFAULT_LANGUAGE]))
