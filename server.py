"""
server.py — Flask web server for the Transmission Land Parcel System.

Routes
------
GET /                     Dashboard (stats + top parcels table + map)
GET /map                  Full-screen interactive Folium map
GET /api/projects         JSON — all transmission projects
GET /api/parcels/top      JSON — top-N scored parcels
GET /api/parcels/for-sale JSON — high-priority for-sale parcels
GET /api/stats            JSON — summary statistics
GET /api/refresh          Trigger pipeline re-run (re-score all parcels)

Run
---
    pip install flask
    python server.py          ← http://localhost:5000
"""
import json
import logging
import os
import threading
from pathlib import Path

import geopandas as gpd
import pandas as pd
from flask import Flask, jsonify, render_template, send_from_directory

# ── local modules ──────────────────────────────────────────────────────────
import config
from data.generate_sample_data import generate_all_sample_data
from analysis.corridor_mapper  import CorridorMapper
from analysis.parcel_overlay   import ParcelOverlay
from analysis.scorer           import ParcelScorer
from visualization.map_renderer import MapRenderer

# ── logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── app setup ──────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── global pipeline state (loaded once on startup) ─────────────────────────
_state: dict = {}
_pipeline_ready = False
_pipeline_error: str = ""


def _run_pipeline() -> None:
    """Load data → corridor map → overlay → score → render map."""
    global _state

    logger.info("Running analysis pipeline …")

    # 1. Data
    proj_file   = DATA_DIR / "sample_transmission_projects.geojson"
    parcel_file = DATA_DIR / "sample_parcels.geojson"

    if not proj_file.exists() or not parcel_file.exists():
        projects_gdf, parcels_gdf = generate_all_sample_data()
    else:
        projects_gdf = gpd.read_file(proj_file)
        parcels_gdf  = gpd.read_file(parcel_file)

    # 2. Corridor mapping
    mapper       = CorridorMapper(buffer_feet=config.CORRIDOR_BUFFER_FEET)
    corridors    = mapper.create_corridors(projects_gdf)

    # 3. Overlay + scoring
    overlay      = ParcelOverlay()
    analysis     = overlay.analyze(parcels_gdf, projects_gdf, corridors)
    scorer       = ParcelScorer()
    scored       = scorer.score_parcels(analysis)

    # 4. Folium map
    renderer  = MapRenderer()
    fmap      = renderer.create_map(projects_gdf, corridors, scored)
    map_path  = OUTPUT_DIR / "demo_map.html"
    fmap.save(str(map_path))

    # 5. Store state
    priority_counts = scored["priority"].value_counts().to_dict()
    _state = {
        "projects_gdf":     projects_gdf,
        "parcels_gdf":      parcels_gdf,
        "corridors_gdf":    corridors,
        "scored_gdf":       scored,
        "priority_counts":  priority_counts,
        "map_path":         map_path,
        "total_parcels":    len(scored),
        "for_sale_high":    int(
            scored[
                scored["for_sale"].astype(bool)
                & scored["priority"].isin(["CRITICAL", "HIGH"])
            ].shape[0]
        ),
    }
    logger.info("Pipeline complete. %d parcels scored.", len(scored))
    global _pipeline_ready
    _pipeline_ready = True


# ── helpers ────────────────────────────────────────────────────────────────

def _scored_to_records(gdf: gpd.GeoDataFrame, limit: int = 500) -> list[dict]:
    """Convert GeoDataFrame to JSON-serialisable list (drop geometry)."""
    df = pd.DataFrame(gdf.drop(columns="geometry", errors="ignore"))

    # Normalise types for JSON serialisation
    for col in df.select_dtypes(include=["bool"]).columns:
        df[col] = df[col].astype(bool)
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].round(2)

    # Replace NaN / None
    df = df.fillna("")
    return df.head(limit).to_dict(orient="records")


def _project_geojson(gdf: gpd.GeoDataFrame) -> dict:
    """Return GeoJSON FeatureCollection from a GeoDataFrame."""
    return json.loads(gdf.to_json())


# ── routes ─────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    """Health check endpoint for Render — responds immediately."""
    if _pipeline_ready:
        return jsonify({"status": "ok"}), 200
    return jsonify({"status": "starting"}), 200


