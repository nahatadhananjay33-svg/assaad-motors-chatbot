# Phase 11A — Inventory-Field Intent Dictionary

A complete, deterministic phrase → field mapping for every customer-relevant
inventory field, across **English / Hindi / Hinglish / Marathi**, including short
forms, long forms, spoken variants, question forms and common spelling mistakes.

**No LLM.** Matching is normalization → tokenization → synonym/alias lookup with
word-boundary regex (`_has`), keyword scoring and field-alias mapping. The living,
executable form of this dictionary is `app/inventory_system/phase11a_intent_tests.py`
(1,982 generated utterances, 100 % resolved) and the vocabularies inside
`query_parser.py` / `media_lookup.py`.

Legend: `[F]` = filter/browse value (e.g. "white cars"); `[Q]` = attribute
question about the pinned car (e.g. "kaunsa rang?"). A value → filter; a bare
field-name question → attribute answer.

---

## RC / documents / transfer / fitness / NOC  → `rc_query`
Answers: rc_status, hypothecation_bank, loan_closed, noc_available, finance_eligible, rto.

- **EN:** rc, rc hai, rc status, rc clear, registration, registration certificate,
  rc transfer, transfer, name transfer, noc, fitness, fitness certificate, fc,
  fc valid, rto, rto clear, rto transfer, documents, document, docs, papers,
  paper, paperwork, original papers, papers complete, paper complete, papers ready,
  duplicate rc, hypothecation, loan closed, puc certificate, tax paid, road tax
- **Hinglish/broken:** rc h, rc kaisa, rc ka scene, rc kiske naam, rc asli,
  kagzat, kagaz, kaagaz, kagad, kaagad, sab kagzat, fc hua, rc kis ke naam
- **Marathi/Devanagari:** आरसी, आरसी आहे, रजिस्ट्रेशन, ट्रान्सफर, एनओसी, फिटनेस,
  फिटनेस प्रमाणपत्र, कागदपत्र, कागदपत्रे पूर्ण, आरटीओ, rc आहे, fc झाली, कुणाच्या नावाने

## Insurance  → `insurance_query`
Answers: insurance_type, insurance_expiry, zero_dep, insurance_claim_history.

- **EN:** insurance, insured, policy, policy valid, policy details, cover note,
  cover valid, insurance cover, claim, claims, claim hua, no claim, no claim bonus,
  ncb
- **Hinglish:** bima, beema, insurance kitni, insurance kab tak
- **Marathi/Devanagari:** विमा, विम्याचे, विम्याची, पॉलिसी, क्लेम, विमा दावा
- **Inventory-wide filter** ("insurance kis kis ka hai", "insurance wali gaadi",
  "विमा असलेल्या गाड्या") → `has_insurance` availability filter, not a per-car answer.

## Ownership  → `ownership_query`
Answers: ownership_count.

- **EN:** owner, owners, number of owners, how many owners, first owner, single
  owner, second owner, previous owner, owner history, owner details, used by
- **Hinglish/broken:** kitne owner, kitne malik, malik, maalik, asli malik,
  ek malak, pahila malak, kiti malak, malak kon, company car, teksi thi
- **Marathi/Devanagari:** मालक, किती मालक, एकच मालक, एकाच हाताची, आधीचा मालक,
  किती जणांनी वापरली, मालक इतिहास

## KM / odometer  → `km_reading_query`
Answers: km_driven.

- **EN:** km, kms, kilometer, kilometre, kilometers, kilometres, running, odo,
  odometer, odo reading, km reading, odometer reading, distance, distance covered,
  km driven, kms driven, how many km, how much km
- **Hinglish/broken:** kitne km, km kitne, kitni chali, kiti chali, km chali,
  kitni chalali, kitna chala, kitna chali, kitni running, running kitni
- **Marathi/Devanagari:** किती चालली, किती किलोमीटर, किती वापरली, कितनी चली,
  किलोमीटर, किमी, कितने किलोमीटर, रनिंग
- **Note:** *low-km / less-driven* ("kam km", "least driven", "कमी चाललेली") is a
  km-ascending **browse** (`sort_low_km`), not a single-car odometer answer.

## Condition / accident  → `condition_query`
Answers: accident_free, flood_damage, repainted, body/engine/interior/tyre condition.

- **EN:** condition, accident, accidental, accident history, accident free, damage,
  damaged, scratch, dent, rust, paint, repaint, repainted, touch up, touchup,
  denting, denting painting, body work, panel, putty, crash, repair, airbag,
  frame/chassis/structural, fire damage, tyre, glass, ac working
- **Hinglish/broken:** halat, halaat, hadsa, hadse, takkar, thokar, nuksaan,
  nuksan, marammat, pani mein dooba, aag lagi, koi hadsa
- **Marathi/Devanagari:** स्थिती, गंज, खरचटले, अपघात, नुकसान, धडक, पाण्यात बुडाली,
  आग लागली, अपघातमुक्त, चांगल्या स्थिती
- **Flood** sub-type ("flood", "water damage", "baarish mein", "waterlogged") →
  `flood_query` (condition).

## Colour  → `color` [F] / `color_query` [Q]
Answers: color_norm.

- **[F] values:** white/safed/pandhra, black/kaala/kaali, silver, grey/gray,
  blue/neela/navy/sky blue, red/laal, brown, gold, beige/cream/champagne,
  green/hara/hirwa, orange/narangi, maroon/wine, purple/violet, pearl white, …
- **[Q] questions:** color, colour, colar, coler, kalar, car color, gaadi ka color,
  color kya, colour kya, color kaunsa, which color, which colour, what color,
  kaunsa rang, kaun sa rang, konsa rang, rang kya, kya rang, rang kaunsa, rang;
  Devanagari: रंग, कलर, कोणता रंग, रंग कोणता, रंग काय

