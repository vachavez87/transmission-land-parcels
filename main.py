#!/usr/bin/env python3
"""
main.py — Transmission Land Parcel Identification System
Demo entry point showcasing all required skills:
  Python | GeoPandas | PostGIS | Web Scraping | Energy & Real-Estate Data

Run:
    pip install -r requirements.txt
    python main.py
"""
import sys
import logging
from pathlib import Path

# ── logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,    # suppress library noise in demo output
    format="%(levelname)s | %(name)s | %(message)s",
)

# ── stdlib / third-party ────────────────────────────────────────────────────
import pandas as pd
import geopandas as gpd

# ── local modules ───────────────────────────────────────────────────────────
import config
from data.generate_sample_data import generate_all_sample_data
from analysis.corridor_mapper  import CorridorMapper
from analysis.parcel_overlay   import ParcelOverlay
from analysis.scorer           import ParcelScorer
from scrapers.rto_scraper      import RTOScraperManager
from database.db_manager       import DatabaseManager
from agent.weekly_updater      import TransmissionLandAgent
from visualization.map_renderer import MapRenderer

# ── constants ───────────────────────────────────────────────────────────────
DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")

BANNER = """\
╔══════════════════════════════════════════════════════════════════╗
║        TRANSMISSION LAND PARCEL IDENTIFICATION SYSTEM           ║
║   Demo  ·  Python · GeoPandas · PostGIS · Web Scraping          ║
╚══════════════════════════════════════════════════════════════════╝
"""

SEP = "─" * 66


