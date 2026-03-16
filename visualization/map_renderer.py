"""
visualization/map_renderer.py
Creates an interactive Folium HTML map with:
    - Transmission line corridors (semi-transparent fill, per-RTO colour)
    - Transmission centerlines (coloured by RTO)
    - Land parcels colour-coded by acquisition priority
    - Clickable popups showing score detail, ownership, sale status
    - Layer control (toggle each RTO's line + priority tier)
    - Legend (bottom-left)
"""
import logging

import folium
import geopandas as gpd
import pandas as pd
from folium.plugins import MarkerCluster

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------
PRIORITY_COLORS = {
    "CRITICAL": "#c62828",   # dark red
    "HIGH":     "#ef6c00",   # orange
    "MEDIUM":   "#f9a825",   # amber
    "LOW":      "#2e7d32",   # dark green
}

PRIORITY_FILL_OPACITY = {
    "CRITICAL": 0.70,
    "HIGH":     0.60,
    "MEDIUM":   0.50,
    "LOW":      0.35,
}

RTO_LINE_COLORS = {
    "MISO":   "#1565c0",   # blue
    "PJM":    "#00695c",   # teal
    "ERCOT":  "#e65100",   # deep orange
    "CAISO":  "#6a1b9a",   # purple
    "SPP":    "#558b2f",   # olive green
    "NYISO":  "#37474f",   # blue-grey
    "ISO-NE": "#4e342e",   # brown
}

CORRIDOR_FILL_COLOR  = "#90caf9"   # light blue
CORRIDOR_LINE_COLOR  = "#1565c0"


