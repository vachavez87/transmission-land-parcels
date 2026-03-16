"""
analysis/corridor_mapper.py
Creates Right-of-Way corridor polygons by buffering transmission line
geometries to the specified half-width.

Key design decisions:
    - All buffering is done in EPSG:5070 (US Albers Equal Area, meters)
      so that foot/meter distances are accurate across the continental US.
    - Results are reprojected back to EPSG:4326 for storage and display.
    - cap_style=2 (flat caps) avoids balloon shapes at line endpoints.
"""
import logging

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)

FEET_PER_METER = 3.28084
WORKING_CRS    = "EPSG:5070"   # US Albers Equal Area (meters)
STORAGE_CRS    = "EPSG:4326"   # WGS84 lon/lat


class CorridorMapper:
    """
    Buffers transmission LineString geometries into ROW corridor polygons.

    Example
    -------
    >>> mapper = CorridorMapper(buffer_feet=300)
    >>> corridors_gdf = mapper.create_corridors(projects_gdf)
    """

    def __init__(self, buffer_feet: int = 300):
        """
        Parameters
        ----------
        buffer_feet : int
            Half-width of the ROW corridor in feet.
            Total corridor width = buffer_feet * 2.
            Typical values:
              500kV AC  → 300 ft  (600 ft total)
              345kV AC  → 200 ft  (400 ft total)
              230kV AC  → 150 ft  (300 ft total)
        """
        self.buffer_feet   = buffer_feet
        self.buffer_meters = buffer_feet / FEET_PER_METER

    def create_corridors(self, projects_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Build a corridor polygon for every transmission line project.

        Parameters
        ----------
        projects_gdf : GeoDataFrame
            LineString geometries in EPSG:4326.
            Required columns: project_id, name, rto, voltage_kv

        Returns
        -------
        GeoDataFrame of corridor Polygon geometries in EPSG:4326.
        """
        if projects_gdf.crs is None:
            projects_gdf = projects_gdf.set_crs(STORAGE_CRS)

        # Reproject to metric CRS for accurate buffering
        projected = projects_gdf.to_crs(WORKING_CRS)

        corridors = []
        for _, row in projected.iterrows():
            # flat caps (cap_style=2) stops circular balloons at line ends
            corridor_geom = row.geometry.buffer(self.buffer_meters, cap_style=2)

            # Km² → sq miles  (1 km² = 0.386102 mi²)
            area_sqmi = (corridor_geom.area / 1_000_000) * 0.386102

            corridors.append({
                "project_id":       row["project_id"],
                "name":             row["name"],
                "rto":              row["rto"],
                "voltage_kv":       row["voltage_kv"],
                "buffer_feet":      self.buffer_feet,
                "total_width_ft":   self.buffer_feet * 2,
                "corridor_area_sqmi": round(area_sqmi, 2),
                "geometry":         corridor_geom,
            })

        corridors_gdf = gpd.GeoDataFrame(corridors, crs=WORKING_CRS)
        result = corridors_gdf.to_crs(STORAGE_CRS)

        logger.info(
            "Created %d corridor polygons (buffer = %d ft each side)",
            len(result), self.buffer_feet,
        )
        return result

    def create_search_bands(
        self,
        projects_gdf: gpd.GeoDataFrame,
        radius_miles: float = 5.0,
    ) -> gpd.GeoDataFrame:
        """
        Create wider search-band polygons for finding parcels that may be
        needed if the centerline shifts during detailed engineering.

        Parameters
        ----------
        projects_gdf : GeoDataFrame
        radius_miles : float
            Radius in miles for the expanded search band.

        Returns
        -------
        GeoDataFrame with wider buffer polygons in EPSG:4326.
        """
        buffer_meters = radius_miles * 1_609.34

        if projects_gdf.crs is None:
            projects_gdf = projects_gdf.set_crs(STORAGE_CRS)

        projected  = projects_gdf.to_crs(WORKING_CRS)
        bands      = projected.copy()
        bands["geometry"]       = projected.geometry.buffer(buffer_meters)
        bands["buffer_type"]    = "search_band"
        bands["buffer_miles"]   = radius_miles

        return bands.to_crs(STORAGE_CRS)
