"""Shadow median road-tier valuation engine.

This replaces the earlier shadow regression model with a simpler deterministic
baseline: median price/m2 by segment and broad road-tier bucket, then transparent
area/legal/shape adjustments. The public import path is kept stable because the
reprocess pipeline already imports this module for the shadow model.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
import json
from typing import Dict, List, Optional, Tuple

import numpy as np

from analytics.valuation import (
    ACTIONABLE_SUPPRESS_FLAGS,
    DEFAULT_BASELINE_SOURCES,
    EXPECTED_NEGOTIATION_RATIO,
    Listing,
    PRIMARY_BASELINE_MIN_CANONICAL_N,
    SOURCE_SIGNAL_SUPPRESS_FLAGS,
    SUPPLEMENTAL_BASELINE_SOURCE,
    SUPPLEMENTAL_BASELINE_WEIGHT,
    SUPPLEMENTAL_GULAND_OLD_POST_DAYS,
    SUPPLEMENTAL_LARGE_LOT_AREA_M2,
    ValuationResult,
    _effective_has_so,
    _has_legal_conflict,
    _source_flags,
    compute_signal_score,
    extract_regex_features,
)

MODEL_NAME = "median_road_tier"
MODEL_VERSION = "median_road_tier_v1"

MIN_BUCKET_SAMPLES = 8
MIN_SEGMENT_SAMPLES = 8
TIER4_PENALTY = 0.85
TIER5_PENALTY = 0.75


def _road_model_tier(road_tier: int | None) -> int:
    tier = int(road_tier or 0)
    if tier == 1:
        return 1
    if tier == 2:
        return 2
    return 3


def _area_adjustment(area_m2: float | None, ref_area_m2: float | None) -> tuple[float, tuple[str, ...], dict]:
    if not area_m2 or not ref_area_m2 or area_m2 <= 0 or ref_area_m2 <= 0:
        return 1.0, (), {"area_ratio": None, "area_adjustment": 1.0}
    ratio = float(area_m2) / float(ref_area_m2)
    flags: list[str] = []
    if ratio <= 0.7:
        factor = 1.05
    elif ratio <= 1.5:
        factor = 1.0
    elif ratio <= 3.0:
        factor = 0.90
    elif ratio <= 6.0:
        factor = 0.80
    else:
        factor = 0.65
        flags.append("large_lot_model_risk")
    return factor, tuple(flags), {"area_ratio": round(ratio, 3), "area_adjustment": factor}


def _road_penalty(road_tier: int | None) -> tuple[float, tuple[str, ...]]:
    tier = int(road_tier or 0)
    if tier == 4:
        return TIER4_PENALTY, ()
    if tier == 5:
        return TIER5_PENALTY, ()
    if tier == 0:
        return 1.0, ("low_road_confidence",)
    return 1.0, ()


@dataclass
class MedianRoadTierSegmentModel:
    segment_key: Tuple[str, str, str]
    fallback_level: str = "exact"
    ref_area_m2: float = 0.0
    segment_median_ppm2: float = 0.0
    bucket_medians: Dict[int, float] = field(default_factory=dict)
    bucket_counts: Dict[int, int] = field(default_factory=dict)
    n_samples: int = 0
    fitted: bool = False

    def fit(self, listings: List[Listing]):
        clean = [
            listing for listing in listings
            if listing.price_per_m2 and listing.price_per_m2 > 0
            and listing.area_m2 and listing.area_m2 > 0
        ]
        if len(clean) < MIN_SEGMENT_SAMPLES:
            return
        self.ref_area_m2 = float(np.median([listing.area_m2 for listing in clean]))
        self.segment_median_ppm2 = float(np.median([listing.price_per_m2 for listing in clean]))
        self.n_samples = len(clean)
        buckets: dict[int, list[float]] = defaultdict(list)
        for listing in clean:
            buckets[_road_model_tier(listing.road_tier)].append(float(listing.price_per_m2))
        for tier, prices in buckets.items():
            self.bucket_counts[tier] = len(prices)
            if len(prices) >= MIN_BUCKET_SAMPLES:
                self.bucket_medians[tier] = float(np.median(prices))
        self.fitted = True

    def base_ppm2_for_tier(self, road_tier: int | None) -> tuple[Optional[float], str]:
        model_tier = _road_model_tier(road_tier)
        if model_tier in self.bucket_medians:
            return self.bucket_medians[model_tier], f"road_tier_{model_tier}"
        if self.segment_median_ppm2 > 0:
            return self.segment_median_ppm2, "segment_median"
        return None, "missing"

    def confidence_level(self):
        if self.n_samples >= 45:
            return "high"
        return "medium" if self.n_samples >= MIN_SEGMENT_SAMPLES else "low"


class MedianRoadTierValuationEngine:
    def __init__(self, baseline_sources=None):
        self._models: Dict[Tuple[str, str, str], MedianRoadTierSegmentModel] = {}
        self._baseline_sources = tuple(
            str(source).strip().lower()
            for source in (baseline_sources or DEFAULT_BASELINE_SOURCES)
            if str(source).strip()
        )

    def _key(self, listing: Listing):
        return (listing.ward or "SELECTED_REGION", listing.property_type, listing.tx_type)

    def _fallback_key(self, listing: Listing):
        return ("SELECTED_REGION", listing.property_type, listing.tx_type)

    def _parent_ward_key(self, listing: Listing):
        from config.area_profiles import ALL_SUBWARDS
        parent = ALL_SUBWARDS.get(listing.ward)
        if parent:
            return (parent, listing.property_type, listing.tx_type)
        return None

    def _dedupe_training_lots(self, listings: List[Listing]) -> List[Listing]:
        lots: Dict[int, Listing] = {}
        for listing in listings:
            lot_id = getattr(listing, "duplicate_of_id", None) or listing.id
            current = lots.get(lot_id)
            if current is None:
                lots[lot_id] = listing
            elif listing.id == lot_id and current.id != lot_id:
                lots[lot_id] = listing
            elif current.id != lot_id and (listing.crawled_at or date.min) > (current.crawled_at or date.min):
                lots[lot_id] = listing
        return list(lots.values())

    def _is_primary_baseline_source(self, listing: Listing) -> bool:
        source = (getattr(listing, "source", "") or "").strip().lower()
        return not self._baseline_sources or not source or source in self._baseline_sources

    def _is_strict_supplemental_baseline(self, listing: Listing) -> bool:
        source = (getattr(listing, "source", "") or "").strip().lower()
        if source != SUPPLEMENTAL_BASELINE_SOURCE:
            return False
        if getattr(listing, "exclude_from_baseline", False) or _source_flags(listing):
            return False
        if not listing.ward or listing.ward == "unknown":
            return False
        if not listing.price_total or not listing.price_per_m2 or not listing.area_m2:
            return False
        if listing.area_m2 >= SUPPLEMENTAL_LARGE_LOT_AREA_M2:
            if (listing.road_tier or 0) <= 0:
                return False
        posted = getattr(listing, "posted_at", None)
        crawled = getattr(listing, "crawled_at", None)
        if posted and crawled and (crawled - posted).days >= SUPPLEMENTAL_GULAND_OLD_POST_DAYS:
            return False
        return True

    def _add_training_listing(self, groups, parent_groups, fallback_groups, listing: Listing):
        from config.area_profiles import ALL_SUBWARDS
        groups[self._key(listing)].append(listing)
        fallback_groups[self._fallback_key(listing)].append(listing)
        parent = ALL_SUBWARDS.get(listing.ward)
        if parent:
            parent_groups[(parent, listing.property_type, listing.tx_type)].append(listing)

    def _combine_primary_and_supplemental(self, primary_groups, supplemental_groups):
        combined = {}
        for key in set(primary_groups) | set(supplemental_groups):
            primary = primary_groups.get(key, [])
            listings = primary
            if len(primary) < PRIMARY_BASELINE_MIN_CANONICAL_N:
                listings = primary + supplemental_groups.get(key, [])
            if listings:
                combined[key] = listings
        return combined

    def fit(self, listings: List[Listing], conn=None):
        listings = self._dedupe_training_lots(listings)
        primary_segs = defaultdict(list)
        primary_fallback_segs = defaultdict(list)
        primary_parent_segs = defaultdict(list)
        supplemental_segs = defaultdict(list)
        supplemental_fallback_segs = defaultdict(list)
        supplemental_parent_segs = defaultdict(list)

        for listing in listings:
            if getattr(listing, "exclude_from_baseline", False) or _source_flags(listing):
                continue
            if not (listing.price_per_m2 and listing.area_m2):
                continue
            if self._is_primary_baseline_source(listing):
                listing.baseline_weight = 1.0
                self._add_training_listing(primary_segs, primary_parent_segs, primary_fallback_segs, listing)
            elif self._is_strict_supplemental_baseline(listing):
                listing.baseline_weight = SUPPLEMENTAL_BASELINE_WEIGHT
                self._add_training_listing(supplemental_segs, supplemental_parent_segs, supplemental_fallback_segs, listing)

        model_groups = [
            (self._combine_primary_and_supplemental(primary_segs, supplemental_segs), "exact"),
            (self._combine_primary_and_supplemental(primary_parent_segs, supplemental_parent_segs), "parent"),
            (self._combine_primary_and_supplemental(primary_fallback_segs, supplemental_fallback_segs), "region"),
        ]
        for groups, fallback_level in model_groups:
            for key, group_listings in groups.items():
                model = MedianRoadTierSegmentModel(key, fallback_level=fallback_level)
                model.fit(group_listings)
                if model.fitted:
                    self._models[key] = model

    def _model_for(self, listing: Listing) -> Optional[MedianRoadTierSegmentModel]:
        model = self._models.get(self._key(listing))
        if model:
            return model
        parent_key = self._parent_ward_key(listing)
        if parent_key and parent_key in self._models:
            return self._models[parent_key]
        return self._models.get(self._fallback_key(listing))

    def valuate(self, listing: Listing) -> Optional[ValuationResult]:
        if not listing.price_per_m2:
            return None
        model = self._model_for(listing)
        if not model:
            return None
        base_fair, price_basis = model.base_ppm2_for_tier(listing.road_tier)
        if not base_fair:
            return None

        quality_flags = set(_source_flags(listing))
        area_factor, area_flags, area_audit = _area_adjustment(listing.area_m2, model.ref_area_m2)
        road_factor, road_flags = _road_penalty(listing.road_tier)
        quality_flags.update(area_flags)
        quality_flags.update(road_flags)

        fair = base_fair * area_factor * road_factor
        feat = extract_regex_features(f"{listing.title} {listing.description}")
        if feat.get("is_corner"):
            fair *= 1.10
        if feat.get("is_ná»Ÿ_háº­u"):
            fair *= 1.05
        if feat.get("is_tháº¯t_háº­u"):
            fair *= 0.90
        if feat.get("is_Ä‘Æ°á»ng_Ä‘Ã¢m"):
            fair *= 0.85
        if feat.get("near_grave"):
            fair *= 0.80
        if not _effective_has_so(listing):
            fair *= 0.75
        fair *= EXPECTED_NEGOTIATION_RATIO
        fair = round(fair, 2)

        actual = float(listing.price_per_m2)
        discount = (fair - actual) / fair if fair else 0.0

        from config.settings import SIGNAL_MOS_THRESHOLD
        is_signal = discount >= SIGNAL_MOS_THRESHOLD
        if not listing.ward or listing.ward == "unknown":
            is_signal = False
        if _has_legal_conflict(listing):
            is_signal = False

        source_quality_recheck = bool(is_signal and (quality_flags & ACTIONABLE_SUPPRESS_FLAGS))
        score = compute_signal_score(listing, discount * 100) if is_signal else 0
        audit = {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "segment": "|".join(model.segment_key),
            "fallback_level": model.fallback_level,
            "price_basis": price_basis,
            "ref_area_m2": round(model.ref_area_m2, 2) if model.ref_area_m2 else None,
            "road_model_tier": _road_model_tier(listing.road_tier),
            "actual_road_tier": int(listing.road_tier or 0),
            "road_bucket_counts": model.bucket_counts,
            "road_penalty": road_factor,
            **area_audit,
        }

        return ValuationResult(
            listing_id=listing.id,
            area=listing.area,
            property_type=listing.property_type,
            price_per_m2_actual=round(actual, 2),
            price_per_m2_fair=fair,
            discount_pct=round(discount * 100, 1),
            is_signal=is_signal,
            confidence=model.confidence_level(),
            segment_n=model.n_samples,
            signal_score=score,
            is_outlier=False,
            note=json.dumps(audit, ensure_ascii=False),
            source_quality_flags=tuple(sorted(quality_flags)),
            source_quality_recheck=source_quality_recheck,
            legal_status=getattr(listing, "legal_status", "unverified") or "unverified",
            trust_tier=getattr(listing, "trust_tier", "candidate_signal") or "candidate_signal",
            trust_score=int(getattr(listing, "trust_score", 0) or 0),
            legal_flags=tuple(sorted(getattr(listing, "legal_flags", ()) or ())),
        )

    def valuate_batch(self, listings: List[Listing]) -> List[ValuationResult]:
        results = []
        for listing in listings:
            result = self.valuate(listing)
            if result:
                results.append(result)
        return results


# Backward-compatible import name for the existing reprocess pipeline.
HierarchicalValuationEngine = MedianRoadTierValuationEngine
