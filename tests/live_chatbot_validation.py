"""
Live chatbot validation harness (data-driven, reusable).
Reads the CURRENT inventory Excel, auto-generates questions from real vehicles/
values, runs them through the REAL ChatService, grades each answer against the
Excel (field label + value = wrong-column protection), and writes reports.

Isolated: loads a COPY of the Excel + writes DBs to a temp dir. Production untouched.
Usage: python -X utf8 harness.py [--dry N] [--max 750] [--out DIR] [--xlsx PATH]
"""
import os, sys, json, csv, random, argparse, hashlib, datetime, re
from collections import Counter, defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--dry", type=int, default=0)
ap.add_argument("--max", type=int, default=750)
ap.add_argument("--out", default=None)
ap.add_argument("--xlsx", default=None)
ap.add_argument("--seed", type=int, default=20260816)
A = ap.parse_args()
random.seed(A.seed)

import tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))          # <repo>/tests
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "app", "inventory_system")
# Isolation: copy the LIVE Excel into a throwaway workdir and point all DBs there,
# so production inventory / logs are never touched. Override the source with --xlsx.
LIVE_XLSX = A.xlsx or os.path.join(REPO, "app", "IVR_Sheet.xlsx")
WORK = tempfile.mkdtemp(prefix="chatval_")
DATA = os.path.join(WORK, "data"); os.makedirs(DATA, exist_ok=True)
XLSX = os.path.join(WORK, "IVR_Sheet.xlsx"); shutil.copy2(LIVE_XLSX, XLSX)
os.environ["CHAT_DATA_DIR"] = DATA
os.environ["CHAT_XLSX"] = XLSX
sys.path.insert(0, APP); os.chdir(APP)
import inventory_loader as L
from chat_service import ChatService

items = [i for i in L.load_inventory(XLSX) if i.is_customer_facing]
svc = ChatService(XLSX, leads_db=os.path.join(DATA, "l.db"),
                  analytics_db=os.path.join(DATA, "a.db"), unknown_db=os.path.join(DATA, "u.db"))

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f: h.update(f.read())
    return h.hexdigest()

# ── helpers ──
def has(v): return v not in (None, "", "UNKNOWN")
def lc(s): return str(s).lower()

def price_tokens(v): return [f"{v:g}", f"{v:.2f}"]
def km_tokens(v): return [f"{int(v):,}", str(int(v))]