class MapRenderer:
    """
    Builds a multi-layer Folium interactive map.

    Usage
    -----
    >>> renderer = MapRenderer()
    >>> m = renderer.create_map(projects_gdf, corridors_gdf, scored_gdf)
    >>> m.save("output/demo_map.html")
    """

    def create_map(
        self,
        projects_gdf: gpd.GeoDataFrame,
        corridors_gdf: gpd.GeoDataFrame,
        scored_gdf: gpd.GeoDataFrame,
    ) -> folium.Map:
        """
        Build the interactive map.

        Parameters
        ----------
        projects_gdf  : Transmission line GeoDataFrame
        corridors_gdf : Corridor polygon GeoDataFrame
        scored_gdf    : Scored parcel GeoDataFrame (output of ParcelScorer)

        Returns
        -------
        folium.Map ready to be saved as HTML.
        """
        # --- Centre the map on the geographic midpoint of all parcels ---
        # Project to metric CRS first to avoid centroid-on-geographic-CRS warning
        all_centroids = scored_gdf.to_crs("EPSG:5070").geometry.centroid.to_crs("EPSG:4326")
        center_lat = all_centroids.y.median()
        center_lon = all_centroids.x.median()

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=6,
            tiles="CartoDB positron",
            prefer_canvas=True,
        )

        # --- Layer 1: Transmission corridors ---
        self._add_corridors(m, corridors_gdf)

        # --- Layer 2: Transmission centerlines ---
        self._add_lines(m, projects_gdf)

        # --- Layers 3–6: Parcels by priority (LOW first so CRITICAL renders on top) ---
        for priority in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            self._add_parcel_layer(
                m, scored_gdf, priority,
                show=(priority in ("CRITICAL", "HIGH")),
            )

        # --- Legend + layer control ---
        self._add_legend(m)
        folium.LayerControl(collapsed=False).add_to(m)

        logger.info("Interactive map built with %d parcels", len(scored_gdf))
        return m

    # ------------------------------------------------------------------
    # Private layer builders
    # ------------------------------------------------------------------

    def _add_corridors(
        self,
        m: folium.Map,
        corridors_gdf: gpd.GeoDataFrame,
    ) -> None:
        group = folium.FeatureGroup(name="Transmission Corridors (ROW)", show=True)

        for _, row in corridors_gdf.iterrows():
            rto   = row.get("rto", "MISO")
            color = RTO_LINE_COLORS.get(rto, CORRIDOR_LINE_COLOR)

            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda _, c=color: {
                    "fillColor":   c,
                    "color":       c,
                    "weight":      1.5,
                    "fillOpacity": 0.18,
                    "opacity":     0.6,
                },
                tooltip=folium.Tooltip(
                    f"<b>{row.get('project_id', '')}</b><br>"
                    f"{row.get('name', '')}<br>"
                    f"RoW: {row.get('total_width_ft', '?')} ft total<br>"
                    f"Area: {row.get('corridor_area_sqmi', 0):.1f} sq mi"
                ),
            ).add_to(group)

        group.add_to(m)

    def _add_lines(
        self,
        m: folium.Map,
        projects_gdf: gpd.GeoDataFrame,
    ) -> None:
        group = folium.FeatureGroup(name="Transmission Lines", show=True)

        for _, row in projects_gdf.iterrows():
            rto   = row.get("rto", "MISO")
            color = RTO_LINE_COLORS.get(rto, "#333")
            coords = [(y, x) for x, y in row.geometry.coords]

            folium.PolyLine(
                locations=coords,
                color=color,
                weight=4,
                opacity=0.9,
                tooltip=folium.Tooltip(
                    f"<b>{row.get('project_id', '')}</b><br>"
                    f"{row.get('name', '')}<br>"
                    f"RTO: {rto} | {row.get('voltage_kv', '?')} kV<br>"
                    f"Status: {row.get('status', '?')}<br>"
                    f"Length: {row.get('length_miles', '?')} mi | "
                    f"Est. cost: ${row.get('estimated_cost_m', 0):,.0f}M<br>"
                    f"Expected COD: {row.get('expected_cod', '?')}"
                ),
            ).add_to(group)

            # Add endpoint markers
            start = coords[0]
            end   = coords[-1]
            for pt, label in [(start, "Start"), (end, "End")]:
                folium.CircleMarker(
                    location=pt,
                    radius=5,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.8,
                    tooltip=f"{row.get('project_id')} — {label}",
                ).add_to(group)

        group.add_to(m)

    def _add_parcel_layer(
        self,
        m: folium.Map,
        scored_gdf: gpd.GeoDataFrame,
        priority: str,
        show: bool = True,
    ) -> None:
        color   = PRIORITY_COLORS[priority]
        opacity = PRIORITY_FILL_OPACITY[priority]
        group   = folium.FeatureGroup(
            name=f"Parcels — {priority}", show=show
        )

        parcels = scored_gdf[scored_gdf["priority"] == priority]

        for _, row in parcels.iterrows():
            sale_badge = " ★ FOR SALE" if row.get("for_sale") else ""
            price_str  = (
                f"${row['asking_price_usd']:,.0f}"
                if pd.notna(row.get("asking_price_usd")) and row["asking_price_usd"]
                else "—"
            )

            popup_html = (
                f"<div style='width:260px;font-family:sans-serif;font-size:13px'>"
                f"<b style='font-size:14px'>{row.get('parcel_id', '')} "
                f"<span style='color:{color}'>[{priority}]</span></b>"
                f"<span style='color:#e53935'>{sale_badge}</span><br><hr style='margin:4px 0'>"
                f"<b>Owner:</b> {row.get('owner', '?')}<br>"
                f"<b>Location:</b> {row.get('county', '?')}, {row.get('state', '?')}<br>"
                f"<b>Land Use:</b> {row.get('land_use', '?')}<br>"
                f"<b>Acreage:</b> {row.get('acreage', 0):,.0f} ac<br>"
                f"<b>Assessed Value:</b> "
                f"${row.get('assessed_value_usd', 0) or 0:,.0f}<br>"
                f"<b>Asking Price:</b> {price_str}<br>"
                f"<hr style='margin:4px 0'>"
                f"<b>Total Score:</b> {row.get('total_score', 0):.1f} / 100<br>"
                f"<b>In Corridor:</b> {'✓ Yes' if row.get('in_corridor') else '✗ No'}<br>"
                f"<b>Intersect %:</b> {row.get('intersection_pct', 0):.1f}%<br>"
                f"<b>Dist to Line:</b> {row.get('dist_to_line_miles', 0):.2f} mi<br>"
                f"<b>Corridor Score:</b> {row.get('corridor_score', 0):.0f} / 35<br>"
                f"<b>Distance Score:</b> {row.get('distance_score', 0):.0f} / 25<br>"
                f"<b>Land-Use Score:</b> {row.get('land_use_score', 0):.0f} / 15<br>"
                f"<b>Size Score:</b>     {row.get('size_score', 0):.0f} / 10<br>"
                f"<b>Sale Score:</b>     {row.get('sale_score', 0):.0f} / 15"
                f"</div>"
            )

            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda _, c=color, o=opacity: {
                    "fillColor":   c,
                    "color":       c,
                    "weight":      1,
                    "fillOpacity": o,
                },
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=folium.Tooltip(
                    f"{row.get('parcel_id', '')} | "
                    f"{row.get('acreage', 0):.0f} ac | "
                    f"Score: {row.get('total_score', 0):.0f} | "
                    f"[{priority}]"
                    + (" ★ FOR SALE" if row.get("for_sale") else "")
                ),
            ).add_to(group)

        group.add_to(m)

    def _add_legend(self, m: folium.Map) -> None:
        rto_entries = "".join(
            f'<div><span style="color:{c};font-size:16px">━</span> '
            f'<b>{rto}</b></div>'
            for rto, c in RTO_LINE_COLORS.items()
            if rto in ("MISO", "PJM", "ERCOT", "CAISO", "SPP")
        )
        priority_entries = "".join(
            f'<div><span style="color:{c};font-size:18px">■</span> '
            f'<b>{p}</b></div>'
            for p, c in PRIORITY_COLORS.items()
        )

        legend_html = f"""
        <div style="
            position: fixed; bottom: 30px; left: 30px;
            z-index: 1000; background: rgba(255,255,255,0.93);
            padding: 14px 18px; border-radius: 8px;
            border: 1px solid #bbb; font-family: sans-serif;
            font-size: 13px; box-shadow: 2px 2px 8px rgba(0,0,0,0.15);
            min-width: 180px;">
          <div style="font-size:14px;font-weight:bold;margin-bottom:6px">
            🗺 Parcel Acquisition Priority
          </div>
          {priority_entries}
          <div style="margin-top:8px;font-size:14px;font-weight:bold">
            ⚡ Transmission Lines
          </div>
          {rto_entries}
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))