@app.route("/")
def dashboard():
    """Main dashboard page."""
    if not _pipeline_ready:
        return "<html><body style='background:#111;color:#0f0;font-family:monospace;padding:2rem'><h2>Pipeline initializing, please wait...</h2><script>setTimeout(()=>location.reload(),3000)</script></body></html>", 503
    scored = _state.get("scored_gdf", gpd.GeoDataFrame())
    pc     = _state.get("priority_counts", {})

    stats = {
        "total_projects": len(_state.get("projects_gdf", [])),
        "total_parcels":  _state.get("total_parcels", 0),
        "critical":       pc.get("CRITICAL", 0),
        "high":           pc.get("HIGH",     0),
        "medium":         pc.get("MEDIUM",   0),
        "low":            pc.get("LOW",      0),
        "for_sale_high":  _state.get("for_sale_high", 0),
    }

    top_parcels = []
    if not scored.empty:
        cols = [
            "parcel_id", "owner", "county", "state", "land_use",
            "acreage", "for_sale", "total_score", "priority",
            "dist_to_line_miles",
        ]
        top_df = scored.nlargest(20, "total_score")[[
            c for c in cols if c in scored.columns
        ]]
        top_df = top_df.fillna("")
        for col in top_df.select_dtypes(include=["bool"]).columns:
            top_df[col] = top_df[col].astype(bool)
        top_parcels = top_df.to_dict(orient="records")

    projects = []
    if "projects_gdf" in _state and not _state["projects_gdf"].empty:
        proj_df = pd.DataFrame(
            _state["projects_gdf"].drop(columns="geometry", errors="ignore")
        ).fillna("")
        projects = proj_df.to_dict(orient="records")

    return render_template(
        "dashboard.html",
        stats=stats,
        top_parcels=top_parcels,
        projects=projects,
    )


@app.route("/map")
def map_view():
    """Full-screen Folium map embedded in a minimal wrapper."""
    return render_template("map.html")


@app.route("/output/demo_map.html")
def serve_map_file():
    """Serve the generated Folium HTML directly."""
    return send_from_directory(str(OUTPUT_DIR), "demo_map.html")


@app.route("/api/stats")
def api_stats():
    pc = _state.get("priority_counts", {})
    return jsonify({
        "total_projects":  len(_state.get("projects_gdf", [])),
        "total_parcels":   _state.get("total_parcels", 0),
        "priority": {
            "CRITICAL": pc.get("CRITICAL", 0),
            "HIGH":     pc.get("HIGH",     0),
            "MEDIUM":   pc.get("MEDIUM",   0),
            "LOW":      pc.get("LOW",      0),
        },
        "for_sale_high_priority": _state.get("for_sale_high", 0),
        "rtos_covered": ["MISO", "PJM", "ERCOT", "CAISO", "SPP", "NYISO", "ISO-NE"],
    })


@app.route("/api/projects")
def api_projects():
    if "projects_gdf" not in _state:
        return jsonify([])
    return jsonify(_project_geojson(_state["projects_gdf"]))


@app.route("/api/parcels/top")
def api_parcels_top():
    scored = _state.get("scored_gdf", gpd.GeoDataFrame())
    if scored.empty:
        return jsonify([])
    return jsonify(_scored_to_records(scored.nlargest(50, "total_score"), limit=50))


@app.route("/api/parcels/for-sale")
def api_parcels_for_sale():
    scored = _state.get("scored_gdf", gpd.GeoDataFrame())
    if scored.empty:
        return jsonify([])
    fs = scored[
        scored["for_sale"].astype(bool)
        & scored["priority"].isin(["CRITICAL", "HIGH"])
    ].nlargest(50, "total_score")
    return jsonify(_scored_to_records(fs))


@app.route("/api/refresh")
def api_refresh():
    """Re-run the full pipeline and return updated stats."""
    _run_pipeline()
    pc = _state.get("priority_counts", {})
    return jsonify({
        "status":          "ok",
        "total_parcels":   _state.get("total_parcels", 0),
        "priority":        pc,
        "for_sale_high":   _state.get("for_sale_high", 0),
    })


# ── startup ────────────────────────────────────────────────────────────────
# Run pipeline in a background thread so Flask can start immediately and
# respond to Render's health checks before the heavy analysis finishes.
def _pipeline_thread():
    global _pipeline_error
    try:
        _run_pipeline()
    except Exception as exc:  # noqa: BLE001
        _pipeline_error = str(exc)
        logger.exception("Pipeline failed: %s", exc)


threading.Thread(target=_pipeline_thread, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print()
    print("  ╔════════════════════════════════════════════╗")
    print("  ║  Transmission Land Parcel System  ·  Flask ║")
    print("  ╚════════════════════════════════════════════╝")
    print()
    print(f"  Dashboard  → http://localhost:{port}")
    print(f"  Map        → http://localhost:{port}/map")
    print(f"  API stats  → http://localhost:{port}/api/stats")
    print()
    app.run(host="0.0.0.0", port=port, debug=False)
