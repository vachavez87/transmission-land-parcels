"""
data/generate_sample_data.py
Generates realistic synthetic transmission line projects and land parcels
for the demo. Produces two GeoJSON files:
  - sample_transmission_projects.geojson
  - sample_parcels.geojson
"""
import random
from pathlib import Path

import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, box

random.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Transmission line project definitions
# Three real-world-style projects across MISO, PJM, and ERCOT territories
# ---------------------------------------------------------------------------
TRANSMISSION_PROJECTS = [
    {
        "project_id":       "MISO-2024-001",
        "name":             "Midwest 500kV Backbone Expansion",
        "rto":              "MISO",
        "voltage_kv":       500,
        "line_type":        "AC",
        "status":           "Approved – Environmental Review",
        "length_miles":     248,
        "estimated_cost_m": 1200,
        "expected_cod":     "2027-Q3",
        "states":           "MO, IL, IN",
        "geometry": LineString([
            (-90.20, 38.62), (-89.80, 38.75), (-89.30, 38.85),
            (-88.70, 39.00), (-88.10, 39.15), (-87.60, 39.35),
            (-87.00, 39.55), (-86.90, 39.70),
        ]),
    },
    {
        "project_id":       "PJM-2024-047",
        "name":             "Ohio–Pennsylvania Grid Reliability Line",
        "rto":              "PJM",
        "voltage_kv":       345,
        "line_type":        "AC",
        "status":           "FERC Application Filed",
        "length_miles":     162,
        "estimated_cost_m": 680,
        "expected_cod":     "2027-Q1",
        "states":           "PA, OH",
        "geometry": LineString([
            (-80.00, 40.44), (-81.00, 40.30), (-81.70, 40.15),
            (-82.50, 40.00), (-83.00, 39.96),
        ]),
    },
    {
        "project_id":       "ERCOT-2024-012",
        "name":             "West Texas Renewable Export Corridor",
        "rto":              "ERCOT",
        "voltage_kv":       345,
        "line_type":        "AC",
        "status":           "Notice to Proceed Issued",
        "length_miles":     315,
        "estimated_cost_m": 890,
        "expected_cod":     "2026-Q4",
        "states":           "TX",
        "geometry": LineString([
            (-102.10, 31.90), (-101.20, 31.60), (-100.10, 31.30),
            (-99.00, 31.00), (-98.40, 30.60), (-98.30, 29.50),
        ]),
    },
]

# ---------------------------------------------------------------------------
# Reference data for parcel attribute generation
# ---------------------------------------------------------------------------
LAND_USE_TYPES = [
    ("Agricultural",        0.45),
    ("Pasture/Range",       0.20),
    ("Undeveloped",         0.12),
    ("Woodland",            0.08),
    ("Residential - Rural", 0.08),
    ("Commercial",          0.04),
    ("Industrial",          0.03),
]

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Linda",
    "Michael", "Barbara", "William", "Elizabeth", "David", "Susan",
    "Richard", "Karen", "Charles", "Nancy", "Joseph", "Betty",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Wilson", "Anderson", "Taylor", "Thomas",
    "Jackson", "White", "Harris", "Martin", "Thompson", "Moore",
]

STATE_COUNTIES = {
    "MO": ["Jefferson Co.", "Franklin Co.", "Washington Co.", "Gasconade Co.", "Maries Co."],
    "IL": ["Madison Co.", "Bond Co.", "Effingham Co.", "Clay Co.", "Lawrence Co.", "Wayne Co."],
    "IN": ["Sullivan Co.", "Vigo Co.", "Putnam Co.", "Hendricks Co.", "Owen Co."],
    "PA": ["Allegheny Co.", "Washington Co.", "Westmoreland Co.", "Fayette Co.", "Greene Co."],
    "OH": ["Columbiana Co.", "Carroll Co.", "Tuscarawas Co.", "Holmes Co.", "Wayne Co.", "Stark Co."],
    "TX": ["Midland Co.", "Tom Green Co.", "Concho Co.", "Mason Co.", "Kerr Co.", "Bexar Co."],
}


def _get_state(lon: float, rto: str) -> str:
    """Assign a US state abbreviation based on longitude and RTO."""
    if rto == "MISO":
        if lon >= -88.5:
            return "MO"
        elif lon >= -87.5:
            return "IL"
        return "IN"
    elif rto == "PJM":
        return "PA" if lon >= -81.5 else "OH"
    return "TX"


def _random_owner() -> tuple:
    """Return (owner_name, owner_type) tuple."""
    owner_type = random.choices(
        ["Individual", "Family Farm LLC", "Corporation", "Trust", "Investment LLC"],
        weights=[0.35, 0.25, 0.15, 0.15, 0.10],
    )[0]
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)

    if owner_type == "Individual":
        name = f"{fn} {ln}"
    elif owner_type == "Family Farm LLC":
        name = f"{ln} Family Farm LLC"
    elif owner_type == "Corporation":
        name = random.choice([
            "AgriLand Holdings Corp", "Heartland Agricultural Corp",
            "Prairie Land Inc", "Midwest Resources Corp", "SunBelt Ag Corp",
        ])
    elif owner_type == "Trust":
        name = f"{ln} Family Trust"
    else:
        name = f"{ln} Properties LLC"

    return name, owner_type


