"""
inventory_models.py
===================

Data models for the dedicated used-car inventory system (Phase 2A, Option C).

These models implement the approved schema in `final_inventory_architecture.md`
(§5.1 `inventory`, §5.2 `inventory_media`). They are intentionally
dependency-free (stdlib only) so the loader, sync, and tests can run anywhere.

Design notes
------------
* `InventoryItem` mirrors the `inventory` table one-to-one.
* `InventoryMedia` mirrors the `inventory_media` table (URLs only — binaries
  live in Supabase Storage, never in these models or in Excel).
* `registration_no` is the natural key. `id` is a *deterministic* UUIDv5 derived
  from `registration_no`, so re-syncing the same car always yields the same id
  (idempotent upserts).
* Enum-like values are plain strings (class constants) to keep records
  JSON/Supabase friendly and avoid serialization edge cases.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Stable namespace for deterministic ids derived from registration numbers.
# Fixed constant so the same registration always maps to the same UUID.
INVENTORY_NAMESPACE = uuid.UUID("6f3a1c2e-0000-4a00-9000-100000000000")


def deterministic_id(registration_no: str) -> str:
    """A stable UUIDv5 for a registration number (idempotent across syncs)."""
    return str(uuid.uuid5(INVENTORY_NAMESPACE, (registration_no or "").strip().upper()))


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp. Passed in by callers so tests can pin time."""
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Enum-like value sets (kept as strings for DB friendliness)
# ─────────────────────────────────────────────────────────────────────────────
class FuelType:
    PETROL = "Petrol"
    DIESEL = "Diesel"
    CNG = "CNG"
    PETROL_CNG = "Petrol+CNG"
    HYBRID = "Hybrid"
    ELECTRIC = "Electric"
    UNKNOWN = "Unknown"
    ALL = {PETROL, DIESEL, CNG, PETROL_CNG, HYBRID, ELECTRIC, UNKNOWN}


class Transmission:
    AUTOMATIC = "Automatic"
    MANUAL = "Manual"
    UNKNOWN = "Unknown"
    ALL = {AUTOMATIC, MANUAL, UNKNOWN}


class BodyType:
    HATCHBACK = "Hatchback"
    SEDAN = "Sedan"
    COMPACT_SUV = "Compact-SUV"
    SUV = "SUV"
    MUV = "MUV"
    LUXURY = "Luxury"
    UNKNOWN = "Unknown"
    ALL = {HATCHBACK, SEDAN, COMPACT_SUV, SUV, MUV, LUXURY, UNKNOWN}


class ListingStatus:
    AVAILABLE = "available"
    SOLD = "sold"
    ON_HOLD = "on_hold"
    INACTIVE = "inactive"
    ALL = {AVAILABLE, SOLD, ON_HOLD, INACTIVE}


class LocationType:
    SLOT = "slot"          # physical parking grid slot, e.g. Y5, L92
    CUSTODY = "custody"    # word code, e.g. POLI, IMM, ABR (off main lot)
    UNKNOWN = "unknown"
    ALL = {SLOT, CUSTODY, UNKNOWN}


class ColorConfidence:
    HIGH = "high"
    LOW = "low"            # ambiguous codes like GRE (Grey vs Green)
    ALL = {HIGH, LOW}


class MediaType:
    EXTERIOR_PHOTO = "exterior_photo"
    INTERIOR_PHOTO = "interior_photo"
    VIDEO = "video"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    ALL = {EXTERIOR_PHOTO, INTERIOR_PHOTO, VIDEO, INSTAGRAM, YOUTUBE}