# field registry: key -> spec
# grade types: 'basic' (value token + optional ctx), 'spec' (label kw + value token)
FIELDS = {
 "price":   dict(col="RATE", attr="price_lakh", kind="basic", ctx=["lakh","₹"], tok=price_tokens,
                 q=["{reg} ka price kya hai?","price of {reg}?","{reg} kitne ka hai?"]),
 "fuel":    dict(col="FUEL", attr="fuel_norm", kind="basic", ctx=[], tok=lambda v:[lc(v)],
                 q=["{reg} me kaunsa fuel hai?","what fuel does {reg} have?","{reg} petrol hai ya diesel?"]),
 "transmission": dict(col="TRANSMISSION", attr="transmission_norm", kind="basic", ctx=[], tok=lambda v:[lc(v)],
                 q=["{reg} automatic hai ya manual?","transmission of {reg}?","{reg} manual ya automatic?"]),
 "year":    dict(col="YEAR", attr="year_int", kind="basic", ctx=[], tok=lambda v:[str(v)],
                 q=["{reg} kis saal ki hai?","what year is {reg}?","{reg} model year?"]),
 "color":   dict(col="COLOR", attr="color_norm", kind="basic", ctx=[], tok=lambda v:[lc(v)],
                 q=["{reg} ka colour kya hai?","colour of {reg}?","{reg} kis rang ki hai?"]),
 "owners":  dict(col="OWNERSHIP", attr="ownership_count", kind="basic", ctx=[], tok=lambda v:[f"{v} owner"],
                 q=["{reg} kitne owner hain?","how many owners for {reg}?","{reg} ownership kitni hai?"]),
 "km":      dict(col="KM", attr="km_driven", kind="basic", ctx=["km"], tok=km_tokens,
                 q=["{reg} kitne km chali hai?","km of {reg}?","{reg} ka odometer kitna hai?"]),
 "seats":   dict(col="SEATS", attr="seats", kind="basic", ctx=["seat"], tok=lambda v:[f"{int(v)} seat"],
                 q=["{reg} me kitni seats hai?","how many seats in {reg}?","{reg} kitne seater hai?"]),
 "engine":  dict(col="Engine CC", attr="engine_cc", kw=["engine"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ka engine kitna cc hai?","engine cc of {reg}?"]),
 "airbags": dict(col="Airbags", attr="airbags", kw=["airbag"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} me kitne airbags hain?","airbags in {reg}?","{reg} me kitne airbag hai?"]),
 "boot":    dict(col="Boot Space", attr="boot_litres", kw=["boot"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ka boot space kitna hai?","boot space of {reg}?","{reg} ki dickey kitni badi hai?"]),
 "ground_clearance": dict(col="Ground Clearance", attr="ground_clearance_mm", kw=["ground clearance","clearance"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ka ground clearance kitna hai?","ground clearance of {reg}?"]),
 "mileage": dict(col="Mileage (ARAI)", attr="mileage_arai_kmpl", kw=["mileage"], kind="spec", tok=lambda v:[f"{v:.1f}", f"{v:g}"],
                 q=["{reg} ka mileage kitna hai?","{reg} kitna average deti hai?"]),
 "fuel_tank": dict(col="Fuel Tank", attr="fuel_tank_l", kw=["fuel tank","tank"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ka fuel tank kitna hai?","fuel tank capacity of {reg}?"]),
 "drivetrain": dict(col="Drivetrain", attr="drivetrain", kw=["drive"], kind="spec", tok=lambda v:[lc(v)],
                 q=["{reg} ka drivetrain kya hai?","{reg} fwd hai ya awd?"]),
 "abs_ebd": dict(col="ABS/EBD", attr="abs_ebd", kw=["abs"], kind="bool",
                 q=["{reg} me abs hai kya?","does {reg} have abs?","{reg} me abs ebd hai?"]),
 "length":  dict(col="Length", attr="length_mm", kw=["length"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ki length kitni hai?"]),
 "width":   dict(col="Width", attr="width_mm", kw=["width"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ki width kitni hai?"]),
 "height":  dict(col="Height", attr="height_mm", kw=["height"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ki height kitni hai?"]),
 "wheelbase": dict(col="Wheelbase", attr="wheelbase_mm", kw=["wheelbase"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ka wheelbase kitna hai?"]),
 "ncap":    dict(col="NCAP Rating", attr="ncap_rating", kw=["ncap"], kind="spec", tok=lambda v:[str(int(v))],
                 q=["{reg} ki ncap rating kya hai?","ncap rating of {reg}?","{reg} kitni safe hai ncap?"]),
 "sunroof": dict(col="Sunroof", attr="sunroof_type", kw=["sunroof"], kind="spec", tok=lambda v:[lc(v),"haan"],
                 q=["{reg} me sunroof hai?","does {reg} have a sunroof?"]),
 "ac_type": dict(col="AC Type", attr="ac_type", kw=["ac"], kind="spec", tok=lambda v:[lc(v)],
                 q=["{reg} ka ac type kya hai?","{reg} me climate control hai?"]),
 "headlamp": dict(col="Headlamp", attr="headlamp_type", kw=["headlamp","headlight"], kind="spec", tok=lambda v:[lc(v)],
                 q=["{reg} me kaunsi headlight hai?","headlamp type of {reg}?"]),
 "wheels":  dict(col="Wheel Type", attr="wheel_type", kw=["wheel"], kind="spec", tok=lambda v:[lc(v)],
                 q=["{reg} me alloy wheels hai?"]),
 "rear_ac": dict(col="Rear AC Vents", attr="rear_ac_vents", kw=["rear ac"], kind="bool",
                 q=["{reg} me rear ac vents hai?","does {reg} have rear ac vents?"]),
 "camera":  dict(col="Camera", attr="camera_type", kw=["camera"], kind="spec", tok=lambda v:[lc(v),"haan"],
                 q=["{reg} me camera hai?","does {reg} have a reverse camera?","{reg} me reverse camera hai?"]),
 "parking_sensors": dict(col="Parking Sensors", attr="parking_sensors", kw=["parking"], kind="bool",
                 q=["{reg} me parking sensors hai?","parking sensors in {reg}?"]),
}

MISS = ["data not available", "confirm", "visit pe", "abhi available", "bata nahi", "not available", "nahi hai"]

def grade(spec, item, r):
    """Return (passed:bool, note:str). Uses answer text + structured result."""
    a = lc(r.response or "")
    attr = spec["attr"]; val = getattr(item, attr, None)
    if not has(val):
        ok = any(m in a for m in MISS)
        return ok, ("missing-ok" if ok else "expected missing-data, got value/none")
    kind = spec["kind"]
    if kind == "bool":
        want = ["haan", "yes"] if val else ["nahi", "no", "not available"]
        label_ok = any(k in a for k in spec.get("kw", []))
        val_ok = any(w in a for w in want)
        return (label_ok and val_ok), f"label={label_ok} val={val_ok}"
    toks = spec["tok"](val)
    val_ok = any(lc(t) in a for t in toks)
    if kind == "spec":
        label_ok = any(k in a for k in spec.get("kw", []))
        return (label_ok and val_ok), f"col={label_ok} val={val_ok} toks={toks}"
    else:  # basic
        ctx = spec.get("ctx", [])
        ctx_ok = (not ctx) or any(c in a for c in ctx)
        return (val_ok and ctx_ok), f"val={val_ok} ctx={ctx_ok} toks={toks}"

# ── inventory intel ──
models = Counter(i.model for i in items if i.model)
DUP = [m for m, c in models.items() if c > 1]
SINGLE = [m for m, c in models.items() if c == 1]
by_model = defaultdict(list)
for i in items: by_model[i.model].append(i)
last4 = Counter(i.reg_last4 for i in items if i.reg_last4)
UNIQ4 = {i.reg_last4: i for i in items if last4[i.reg_last4] == 1}

tests = []
_tid = [0]
def add(cat, q, lang, item, field, col, expval, check, **extra):
    _tid[0] += 1
    tests.append(dict(id=f"TEST-{_tid[0]:04d}", category=cat, question=q, language=lang,
                      expected_vehicle=(item.registration_no if item else None),
                      expected_field=field, expected_excel_column=col,
                      expected_value=("" if expval is None else str(expval)),
                      _check=check, **extra))

def lang_of(q):
    return "english" if re.search(r'[a-z]', q) and not re.search(r'(hai|kya|kitn|ka |ki |me |kaun|batao|chali|rang|saal)', q) else "hinglish"

# 1) REG + FIELD (the backbone) — every field, many vehicles across value ranges
FIELD_ORDER = list(FIELDS.keys())
per_field_cap = 14
for fkey in FIELD_ORDER:
    spec = FIELDS[fkey]
    havers = [i for i in items if has(getattr(i, spec["attr"], None))]
    random.shuffle(havers)
    picks = havers[:per_field_cap]
    for it in picks:
        tmpl = random.choice(spec["q"])
        q = tmpl.format(reg=it.registration_no)
        val = getattr(it, spec["attr"], None)
        cat = "Specifications" if spec["kind"] in ("spec", "bool") else ("Price" if fkey=="price" else "KM" if fkey=="km" else "Fuel" if fkey=="fuel" else "Transmission" if fkey=="transmission" else "Registration" if fkey in ("year","color","owners","seats") else "Basic")
        add(cat if cat!="Basic" else "Basic fields", q, lang_of(q), it, fkey, spec["col"], val,
            (lambda s=spec, i=it: (lambda r: grade(s, i, r))), subtype="reg+field")

# 2) MISSING DATA — vehicles lacking a field
for fkey in FIELD_ORDER:
    spec = FIELDS[fkey]
    missers = [i for i in items if not has(getattr(i, spec["attr"], None))]
    random.shuffle(missers)
    for it in missers[:3]:
        tmpl = random.choice(spec["q"]); q = tmpl.format(reg=it.registration_no)
        add("Missing data", q, lang_of(q), it, fkey, spec["col"], "MISSING",
            (lambda s=spec, i=it: (lambda r: grade(s, i, r))), subtype="missing")

# 3) LAST-4 unique — clean 4-digit, non-year-like values (avoid year confusion)
UNIQ4_clean = {k: v for k, v in UNIQ4.items()
               if str(k).isdigit() and len(str(k)) == 4 and not (1985 <= int(k) <= 2027)}
for reg4, it in list(UNIQ4_clean.items())[:40]:
    fkey = random.choice(["price","fuel","km","year","color"])
    spec = FIELDS[fkey]
    if not has(getattr(it, spec["attr"], None)): continue
    label = {'price':'price','fuel':'fuel','km':'km','year':'year','color':'colour'}[fkey]
    q = f"{reg4} number wali gaadi ka {label} batao?"
    add("Registration", q, "hinglish", it, fkey, spec["col"], getattr(it, spec["attr"]),
        (lambda s=spec, i=it: (lambda r: grade(s, i, r))), subtype="last4")

# 4) SINGLE-instance model + field (direct answer expected)
for m in SINGLE[:26]:
    it = by_model[m][0]
    fkey = random.choice(["price","fuel","year"])
    spec = FIELDS[fkey]
    q = {"price": f"{m} ka price kya hai?", "fuel": f"{m} kaunse fuel me aati hai?",
         "year": f"{m} kis saal ki hai?"}[fkey]
    add("Single-instance models", q, "hinglish", it, fkey, spec["col"], getattr(it, spec["attr"]),
        (lambda s=spec, i=it: (lambda r: grade(s, i, r))), subtype="single-model")

# 4b) MODEL availability — ask distinct models by name (surfaces recognition coverage)
def model_avail_check(model):
    def f(r):
        a = lc(r.response or ""); st = getattr(r, "status", ""); c = getattr(r, "count", 0) or 0
        ok = st in ("found", "multi") or c >= 1 or (lc(model) in a and "available" in a)
        return ok, f"status={st} count={c}"
    return f
_allmodels = list(models.keys()); random.shuffle(_allmodels)
for m in _allmodels[:52]:
    add("Model", f"{m} hai kya?", "hinglish", by_model[m][0], "availability", "MODEL",
        f"{models[m]} in stock", (lambda mm=m: model_avail_check(mm)), subtype="model-availability")

# 5) DUPLICATE model -> expect clarify/multi (not silent pick)
def dup_check(r):
    a = lc(r.response or "")
    multi = (getattr(r, "count", 0) or 0) > 1 or getattr(r, "status", "") in ("multi", "clarify")
    signal = any(s in a for s in ["options hain", "konsi", "kaunsi", "kis gaadi", "kaun si"])
    return (multi or signal), f"status={getattr(r,'status','')} count={getattr(r,'count',0)}"
for m in DUP[:34]:
    q = f"{m} ka price kya hai?"
    add("Duplicate models", q, "hinglish", None, "clarify", "-", f"{models[m]} vehicles",
        (lambda: dup_check), subtype="dup-model")

# 6) UNAVAILABLE models
ABSENT = ["Lamborghini Aventador","Ferrari 488","Rolls Royce Phantom","Tesla Model 3","Bugatti Chiron",
          "Maserati Ghibli","Bentley Continental","McLaren 720S","Porsche Cayenne","Aston Martin",
          "Hummer H2","Jeep Wrangler","Lexus LX","Volvo XC90","Mini Cooper","Datsun Go","Force Gurkha",
          "Isuzu D-Max","Nissan GT-R","Cadillac Escalade"]
present_words = set()
for _m in models: present_words |= set(lc(_m).split())
for _mk in set(lc(i.make_full or i.make) for i in items if (i.make_full or i.make)): present_words |= set(_mk.split())
def unavail_check(name):
    def f(r):
        a = lc(r.response or "")
        # PASS if it does not present that exact model as available
        claimed = (lc(name) in a and ("available hai" in a or "available h" in a))
        honest = any(s in a for s in ["available nahi","nahi lagti","abhi available nahi","similar","koi aur","nahi hai","not available"]) or (getattr(r,"count",0)==0) or getattr(r,"status","") in ("not_found","unknown","off_sheet")
        return (not claimed) and (honest or getattr(r,"count",0)==0 or getattr(r,"status","") not in ("found",)), f"status={getattr(r,'status','')} claimed={claimed}"
    return f
for name in [n for n in ABSENT if not (set(lc(n).split()) & present_words)][:18]:
    add("Unavailable models", f"{name} hai kya?", "hinglish", None, "availability", "-", "NOT AVAILABLE",
        (lambda n=name: unavail_check(n)), subtype="unavailable")

# 7) MULTI-FIELD (price + km / fuel + transmission etc.)
multi_cars = [i for i in items if has(i.price_lakh) and has(i.km_driven)]
for it in multi_cars[:18]:
    q = f"{it.registration_no} ka price aur km dono batao?"
    def mk(i):
        def f(r):
            a=lc(r.response or "")
            p=any(t in a for t in price_tokens(i.price_lakh)); k=any(t in a for t in km_tokens(i.km_driven))
            return (p and k), f"price={p} km={k}"
        return f
    add("Multi-intent", q, "hinglish", it, "price+km", "RATE+KM", f"{it.price_lakh}L / {it.km_driven}km",
        (lambda i=it: mk(i)), subtype="multi-field")
ft_cars=[i for i in items if has(i.fuel_norm) and has(i.transmission_norm)]
for it in ft_cars[:16]:
    q=f"{it.registration_no} ka fuel aur transmission batao?"
    def mk2(i):
        def f(r):
            a=lc(r.response or ""); return (lc(i.fuel_norm) in a and lc(i.transmission_norm) in a), "fuel+trans"
        return f
    add("Multi-intent", q, "hinglish", it, "fuel+transmission", "FUEL+TRANSMISSION", f"{it.fuel_norm}/{it.transmission_norm}",
        (lambda i=it: mk2(i)), subtype="multi-field")

# 8) FILTERS / recommendations (fuel/transmission/color/body) — verify shown cards satisfy
def filter_check(pred_desc, fuel=None, trans=None, color=None):
    def f(r):
        cnt=getattr(r,"count",0) or 0; st=getattr(r,"status","")
        if cnt>0 and st not in ("not_found","unknown"): return True, f"count={cnt}"
        if st=="clarify": return True, "clarify-ok"     # asking to narrow an ambiguous filter is fine
        return False, f"no results status={st}"
    return f
fuels = [f for f in Counter(i.fuel_norm for i in items if has(i.fuel_norm))]
for fu in [f for f in fuels if "+" not in f]:           # single fuels only
    for tr in ["automatic","manual"]:
        add("Recommendation", f"{tr} {fu.lower()} cars dikhao", "hinglish", None, "filter", "-", f"{fu}+{tr}",
            (lambda fu=fu,tr=tr: filter_check(f"{fu}+{tr}", fuel=fu, trans=tr)), subtype="filter")
for bt in [b for b in Counter(i.body_type for i in items if has(i.body_type))][:6]:
    add("Recommendation", f"{bt.lower()} cars under 10 lakh batao", "hinglish", None, "filter", "-", bt,
        (lambda: filter_check("body+budget")), subtype="filter")
for col in [c for c in Counter(i.color_norm for i in items if has(i.color_norm))][:6]:
    add("Recommendation", f"{col.lower()} colour ki car dikhao", "hinglish", None, "filter", "-", col,
        (lambda: filter_check("color")), subtype="filter")

# 9) COMPARISON (two single-instance models -> both mentioned)
comp_models = SINGLE[:20]
for j in range(0, min(len(comp_models)-1, 24), 1):
    m1, m2 = comp_models[j], comp_models[(j+1) % len(comp_models)]
    if m1==m2: continue
    q=f"{m1} aur {m2} me kaunsi behtar hai?"
    def mkc(a1,b1):
        def f(r):
            a=lc(r.response or ""); return (lc(a1) in a or lc(b1) in a), "mention"
        return f
    add("Comparison", q, "hinglish", None, "compare", "-", f"{m1} vs {m2}", (lambda a1=m1,b1=m2: mkc(a1,b1)), subtype="comparison")

# 10) INTENT COLLISION — ask non-price field on a specific car, ensure NOT answered as price
def collide_check(spec, item, forbidden_price):
    def f(r):
        a=lc(r.response or "")
        val=getattr(item, spec["attr"], None)
        toks=spec["tok"](val) if has(val) and spec["kind"]!="bool" else []
        got_field = any(lc(t) in a for t in toks) or (spec["kind"]=="bool" and any(k in a for k in spec.get("kw",[])))
        # must NOT be a bare price answer when we asked e.g. engine/owner/color
        price_only = any(t in a for t in price_tokens(item.price_lakh)) and ("lakh" in a) and not got_field if has(item.price_lakh) else False
        return (got_field and not price_only), f"field={got_field} price_only={price_only}"
    return f
for fkey in ["engine","owners","color","airbags","seats","mileage"]:
    spec=FIELDS[fkey]; havers=[i for i in items if has(getattr(i,spec["attr"],None))]; random.shuffle(havers)
    for it in havers[:5]:
        q=spec["q"][0].format(reg=it.registration_no)
        add("Intent collision", q, lang_of(q), it, fkey, spec["col"], getattr(it,spec["attr"]),
            (lambda s=spec,i=it: collide_check(s,i,True)), subtype="collision")

# 11) MEDIA (no media in this inventory -> expect honest, no fabricated url)
media_cars = random.sample(items, 16)
def media_check(r):
    a=lc(r.response or "")
    fake=bool(re.search(r'https?://', a))
    return (not fake), f"has_url={fake}"
for it in media_cars:
    q=random.choice([f"{it.registration_no} ki photo hai kya?", f"{it.registration_no} ka video available hai?"])
    add("Media", q, "hinglish", it, "media", "-", "no fabricated url", (lambda: media_check), subtype="media")

# 12) MULTILINGUAL (English + Hindi phrasing of value questions)
hindi_tmpl = {"price":"{reg} की कीमत क्या है?","fuel":"{reg} में कौन सा ईंधन है?","km":"{reg} कितने किलोमीटर चली है?",
              "year":"{reg} किस साल की है?","color":"{reg} का रंग क्या है?","seats":"{reg} में कितनी सीटें हैं?"}
for fkey, tmpl in hindi_tmpl.items():
    spec=FIELDS[fkey]; havers=[i for i in items if has(getattr(i,spec["attr"],None))]; random.shuffle(havers)
    for it in havers[:8]:
        add("Multilingual", tmpl.format(reg=it.registration_no), "hindi", it, fkey, spec["col"], getattr(it,spec["attr"]),
            (lambda s=spec,i=it: (lambda r: grade(s,i,r))), subtype="hindi")
# English phrasing
for fkey in ["price","fuel","km","transmission","engine","airbags"]:
    spec=FIELDS[fkey]; havers=[i for i in items if has(getattr(i,spec["attr"],None))]; random.shuffle(havers)
    for it in havers[:8]:
        q={"price":f"what is the price of {it.registration_no}?","fuel":f"what fuel does {it.registration_no} use?",
           "km":f"how many kilometers has {it.registration_no} run?","transmission":f"is {it.registration_no} automatic or manual?",
           "engine":f"what is the engine cc of {it.registration_no}?","airbags":f"how many airbags does {it.registration_no} have?"}[fkey]
        add("Multilingual", q, "english", it, fkey, spec["col"], getattr(it,spec["attr"]),
            (lambda s=spec,i=it: (lambda r: grade(s,i,r))), subtype="english")

# 13) FOLLOW-UP / context (pin a car via reg, then ask fields without reg)
followup_cars = [i for i in items if has(i.price_lakh) and has(i.fuel_norm)][:20]
for it in followup_cars:
    sid=f"fu-{it.registration_no}"
    # turn 1 pins the car
    add("Follow-up", f"{it.registration_no} dikhao", "hinglish", it, "pin", "-", it.model,
        (lambda: (lambda r: (getattr(r,'count',0)>=1 or 'available' in lc(r.response or ''), 'pin'))), session=sid, order=1, subtype="followup-pin")
    add("Follow-up", "iska price kya hai?", "hinglish", it, "price", "RATE", it.price_lakh,
        (lambda s=FIELDS["price"], i=it: (lambda r: grade(s,i,r))), session=sid, order=2, subtype="followup")
    add("Follow-up", "aur fuel kya hai?", "hinglish", it, "fuel", "FUEL", it.fuel_norm,
        (lambda s=FIELDS["fuel"], i=it: (lambda r: grade(s,i,r))), session=sid, order=3, subtype="followup")

# ── dedup by (question, session) ──
seen=set(); uniq=[]
for t in tests:
    key=(t["question"], t.get("session"))
    if key in seen: continue
    seen.add(key); uniq.append(t)
tests=uniq[:A.max]

print(f"generated {len(tests)} unique tests (cap {A.max})")
if A.dry:
    tests = tests[:A.dry]

# ── execute (respect session ordering for follow-ups) ──
ts_now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
def run_one(t):
    r = svc.handle(t["question"], session_id=t.get("session"))
    chk = t["_check"]()
    passed, note = chk(r)
    return r, passed, note

# order: keep follow-up chains contiguous & ordered
tests.sort(key=lambda t: (t.get("session") or "", t.get("order", 0)))
results=[]
for t in tests:
    try:
        r, passed, note = run_one(t)
        rec = {k:v for k,v in t.items() if not k.startswith("_")}
        rec.update(actual_answer=(r.response or "").replace("\n"," "),
                   detected_intent=r.intent, status=getattr(r,"status",""), match_count=getattr(r,"count",0),
                   passed=bool(passed), failure_reason=("" if passed else note), timestamp=ts_now)
        results.append(rec)
    except Exception as e:
        rec = {k:v for k,v in t.items() if not k.startswith("_")}
        rec.update(actual_answer="", detected_intent="ERROR", passed=False, failure_reason=f"exception: {e}", timestamp=ts_now)
        results.append(rec)

# ── write reports ──
OUT = A.out or os.path.join(REPO, "tests", "reports")
os.makedirs(OUT, exist_ok=True)
jsonl=os.path.join(OUT,"live_chatbot_validation.jsonl")
csvp=os.path.join(OUT,"live_chatbot_validation.csv")
mdp=os.path.join(OUT,"live_chatbot_validation.md")
cols=["id","category","subtype","question","language","expected_vehicle","expected_field","expected_excel_column",
      "expected_value","actual_answer","detected_intent","status","match_count","passed","failure_reason","timestamp"]
with open(jsonl,"w",encoding="utf-8") as f:
    for r in results: f.write(json.dumps({k:r.get(k) for k in cols}, ensure_ascii=False)+"\n")
with open(csvp,"w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
    for r in results: w.writerow({k:r.get(k,"") for k in cols})

# summary
total=len(results); passed=sum(1 for r in results if r["passed"]); failed=total-passed
by_cat=defaultdict(lambda:[0,0])
for r in results:
    by_cat[r["category"]][0]+=1; by_cat[r["category"]][1]+= (1 if r["passed"] else 0)
# field coverage matrix
fieldcov=defaultdict(lambda:{"q":0,"pass":0,"pos":0,"miss":0})
for r in results:
    fk=r.get("expected_field")
    if fk in FIELDS:
        fc=fieldcov[fk]; fc["q"]+=1; fc["pass"]+= (1 if r["passed"] else 0)
        if r.get("subtype")=="missing": fc["miss"]+=1
        else: fc["pos"]+=1

with open(mdp,"w",encoding="utf-8") as f:
    f.write(f"# Live Chatbot Validation Report\n\n")
    f.write(f"- Inventory: `{os.path.basename(XLSX)}`  hash `{sha(XLSX)}`\n")
    f.write(f"- Cars: {len(items)}  Models: {len(models)}  Generated tests: {total}\n")
    f.write(f"- Timestamp: {ts_now}\n\n")
    f.write(f"## Totals\n\n**{passed}/{total} passed ({100*passed/total:.1f}%)** — {failed} failed\n\n")
    f.write("## By category\n\n| Category | Q | Pass | Fail | Rate |\n|---|---|---|---|---|\n")
    for c in sorted(by_cat):
        q,p=by_cat[c]; f.write(f"| {c} | {q} | {p} | {q-p} | {100*p/q:.0f}% |\n")
    f.write("\n## Field coverage matrix\n\n| Field | Excel column | Q | Positive | Missing | Pass | Status |\n|---|---|---|---|---|---|---|\n")
    for fk in FIELDS:
        fc=fieldcov.get(fk,{"q":0,"pass":0,"pos":0,"miss":0})
        col=FIELDS[fk]["col"]
        havers=sum(1 for i in items if has(getattr(i,FIELDS[fk]["attr"],None)))
        status="OK" if fc["q"] and fc["pass"]==fc["q"] else ("NO POPULATED DATA" if havers==0 else "REVIEW" if fc["q"] else "not tested")
        f.write(f"| {fk} | {col} | {fc['q']} | {fc['pos']} | {fc['miss']} | {fc['pass']} | {status} |\n")
    f.write("\n## Failures\n\n")
    fails=[r for r in results if not r["passed"]]
    for r in fails[:200]:
        f.write(f"- `{r['id']}` [{r['category']}/{r.get('subtype')}] {r['question']} | exp {r['expected_field']}={r['expected_value']} | {r['failure_reason']} | ans: {r['actual_answer'][:120]}\n")

print(f"\nTOTAL {passed}/{total} passed ({100*passed/total:.1f}%)  failed={failed}")
print("by category:")
for c in sorted(by_cat):
    q,p=by_cat[c]; print(f"  {c:24} {p}/{q} ({100*p/q:.0f}%)")
print(f"\nreports: {jsonl}\n         {csvp}\n         {mdp}")
print("XLSX hash after:", sha(XLSX))
