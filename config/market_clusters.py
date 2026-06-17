"""Auditable market clusters for valuation fallback.

Clusters are intentionally explicit, not inferred on the fly. Each cluster
groups nearby wards with similar landed-property market behavior so valuation
can fall back to a wider area while preserving the same road bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class MarketCluster:
    cluster_id: str
    wards: Tuple[str, ...]
    rationale: str


MARKET_CLUSTERS: Tuple[MarketCluster, ...] = (
    MarketCluster(
        cluster_id="tdm_tan_an_west",
        wards=("Tân An", "Chánh Mỹ", "Tương Bình Hiệp", "Hiệp An"),
        rationale=(
            "Adjacent west/north-west Thu Dau Mot wards with local-road and "
            "car-alley landed-property supply; used only after exact ward plus "
            "road-bucket samples are thin."
        ),
    ),
    MarketCluster(
        cluster_id="tdm_central",
        wards=("Phú Cường", "Phú Thọ", "Chánh Nghĩa", "Hiệp Thành"),
        rationale=(
            "Central Thu Dau Mot wards with denser urban/commercial land and "
            "house-land comparables."
        ),
    ),
    MarketCluster(
        cluster_id="tdm_north_industrial",
        wards=("Định Hòa", "Phú Mỹ", "Phú Tân", "Hòa Phú"),
        rationale=(
            "Northern Thu Dau Mot wards with industrial/new-urban influence; "
            "kept separate from the Tân An west cluster."
        ),
    ),
    MarketCluster(
        cluster_id="ben_cat_my_phuoc",
        wards=("Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4", "Thới Hòa"),
        rationale=(
            "Ben Cat/My Phuoc planned-market wards and sub-wards with similar "
            "grid-road land products."
        ),
    ),
    MarketCluster(
        cluster_id="ben_cat_outer",
        wards=("Tân Định", "Hòa Lợi", "Chánh Phú Hòa", "Tân Hưng", "Lai Hưng"),
        rationale=(
            "Outer Ben Cat/Hoa Loi corridor wards; wider fallback only when "
            "exact ward road-bucket samples are insufficient."
        ),
    ),
)


WARD_TO_MARKET_CLUSTER: Dict[str, MarketCluster] = {
    ward: cluster
    for cluster in MARKET_CLUSTERS
    for ward in cluster.wards
}


def cluster_for_ward(ward: Optional[str]) -> Optional[MarketCluster]:
    if not ward:
        return None
    return WARD_TO_MARKET_CLUSTER.get(ward)