# ─────────────────────────────────────────────────────────────────────────────
# inventory_media (URLs only — binaries live in Supabase Storage)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class InventoryMedia:
    registration_no: str
    media_type: str
    slot: int
    url: str
    storage_path: Optional[str] = None
    is_primary: bool = False
    sort_order: int = 0
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = str(
                uuid.uuid5(
                    INVENTORY_NAMESPACE,
                    f"{(self.registration_no or '').upper()}|{self.media_type}|{self.slot}",
                )
            )

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# inventory (the catalogue) — one row per registration
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class InventoryItem:
    # ── identity ──
    registration_no: str
    id: Optional[str] = None
    stock_no: Optional[int] = None
    reg_last4: Optional[str] = None

    # ── normalized descriptive ──
    make: Optional[str] = None
    make_full: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    year_int: Optional[int] = None
    fuel_norm: str = FuelType.UNKNOWN
    transmission_norm: str = Transmission.UNKNOWN
    ownership_count: Optional[int] = None
    km_driven: Optional[int] = None          # None == unknown (never 0-as-fact)
    color_norm: Optional[str] = None
    color_confidence: str = ColorConfidence.HIGH

    # ── price ──
    price_inr: Optional[int] = None          # None when not quotable
    price_lakh: Optional[float] = None
    price_quotable: bool = False

    # ── advisory / derived ──
    insurance_hint: Optional[str] = None     # advisory only; never asserted
    body_type: str = BodyType.UNKNOWN
    seats: Optional[int] = None

    # ── pricing extensions (Phase 7D) ──
    price_range_low: Optional[int] = None
    price_range_high: Optional[int] = None
    negotiable: Optional[bool] = None

    # ── usage ──
    claimed_mileage_kmpl: Optional[float] = None

    # ── insurance structured (Phase 7D) ──
    insurance_type: Optional[str] = None        # Comprehensive / Third-Party / Expired
    insurance_expiry: Optional[str] = None      # ISO date or raw string
    zero_dep: Optional[bool] = None
    insurance_claim_history: Optional[bool] = None

    # ── vehicle condition ──
    accident_free: Optional[bool] = None
    flood_damage: Optional[bool] = None
    repainted: Optional[bool] = None
    repaint_panels: Optional[str] = None
    body_condition: Optional[str] = None        # Excellent/Good/Fair/Poor
    engine_condition: Optional[str] = None
    interior_condition: Optional[str] = None
    tyre_condition: Optional[str] = None        # Good/Fair/Replace
    brake_condition: Optional[str] = None
    clutch_condition: Optional[str] = None      # Good/Fair/Replace/NA
    battery_condition: Optional[str] = None

    # ── service history ──
    service_history_available: Optional[bool] = None
    last_service_date: Optional[str] = None
    service_center_type: Optional[str] = None   # Authorised/Multi-brand/Local

    # ── documents ──
    rc_status: Optional[str] = None             # Clear/Hypothecated/Pending
    hypothecation_bank: Optional[str] = None
    loan_closed: Optional[bool] = None
    noc_available: Optional[bool] = None
    finance_eligible: Optional[bool] = None

    # ── warranty ──
    warranty_available: Optional[bool] = None
    warranty_expiry: Optional[str] = None
    warranty_provider: Optional[str] = None

    # ── sales intelligence ──
    reason_for_sale: Optional[str] = None
    best_features: Optional[str] = None
    known_issues: Optional[str] = None

    # ═════════════════════════════════════════════════════════════════════════
    # Phase 12B — Schema expansion (Phase 12A schema v2).
    # All Optional / default None → fully backward compatible. Fields split into:
    #   • STANDARD SPECS  — auto-fillable from model_specs (make/model/variant/year)
    #   • DEALERSHIP DATA — owner-entered per car (extra condition/docs/keys/EV)
    # None always renders as "Data not available" — never fabricated.
    # ═════════════════════════════════════════════════════════════════════════
    # ── engine (spec) ──
    engine_cc: Optional[int] = None
    power_bhp: Optional[float] = None
    torque_nm: Optional[float] = None
    aspiration: Optional[str] = None            # NA / Turbo / Supercharged
    # ── transmission detail (spec) ──
    transmission_subtype: Optional[str] = None  # AMT / CVT / DCT / iMT / TC
    gears: Optional[int] = None
    drivetrain: Optional[str] = None            # FWD / RWD / AWD / 4WD
    # ── fuel & economy (spec) ──
    cng_kit_type: Optional[str] = None          # Company / After-market / None
    mileage_arai_kmpl: Optional[float] = None
    fuel_tank_l: Optional[int] = None
    # ── dimensions (spec) ──
    length_mm: Optional[int] = None
    width_mm: Optional[int] = None
    height_mm: Optional[int] = None
    wheelbase_mm: Optional[int] = None
    boot_litres: Optional[int] = None
    ground_clearance_mm: Optional[int] = None
    # ── exterior & lights (spec) ──
    headlamp_type: Optional[str] = None         # LED / Projector / Halogen
    drl: Optional[bool] = None
    fog_lamps: Optional[bool] = None
    wheel_type: Optional[str] = None            # Alloy / Steel
    wheel_size_inch: Optional[int] = None
    sunroof_type: Optional[str] = None          # None / Single / Panoramic
    roof_rails: Optional[bool] = None
    spoiler: Optional[bool] = None
    # ── interior & comfort (spec) ──
    upholstery: Optional[str] = None            # Fabric / Leather / Leatherette
    ac_type: Optional[str] = None               # Manual / Auto-climate
    rear_ac_vents: Optional[bool] = None
    power_windows: Optional[str] = None         # All 4 / Front
    adjustable_seat: Optional[str] = None       # Height / Manual / Power
    # ── convenience (spec) ──
    push_button_start: Optional[bool] = None
    keyless_entry: Optional[bool] = None
    cruise_control: Optional[bool] = None
    auto_folding_orvm: Optional[bool] = None
    rear_defogger: Optional[bool] = None
    rear_wiper: Optional[bool] = None
    wireless_charging: Optional[bool] = None
    ventilated_seats: Optional[bool] = None
    connected_car: Optional[bool] = None
    # ── infotainment (spec) ──
    touchscreen_inches: Optional[float] = None
    android_auto_carplay: Optional[bool] = None
    speakers: Optional[int] = None
    camera_type: Optional[str] = None           # None / Reverse / 360
    steering_controls: Optional[bool] = None
    # ── safety (spec) ──
    airbags: Optional[int] = None
    abs_ebd: Optional[bool] = None
    esp: Optional[bool] = None
    hill_hold: Optional[bool] = None
    parking_sensors: Optional[str] = None       # None / Rear / Front+Rear
    isofix: Optional[bool] = None
    ncap_rating: Optional[int] = None           # stars
    # ── documents extra (dealership data) ──
    puc_valid_till: Optional[str] = None
    road_tax_status: Optional[str] = None       # Paid / Lifetime / Pending
    fitness_valid_till: Optional[str] = None
    duplicate_rc: Optional[bool] = None
    keys_count: Optional[int] = None
    # ── ownership extra (dealership data) ──
    usage_type: Optional[str] = None            # Private / Taxi / Corporate
    # ── condition extra (dealership data) ──
    tyre_life_pct: Optional[int] = None
    battery_replaced_on: Optional[str] = None
    # ── keys & accessories (dealership data) ──
    spare_key: Optional[bool] = None
    spare_tyre: Optional[bool] = None
    toolkit: Optional[bool] = None
    floor_mats: Optional[bool] = None
    accessories_added: Optional[str] = None
    # ── EV-specific (dealership data; conditional on fuel=Electric) ──
    battery_health_pct: Optional[int] = None
    real_range_km: Optional[int] = None
    battery_warranty_till: Optional[str] = None
    charger_type: Optional[str] = None
    charging_time: Optional[str] = None
    battery_owned: Optional[bool] = None

    # ── media summary ──
    photo_count: Optional[int] = None
    video_count: Optional[int] = None

    # ── location (internal only) ──
    location_code: Optional[str] = None
    location_type: str = LocationType.UNKNOWN
    customer_viewable: bool = True
    rto: Optional[str] = None

    # ── status / provenance ──
    listing_status: str = ListingStatus.AVAILABLE
    is_ivr_eligible: bool = False
    is_placeholder: bool = False
    source_sheet: str = "DNJ"

    # ── audit ──
    raw: Dict[str, Any] = field(default_factory=dict)
    as_of: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # media is stored separately (inventory_media); kept here for convenience
    media: List[InventoryMedia] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.registration_no = (self.registration_no or "").strip().upper()
        if self.id is None:
            self.id = deterministic_id(self.registration_no)

    # ── derived helpers ──
    @property
    def is_customer_facing(self) -> bool:
        """A row a customer may be offered: available, real, not a placeholder."""
        return (
            self.listing_status == ListingStatus.AVAILABLE
            and not self.is_placeholder
        )

    def to_record(self, *, include_media: bool = False) -> Dict[str, Any]:
        """Snake_case dict suitable for a Supabase upsert (catalogue columns)."""
        d = asdict(self)
        d.pop("media", None)
        if include_media:
            d["media"] = [m.to_record() for m in self.media]
        return d

    def fingerprint(self) -> Dict[str, Any]:
        """
        The mutable, business-meaningful subset used to decide whether an
        existing row actually changed (drives idempotent 'updated' counts).
        Excludes id / timestamps / raw.
        """
        skip = {"id", "created_at", "updated_at", "as_of", "raw", "media",
                "repaint_panels", "hypothecation_bank", "best_features",
                "known_issues", "warranty_provider"}
        return {k: v for k, v in asdict(self).items() if k not in skip}