def _price_per_acre(land_use: str) -> float:
    ranges = {
        "Agricultural":        (2_000,  8_000),
        "Pasture/Range":       (1_500,  6_000),
        "Woodland":            (1_000,  4_000),
        "Undeveloped":         (  800,  3_500),
        "Residential - Rural": (8_000, 30_000),
        "Commercial":         (20_000, 80_000),
        "Industrial":         (10_000, 50_000),
    }
    lo, hi = ranges.get(land_use, (1_000, 5_000))
    return random.uniform(lo, hi)


def _generate_parcels_for_project(project: dict, num_parcels: int = 150) -> list:
    """
    Generate synthetic parcel polygons scattered around a transmission line.

    Strategy:
        1. Buffer the line by ~6 miles to define a search band.
        2. Randomly place rectangular parcels (varying size) within the band.
        3. Assign realistic agricultural / rural attributes.
    """
    line = project["geometry"]
    rto  = project["rto"]

    # At ~35-40°N: 1° lon ≈ 53 mi, 1° lat ≈ 69 mi
    search_buffer = 0.09   # degrees ≈ 6 miles lateral
    search_area   = line.buffer(search_buffer)
    minx, miny, maxx, maxy = search_area.bounds

    parcels  = []
    attempts = 0

    while len(parcels) < num_parcels and attempts < num_parcels * 20:
        attempts += 1

        cx = random.uniform(minx, maxx)
        cy = random.uniform(miny, maxy)

        # Parcel size categories
        size_cat = random.choices(
            ["large", "medium", "small"],
            weights=[0.15, 0.65, 0.20],
        )[0]

        if size_cat == "large":
            w = random.uniform(0.035, 0.070)
            h = random.uniform(0.025, 0.050)
        elif size_cat == "medium":
            w = random.uniform(0.015, 0.035)
            h = random.uniform(0.012, 0.025)
        else:
            w = random.uniform(0.004, 0.015)
            h = random.uniform(0.003, 0.012)

        parcel_geom = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        if not search_area.intersects(parcel_geom):
            continue

        # Approximate acreage (rough conversion at these latitudes)
        lon_factor = 53.0 + (40.0 - cy) * 0.3
        acres = round((w * lon_factor) * (h * 69.0) * 640, 1)

        state    = _get_state(cx, rto)
        county   = random.choice(STATE_COUNTIES.get(state, ["Unknown Co."]))
        land_use = random.choices(
            [lu[0] for lu in LAND_USE_TYPES],
            weights=[lu[1] for lu in LAND_USE_TYPES],
        )[0]
        owner, owner_type = _random_owner()

        for_sale = random.random() < 0.10
        ppa      = _price_per_acre(land_use)

        assessed_value = int(acres * ppa * random.uniform(0.55, 0.85))
        asking_price   = int(acres * ppa * random.uniform(0.95, 1.15)) if for_sale else None

        parcels.append({
            "parcel_id":         f"{project['project_id'][:4]}-P{len(parcels):04d}",
            "owner":             owner,
            "owner_type":        owner_type,
            "county":            county,
            "state":             state,
            "land_use":          land_use,
            "acreage":           acres,
            "for_sale":          for_sale,
            "asking_price_usd":  asking_price,
            "assessed_value_usd": assessed_value,
            "geometry":          parcel_geom,
        })

    return parcels


def generate_all_sample_data(output_dir: str = "data"):
    """
    Generate and save both sample GeoJSON files.

    Returns
    -------
    (projects_gdf, parcels_gdf) : tuple of GeoDataFrames
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # --- Transmission projects ---
    projects_gdf = gpd.GeoDataFrame(TRANSMISSION_PROJECTS, crs="EPSG:4326")
    proj_path = output_path / "sample_transmission_projects.geojson"
    projects_gdf.to_file(proj_path, driver="GeoJSON")
    print(f"    → Saved {len(projects_gdf)} transmission projects → {proj_path}")

    # --- Parcels ---
    all_parcels = []
    for project in TRANSMISSION_PROJECTS:
        parcels = _generate_parcels_for_project(project, num_parcels=150)
        all_parcels.extend(parcels)
        print(f"    → Generated {len(parcels)} parcels for {project['project_id']}")

    parcels_gdf = gpd.GeoDataFrame(all_parcels, crs="EPSG:4326")
    parcel_path = output_path / "sample_parcels.geojson"
    parcels_gdf.to_file(parcel_path, driver="GeoJSON")
    print(f"    → Saved {len(parcels_gdf)} total parcels → {parcel_path}")

    return projects_gdf, parcels_gdf


if __name__ == "__main__":
    print("Generating sample data...")
    generate_all_sample_data()
    print("Done.")