## Fuel  → `fuel` [F] / `fuel_query` [Q]
Answers: fuel_norm.

- **[F] values:** petrol/peterol/patrol, diesel/dijal/diseil, cng/gas/gas wali,
  hybrid/strong hybrid/self charging, electric/ev/battery wali, petrol+cng;
  Devanagari: डिझेल, पेट्रोल, सीएनजी, इलेक्ट्रिक
- **[Q] questions:** fuel, fuel type, kaunsa fuel, kaun sa fuel, konsa fuel,
  which fuel, what fuel, fuel kya, kya fuel, kis fuel, "petrol ya diesel",
  "diesel ya petrol"; Devanagari: इंधन, कोणते इंधन, फ्युएल
- **Excluded** (economy browse, not fuel question): fuel efficient/economy/average/
  mileage/kmpl.

## Transmission  → `transmission` [F] / `transmission_query` [Q]
Answers: transmission_norm.

- **[F] values:** automatic, auto, amt, cvt, dct, dsg, imt, clutchless, no clutch,
  manual, gear wali, stick, clutch wali; Devanagari: ऑटोमॅटिक, मॅन्युअल
- **[Q] questions:** transmission, gearbox, gear box, gear kaisa, gear kya,
  kaunsa gear, which transmission, gear type, gear system, "manual ya automatic",
  "automatic ya manual"; Devanagari: ट्रान्समिशन, गिअरबॉक्स, कोणते गिअर

## Seats  → `seats` [F] / `seats_query` [Q]
Answers: seats.

- **[F] values:** 5/6/7/8/9 seater, saat seater, paanch seater, 7 seat, 7 log
- **[Q] questions:** kitni seat, kitni seats, kitne seat, how many seats,
  seat kitni, seating capacity, kitni seating, kitne log baith, capacity kya;
  Devanagari: किती सीट, कितनी सीट, आसन क्षमता

## Price  → `price` intent  /  Budget  → `price_max` / `price_min` / `sort_cheapest`
Answers: price_lakh (quotable only; never fabricated).

- **Price question:** price, rate, cost, daam, bhav, kimat/kimmat/keemat/kemat,
  how much, kitne ka, kitne ki, kitne mein, kitna, kitna hai, kya daam;
  Devanagari: किंमत, दाम, भाव. Bare `Final?` → price follow-up on the pinned car.
- **Budget ceiling:** "under 5 lakh", "6 lakh ke andar", "N lakh tak", "below 8",
  "under 6", "upto 10 lakh", "8L", "50k", "X crore", "₹X"; Devanagari लाख/लाक forms.
  Bare "below N / under N" (N 1–40, no unit) → N lakh.
- **Cheapest sort:** sasti, sasta, cheapest, kam budget, sabse kam, lowest price.
- **Negotiation** ("last price", "best price", "final rate", "discount") stays a
  FAQ (`price_fixed`) — prices are fixed.

## Finance / EMI  → `downpayment_query` (+ finance FAQ)
Answers: 20% downpayment estimate on price; finance_eligible.

- **EN/Hinglish:** emi, downpayment, down payment, dp kitna, kist, kitni kist,
  installment, instalment, monthly installment, monthly kitna, monthly payment,
  emi kitni, emi option
- **Marathi/Devanagari:** हप्ता, किती हप्ता, मासिक हप्ता, डाउन पेमेंट, ईएमआई
- **General "finance available?/loan?"** → finance FAQ (2014+ eligible, nothing
  guaranteed).

## Warranty  → `warranty_detail_query`
Answers: warranty_available, warranty_expiry, warranty_provider, tyre/brake/clutch.

- **EN:** warranty, warranty period, any warranty, warranty card, warranty status,
  warranty available, warranty left, engine warranty, guarantee, gaurantee,
  guaranty, garanti, assurance
- **Hinglish:** warranty hai kya, warranty milegi, koi warranty, warranty kab tak
- **Marathi/Devanagari:** वॉरंटी, वारंटी, वॉरन्टी, गॅरंटी, हमी, वॉरंटी आहे

## Service history  → `service_query`
Answers: service_history_available, last_service_date, service_center_type.

- **EN:** service, service history, service record(s), serviced, last service,
  maintenance, maintenance history, regular service, dealer service, oil change,
  service due, service center/centre, service book
- **Hinglish/broken:** service kab, service kiya, servis histri, servis rekords
- **Marathi/Devanagari:** सर्व्हिस, सर्व्हिस इतिहास, नियमित सर्व्हिस, सर्विस

## Media — Photo / Video / Instagram / YouTube  (`media_lookup.detect_media_intent`)
Answers: InventoryMedia URLs (photo_count / video_count).

- **Photo:** photo, photos, pic, pics, picture, image, images, snaps, tasveer,
  foto; scope interior/exterior (andar/bahar); Devanagari फोटो, चित्र, तस्वीर
- **Video:** video, videos, walkaround, walk around, clip, clips, video bhejo,
  chalti gaadi; Devanagari व्हिडिओ, व्हिडीओ
- **Instagram:** instagram, insta, reel, reels, insta link, instagram reel,
  insta pe, ig video, story
- **YouTube:** youtube, you tube, yt video, yt link, youtube video, youtube link,
  **shorts, yt shorts, youtube shorts**
- Precedence: youtube > instagram > video > photo.

---

### Behaviour rules (STEP 5 / STEP 6)

* **Pinned vehicle + field question →** answer that car's field directly, no
  fabrication (empty column → "Data not available" / "visit pe confirm").
* **No vehicle pinned + attribute question →** a crisp "which car?" clarification
  (e.g. "Kis gaadi ka colour poochh rahe hain?") instead of a wrong default.