def _section(title: str) -> None:
    """Print a step header."""
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def main() -> None:
    print(BANNER)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ===================================================================
    # STEP 1 — Load / generate sample transmission + parcel data
    # ===================================================================
    _section("STEP 1 / 7 — Transmission Project Data")

    proj_file   = DATA_DIR / "sample_transmission_projects.geojson"
    parcel_file = DATA_DIR / "sample_parcels.geojson"

    if not proj_file.exists() or not parcel_file.exists():
        print("  Generating synthetic sample data …")
        projects_gdf, parcels_gdf = generate_all_sample_data()
    else:
        projects_gdf = gpd.read_file(proj_file)
        parcels_gdf  = gpd.read_file(parcel_file)

    print(f"  ✓ {len(projects_gdf)} transmission projects loaded\n")
    for _, proj in projects_gdf.iterrows():
        print(
            f"    • {proj['project_id']:20s}  {proj['voltage_kv']:>3} kV  "
            f"{proj.get('length_miles', '?'):>4} mi  "
            f"[{proj['rto']}]  {proj['status']}"
        )
    print(f"\n  ✓ {len(parcels_gdf):,} land parcels loaded")

    # ===================================================================
    # STEP 2 — Web scraping demo (all 7 RTOs / ISOs)
    # ===================================================================
    _section("STEP 2 / 7 — Web Scraping: RTO / ISO Project Collection")
    print(
        "  Scrapers target real RTO websites in live mode.\n"
        "  Demo mode returns curated mock data:\n"
    )
    scraper_mgr = RTOScraperManager(demo_mode=True)
    scraper_mgr.demo_scrape()

    # ===================================================================
    # STEP 3 — Corridor mapping (GeoPandas + Shapely)
    # ===================================================================
    _section("STEP 3 / 7 — Corridor Mapping (GeoPandas)")
    print(
        f"  Buffer: {config.CORRIDOR_BUFFER_FEET} ft each side "
        f"→ {config.CORRIDOR_BUFFER_FEET * 2} ft total Right-of-Way\n"
        f"  Analysis CRS: EPSG:5070 (US Albers Equal Area, metres)\n"
        f"  Storage CRS:  EPSG:4326 (WGS84)\n"
    )
    mapper       = CorridorMapper(buffer_feet=config.CORRIDOR_BUFFER_FEET)
    corridors_gdf = mapper.create_corridors(projects_gdf)

    print(f"  ✓ Created {len(corridors_gdf)} corridor polygons")
    for _, c in corridors_gdf.iterrows():
        print(
            f"    • {c['project_id']:20s}  area = {c['corridor_area_sqmi']:.2f} sq mi"
        )

    # ===================================================================
    # STEP 4 — Spatial overlay (sjoin + distance + intersection %)
    # ===================================================================
    _section("STEP 4 / 7 — Spatial Parcel Overlay")
    print("  Running: sjoin (intersects) | ST_Distance | intersection %\n")

    overlay      = ParcelOverlay()
    analysis_gdf = overlay.analyze(parcels_gdf, projects_gdf, corridors_gdf)

    in_corridor  = int(analysis_gdf["in_corridor"].sum())
    near_1mi     = int((analysis_gdf["dist_to_line_miles"] < 1.0).sum())
    near_2mi     = int((analysis_gdf["dist_to_line_miles"] < 2.0).sum())

    print(f"  ✓ Parcels directly in ROW corridor : {in_corridor}")
    print(f"  ✓ Parcels within 1 mile            : {near_1mi}")
    print(f"  ✓ Parcels within 2 miles           : {near_2mi}")
    print(f"  ✓ Total parcels analysed           : {len(analysis_gdf):,}")

    # ===================================================================
    # STEP 5 — Multi-factor scoring
    # ===================================================================
    _section("STEP 5 / 7 — Parcel Scoring (0 – 100)")
    print(
        "  Factors: corridor intersection (35 pt) + distance (25 pt) +\n"
        "           land use (15 pt) + parcel size (10 pt) + "
        "sale status (15 pt)\n"
    )

    scorer     = ParcelScorer()
    scored_gdf = scorer.score_parcels(analysis_gdf)

    priority_counts = scored_gdf["priority"].value_counts()
    for tier in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = int(priority_counts.get(tier, 0))
        bar   = "█" * (count // 3)
        print(f"  {tier:10s}: {count:4d}  {bar}")

    # --- Top-10 table ---
    print()
    print("  TOP 10 PARCELS BY ACQUISITION SCORE")
    print("  " + "─" * 100)
    display_cols = [
        "parcel_id", "owner", "county", "state",
        "land_use", "acreage", "for_sale", "total_score", "priority",
    ]
    top10 = scored_gdf.nlargest(10, "total_score")[display_cols]

    HDR = (
        f"  {'Parcel ID':16s} {'Owner':22s} {'County':16s} ST  "
        f"{'Land Use':20s} {'Acres':>6}  Sale  Score  Priority"
    )
    print(HDR)
    print("  " + "─" * 100)

    for _, row in top10.iterrows():
        sale_flag = "  YES " if row["for_sale"] else "  no  "
        print(
            f"  {row['parcel_id']:16s} {str(row['owner'])[:22]:22s} "
            f"{str(row['county'])[:16]:16s} {row['state']:2s}  "
            f"{str(row['land_use'])[:20]:20s} {row['acreage']:>6.0f} "
            f"{sale_flag} {row['total_score']:5.1f}  {row['priority']}"
        )

    # --- For-sale alert ---
    for_sale_high = scored_gdf[
        scored_gdf["for_sale"].astype(bool)
        & scored_gdf["priority"].isin(["CRITICAL", "HIGH"])
    ]
    if len(for_sale_high):
        print(
            f"\n  ★ {len(for_sale_high)} HIGH-PRIORITY PARCEL(S) CURRENTLY "
            f"FOR SALE — immediate acquisition opportunity!"
        )

    # ===================================================================
    # STEP 6 — PostGIS demonstration
    # ===================================================================
    _section("STEP 6 / 7 — PostGIS Database (Demo)")
    db = DatabaseManager()
    db.demo_mode()

    # ===================================================================
    # STEP 7 — Interactive Folium map
    # ===================================================================
    _section("STEP 7 / 7 — Interactive Map (Folium)")
    print("  Generating interactive HTML map …")

    renderer = MapRenderer()
    folium_map = renderer.create_map(projects_gdf, corridors_gdf, scored_gdf)

    map_path = OUTPUT_DIR / "demo_map.html"
    folium_map.save(str(map_path))

    print(f"  ✓ Map saved → {map_path}")
    print(f"  ✓ Layers: corridors | centerlines | parcels by priority tier")
    print(f"  ✓ Click any parcel for full score breakdown")
    print(f"  ✓ Open in browser: start {map_path}   (Windows)")

    # ===================================================================
    # Weekly agent demo
    # ===================================================================
    _section("BONUS — Weekly Update Agent")
    print(
        "  The agent runs every Monday at 06:00 via the `schedule` library.\n"
        "  It re-scrapes RTOs, re-scores parcels, diffs against the prior\n"
        "  snapshot, and alerts on new listings / upgraded priorities.\n"
    )
    agent = TransmissionLandAgent()
    agent.run_demo(scored_gdf)

    # ===================================================================
    # Summary
    # ===================================================================
    print(f"\n{'═' * 66}")
    print("  DEMO COMPLETE")
    print(f"{'═' * 66}")
    print(
        f"\n  Projects analysed : {len(projects_gdf)}  "
        f"(MISO + PJM + ERCOT)\n"
        f"  Parcels scored    : {len(scored_gdf):,}\n"
        f"  Critical parcels  : {int(priority_counts.get('CRITICAL', 0))}\n"
        f"  High parcels      : {int(priority_counts.get('HIGH', 0))}\n"
        f"  For-sale (high+)  : {len(for_sale_high)}\n"
        f"\n  Output files:"
        f"\n    📄  {proj_file}"
        f"\n    📄  {parcel_file}"
        f"\n    🗺   {map_path}\n"
    )


if __name__ == "__main__":
    main()
