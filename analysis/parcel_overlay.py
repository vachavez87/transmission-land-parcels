"""
analysis/parcel_overlay.py
Spatial analysis: overlay land parcels with transmission corridors to determine:
    - Which parcels intersect the ROW corridor
    - What percentage of a parcel lies within the corridor
    - Distance from each parcel centroid to the nearest transmission centerline

All metric calculations (distances, areas) are performed in EPSG:5070
(US Albers Equal Area, meters) for accuracy, then converted to common US units.
"""
import logging

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.ops import unary_union

logger = logging.getLogger(__name__)

WORKING_CRS    = "EPSG:5070"
STORAGE_CRS    = "EPSG:4326"
METERS_PER_MILE = 1_609.34


class ParcelOverlay:
    """
    Overlays land parcels with transmission line corridors.

    Usage
    -----
    >>> overlay = ParcelOverlay()
    >>> analysis_gdf = overlay.analyze(parcels_gdf, projects_gdf, corridors_gdf)
    """

    def analyze(
        self,
        parcels_gdf: gpd.GeoDataFrame,
        projects_gdf: gpd.GeoDataFrame,
        corridors_gdf: gpd.GeoDataFrame,
    ) -> gpd.GeoDataFrame:
        """
        Full spatial analysis: corridor intersection, intersection percentage,
        and distance-to-centerline for every parcel.

        Parameters
        ----------
        parcels_gdf   : Parcel polygon GeoDataFrame (EPSG:4326)
        projects_gdf  : Transmission line GeoDataFrame (EPSG:4326)
        corridors_gdf : Corridor polygon GeoDataFrame (EPSG:4326)

        Returns
        -------
        GeoDataFrame with original parcel columns plus:
            in_corridor        (bool)
            corridor_project   (str  — project_id of intersecting corridor)
            intersection_pct   (float — 0–100 % of parcel area inside corridor)
            dist_to_line_miles (float — centroid distance to nearest line)
        """
        # --- Reproject everything to metric CRS ---
        parcels_p    = parcels_gdf.to_crs(WORKING_CRS)
        corridors_p  = corridors_gdf.to_crs(WORKING_CRS)
        lines_p      = projects_gdf.to_crs(WORKING_CRS)

        # ----------------------------------------------------------------
        # 1. Spatial join — which parcels intersect any corridor?
        # ----------------------------------------------------------------
        # Keep only the columns we need from corridors to avoid name clashes
        corr_slim = corridors_p[["project_id", "rto", "voltage_kv", "geometry"]].copy()
        corr_slim = corr_slim.rename(columns={
            "project_id": "corr_project_id",
            "rto":        "corr_rto",
            "voltage_kv": "corr_voltage_kv",
        })

        joined = gpd.sjoin(
            parcels_p,
            corr_slim,
            how="left",
            predicate="intersects",
        )

        # A parcel may intersect multiple corridors; keep the one with highest voltage
        joined["corr_voltage_kv"] = pd.to_numeric(
            joined.get("corr_voltage_kv", 0), errors="coerce"
        ).fillna(0)

        joined = (
            joined
            .sort_values("corr_voltage_kv", ascending=False)
            .loc[~joined.index.duplicated(keep="first")]
        )

        joined["in_corridor"]      = joined["corr_project_id"].notna()
        joined["corridor_project"] = joined["corr_project_id"].fillna("")
        joined = joined.drop(
            columns=[c for c in joined.columns
                     if c in ("index_right", "corr_rto", "corr_voltage_kv")],
            errors="ignore",
        )

        # ----------------------------------------------------------------
        # 2. Intersection percentage  (only for parcels inside corridor)
        # ----------------------------------------------------------------
        joined["intersection_pct"] = 0.0

        # Merge all corridors into one geometry for speed
        all_corridors_geom = corridors_p.geometry.unary_union

        in_corr_idx = joined.index[joined["in_corridor"]]
        for idx in in_corr_idx:
            parcel_geom = joined.at[idx, "geometry"]
            if parcel_geom.is_empty or parcel_geom.area == 0:
                continue
            intersection = parcel_geom.intersection(all_corridors_geom)
            pct = min(100.0, (intersection.area / parcel_geom.area) * 100)
            joined.at[idx, "intersection_pct"] = round(pct, 1)

        # ----------------------------------------------------------------
        # 3. Distance from parcel centroid to nearest transmission line
        # ----------------------------------------------------------------
        combined_lines = lines_p.geometry.unary_union
        centroids      = joined.geometry.centroid
        dist_meters    = centroids.distance(combined_lines)

        joined["dist_to_line_miles"] = (dist_meters / METERS_PER_MILE).round(3)

        # ----------------------------------------------------------------
        # 4. Reproject result back to WGS84
        # ----------------------------------------------------------------
        result = joined.to_crs(STORAGE_CRS)

        logger.info(
            "Overlay complete: %d parcels analysed | %d in corridor | avg dist %.2f mi",
            len(result),
            int(result["in_corridor"].sum()),
            result["dist_to_line_miles"].mean(),
        )
        return result
