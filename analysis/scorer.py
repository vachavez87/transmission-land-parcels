"""
analysis/scorer.py
Multi-factor parcel scoring engine (0–100 scale).

Score components
----------------
| Factor                | Max  | Logic |
|-----------------------|------|-------|
| Corridor intersection | 35   | Sliding scale based on intersection % |
| Distance to line      | 25   | Closer = higher score (table lookup) |
| Land use              | 15   | Agricultural best; commercial worst |
| Parcel size           | 10   | Larger parcels score higher |
| Sale / market status  | 15   | Currently for sale = full points |

Priority tiers
--------------
  CRITICAL  80–100   Almost certainly in the ROW path
  HIGH      60–79    Very likely needed
  MEDIUM    40–59    Monitor — possible alternate route
  LOW        0–39    Unlikely to be acquired
"""
import logging

import geopandas as gpd
import pandas as pd
import numpy as np

import config

logger = logging.getLogger(__name__)


class ParcelScorer:
    """
    Assigns a 0–100 acquisition-likelihood score to each parcel.

    Usage
    -----
    >>> scorer = ParcelScorer()
    >>> scored_gdf = scorer.score_parcels(analysis_gdf)
    """

    def score_parcels(self, analysis_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Score every parcel in the GeoDataFrame.

        Parameters
        ----------
        analysis_gdf : output of ParcelOverlay.analyze()
            Must contain: in_corridor, intersection_pct, dist_to_line_miles,
                          land_use, acreage, for_sale

        Returns
        -------
        GeoDataFrame with added columns:
            corridor_score, distance_score, land_use_score,
            size_score, sale_score, total_score, priority
        Sorted by total_score descending.
        """
        df = analysis_gdf.copy()

        # Normalise boolean columns (GeoJSON round-trips may stringify them)
        df["in_corridor"] = df["in_corridor"].apply(
            lambda v: str(v).lower() in ("true", "1", "yes")
        )
        df["for_sale"] = df["for_sale"].apply(
            lambda v: str(v).lower() in ("true", "1", "yes")
        )
        df["acreage"]           = pd.to_numeric(df["acreage"], errors="coerce").fillna(0)
        df["intersection_pct"]  = pd.to_numeric(df["intersection_pct"], errors="coerce").fillna(0)
        df["dist_to_line_miles"]= pd.to_numeric(df["dist_to_line_miles"], errors="coerce").fillna(99)

        # Compute individual factor scores
        df["corridor_score"]  = df.apply(self._corridor_score,   axis=1)
        df["distance_score"]  = df["dist_to_line_miles"].apply(self._distance_score)
        df["land_use_score"]  = df["land_use"].apply(self._land_use_score)
        df["size_score"]      = df["acreage"].apply(self._size_score)
        df["sale_score"]      = df["for_sale"].apply(lambda fs: 15 if fs else 0)

        df["total_score"] = (
            df["corridor_score"]
            + df["distance_score"]
            + df["land_use_score"]
            + df["size_score"]
            + df["sale_score"]
        ).round(1)

        df["priority"] = df["total_score"].apply(self._priority_label)

        # Sort highest-score first
        df = df.sort_values("total_score", ascending=False).reset_index(drop=True)

        logger.info(
            "Scoring complete: CRITICAL=%d  HIGH=%d  MEDIUM=%d  LOW=%d",
            (df["priority"] == "CRITICAL").sum(),
            (df["priority"] == "HIGH").sum(),
            (df["priority"] == "MEDIUM").sum(),
            (df["priority"] == "LOW").sum(),
        )
        return gpd.GeoDataFrame(df, geometry="geometry", crs=analysis_gdf.crs)

    # ------------------------------------------------------------------
    # Factor scoring methods
    # ------------------------------------------------------------------

    @staticmethod
    def _corridor_score(row) -> float:
        """
        35 pts max.
        Full intersection → 35; partial intersection → proportional to pct;
        proximity without intersection → small bonus for nearby parcels.
        """
        if row["in_corridor"]:
            pct = float(row.get("intersection_pct", 0))
            if pct >= 75:
                return 35.0
            elif pct >= 50:
                return 30.0
            elif pct >= 25:
                return 24.0
            else:
                return 18.0
        # Not in corridor but very close gets a small bump
        dist = float(row.get("dist_to_line_miles", 99))
        if dist < 0.5:
            return 8.0
        return 0.0

    @staticmethod
    def _distance_score(dist_miles: float) -> float:
        """
        25 pts max.  Uses lookup table from config.DISTANCE_SCORE_TABLE.
        """
        for threshold, points in config.DISTANCE_SCORE_TABLE:
            if dist_miles <= threshold:
                return float(points)
        return 0.0

    @staticmethod
    def _land_use_score(land_use: str) -> float:
        """
        15 pts max.  Agricultural / range land is easiest for easements.
        """
        return float(config.LAND_USE_SCORES.get(land_use, 3))

    @staticmethod
    def _size_score(acres: float) -> float:
        """
        10 pts max.  Larger parcels → more efficient ROW agreement.
        """
        for threshold, points in config.PARCEL_SIZE_SCORE_TABLE:
            if acres >= threshold:
                return float(points)
        return 1.0

    @staticmethod
    def _priority_label(score: float) -> str:
        tiers = config.PRIORITY_TIERS
        if score >= tiers["CRITICAL"]:
            return "CRITICAL"
        elif score >= tiers["HIGH"]:
            return "HIGH"
        elif score >= tiers["MEDIUM"]:
            return "MEDIUM"
        return "LOW"
