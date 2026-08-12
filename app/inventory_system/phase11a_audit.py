"""
Phase 11A audit harness — grounds coverage in the REAL parser.
Run from app/inventory_system.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.getcwd())

import dataclasses
from inventory_models import InventoryItem
from query_parser import parse
from media_lookup import detect_media_intent

# ── STEP 1: auto-detect inventory fields from the schema (no hardcoding) ──
INTERNAL = {"id", "registration_no", "stock_no", "reg_last4", "raw", "as_of",
            "created_at", "updated_at", "media", "location_code", "location_type",
            "customer_viewable", "is_ivr_eligible", "is_placeholder", "source_sheet",
            "listing_status", "color_confidence", "make", "price_inr",
            "price_range_low", "price_range_high"}
fields = [f.name for f in dataclasses.fields(InventoryItem) if f.name not in INTERNAL]
print("=== STEP 1: customer-relevant inventory fields (auto-detected) ===")
print(f"total dataclass fields: {len(dataclasses.fields(InventoryItem))}, "
      f"customer-relevant: {len(fields)}")
for f in fields:
    print("  -", f)


def detected_field(msg):
    """What field intent the CURRENT system resolves for `msg` (mirrors how it answers)."""
    mi = detect_media_intent(msg)
    if mi:
        return {"photo_request": "photo", "video_request": "video",
                "instagram_request": "instagram", "youtube_request": "youtube"}[mi]
    q = parse(msg)
    if q.rc_query: return "rc"
    if q.insurance_query: return "insurance"
    if q.service_query: return "service"
    if q.warranty_detail_query: return "warranty"
    if q.ownership_query: return "ownership"
    if q.km_reading_query: return "km"
    if q.flood_query: return "condition"
    if q.condition_query: return "condition"
    if q.downpayment_query: return "finance"
    if q.off_sheet and q.off_sheet_topic == "finance": return "finance"
    if q.sort_low_km: return "low_km"
    if q.color_query: return "color"
    if q.fuel_query: return "fuel"
    if q.transmission_query: return "transmission"
    if q.seats_query: return "seats"
    if q.fuel: return "fuel"
    if q.transmission: return "transmission"
    if q.color: return "color"
    if q.seats is not None: return "seats"
    if q.category: return "category"
    if q.price_max is not None or q.price_min is not None or q.sort_cheapest: return "budget"
    if "price" in q.intents: return "price"
    return "availability(fallback)"


# ── STEP 3: audit the task's example phrases (expected -> phrase) ──
CASES = {
    "rc": ["RC", "RC hai?", "RC status", "RC ka kya scene hai", "Registration hai?",
           "rc clear hai kya", "rc kaisa hai", "gaadi ki rc", "rc transfer hoga"],
    "insurance": ["Insurance", "Insurance?", "Policy?", "Policy valid hai?", "Claim hua?",
                  "bima hai", "insurance kab tak", "no claim bonus", "insurance kitni"],
    "ownership": ["Owner", "Kitne owner?", "Single owner?", "First owner?",
                  "kitne malik", "second owner hai kya", "owner history"],
    "km": ["Running?", "Kitni chali?", "Kilometer?", "Odometer?", "KM?",
           "kitne km chali", "km reading", "kितनी चली", "odo kya hai", "kms?"],
    "condition": ["Accident?", "Accidental?", "Damage?", "Paint?", "Touch-up?",
                  "koi scratch", "dent hai kya", "condition kaisi hai", "repaint hua"],
    "video": ["Video bhejo", "Walkaround", "Show video", "video link", "video dikhao"],
    "instagram": ["Instagram", "Reel", "Insta link", "insta reel bhejo"],
    "youtube": ["YouTube", "Shorts", "yt link", "youtube video"],
    "color": ["Color?", "kaunsa rang", "which colour", "rang kya hai", "colour kya hai"],
    "fuel": ["Fuel?", "kaunsa fuel", "petrol hai ya diesel", "fuel type kya hai"],
    "transmission": ["Transmission?", "Automatic?", "Manual?", "AMT?", "CVT?",
                     "manual hai ya automatic", "gear kaisa hai"],
    "seats": ["7 seater?", "6 seater?", "5 seater?", "kitni seats", "how many seats"],
    "budget": ["Under 5 lakh", "6 lakh ke andar", "Below 8", "5 lakh tak"],
    "price": ["Kitna price?", "Final?", "Rate?", "Cost?", "price kya hai", "daam kya hai"],
    "finance": ["Finance?", "Loan?", "EMI?", "emi kitni", "kitni kist"],
    "warranty": ["Warranty?", "Guarantee?", "warranty hai kya", "warranty period"],
    "service": ["Service history?", "service hui kya", "kab service hui"],
    "rc_transfer": ["Transfer?", "NOC?", "rc transfer", "noc milega"],
    "fitness": ["Fitness?", "RTO?", "fitness certificate", "fc done"],
    "documents": ["Original papers?", "Paper complete?", "documents?", "kagzat"],
}

print("\n\n=== STEP 3: coverage audit ===")
overall_pass = overall_total = 0
by_field = {}
misses = []
for expected, phrases in CASES.items():
    # some categories map to an existing bucket
    accept = {expected}
    if expected in ("rc_transfer", "fitness", "documents"):
        accept = {"rc"}       # these bundle into rc/documents in current design
    p = t = 0
    for ph in phrases:
        got = detected_field(ph)
        ok = got in accept
        p += ok; t += 1
        if not ok:
            misses.append((expected, ph, got))
    by_field[expected] = (p, t)
    overall_pass += p; overall_total += t
    bar = "OK " if p == t else "GAP"
    print(f"[{bar}] {expected:12s} {p}/{t}")

print(f"\nOVERALL: {overall_pass}/{overall_total} "
      f"({100*overall_pass/overall_total:.0f}%)")
print("\n--- MISSES (expected | phrase | got) ---")
for exp, ph, got in misses:
    print(f"  {exp:12s} | {ph:28s} | {got}")
