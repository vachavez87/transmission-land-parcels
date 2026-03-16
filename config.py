"""
config.py — Central configuration for the Transmission Land Parcel System.
All tunable parameters, API endpoints, and scoring weights live here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/transmission_db"
)

# ---------------------------------------------------------------------------
# Corridor / ROW parameters
# ---------------------------------------------------------------------------
# Half-width of transmission corridor buffer (feet).
# Typical high-voltage ROW widths:
#   500kV AC : 150–200 ft each side → 300–400 ft total
#   345kV AC : 100–150 ft each side → 200–300 ft total
#   230kV AC :  75–100 ft each side → 150–200 ft total
CORRIDOR_BUFFER_FEET = 300

# Outer search band for parcels that may be needed for routing alternatives
SEARCH_BAND_MILES = 5.0

# CRS used for metric buffering / distance calculations
ANALYSIS_CRS = "EPSG:5070"   # USA Contiguous Albers Equal Area (meters)
STORAGE_CRS  = "EPSG:4326"   # WGS84 (lon/lat degrees)

# ---------------------------------------------------------------------------
# Scoring weights  (must sum to 100)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "corridor_intersection": 35,   # Parcel overlaps buffered corridor
    "distance_to_line":      25,   # Closeness to transmission centerline
    "land_use":              15,   # Land-use type suitability
    "parcel_size":           10,   # Larger = easier ROW negotiation
    "sale_status":           15,   # Currently for sale = opportunity
}

# Distance breakpoints (miles) → points awarded
DISTANCE_SCORE_TABLE = [
    (0.10, 25),
    (0.25, 22),
    (0.50, 18),
    (1.00, 12),
    (2.00,  6),
    (5.00,  2),
    (float("inf"), 0),
]

# Land-use scores (from SCORE_WEIGHTS["land_use"] max)
LAND_USE_SCORES = {
    "Agricultural":        15,
    "Pasture/Range":       13,
    "Undeveloped":         12,
    "Woodland":            10,
    "Residential - Rural":  5,
    "Commercial":           2,
    "Industrial":           2,
}

# Parcel size breakpoints (acres) → points
PARCEL_SIZE_SCORE_TABLE = [
    (640, 10),   # > 640 acres (full square mile)
    (160, 8),
    (80,  6),
    (40,  4),
    (10,  2),
    (0,   1),
]

# Priority tier thresholds
PRIORITY_TIERS = {
    "CRITICAL": 80,
    "HIGH":     60,
    "MEDIUM":   40,
    "LOW":       0,
}

# ---------------------------------------------------------------------------
# RTO / ISO scraper endpoints
# ---------------------------------------------------------------------------
RTO_SOURCES = {
    "MISO": {
        "name": "Midcontinent ISO",
        "projects_url": "https://www.misoenergy.org/planning/transmission-planning/",
        "queue_url":    "https://www.misoenergy.org/planning/generator-interconnection/GI_Queue/",
        "region": "Midwest (15 states + Manitoba)",
    },
    "PJM": {
        "name": "PJM Interconnection",
        "projects_url": "https://www.pjm.com/planning/transmission-expansion",
        "rtep_url":     "https://www.pjm.com/planning/rtep-process",
        "region": "Mid-Atlantic & parts of Midwest (13 states + DC)",
    },
    "ERCOT": {
        "name": "Electric Reliability Council of Texas",
        "projects_url": "https://www.ercot.com/gridinfo/transmission",
        "cdr_url":      "https://www.ercot.com/gridinfo/resource",
        "region": "Texas (90% of state)",
    },
    "CAISO": {
        "name": "California ISO",
        "projects_url": "https://www.caiso.com/planning/Pages/TransmissionPlanning/default.aspx",
        "region": "California",
    },
    "SPP": {
        "name": "Southwest Power Pool",
        "projects_url": "https://www.spp.org/engineering/transmission-planning/",
        "region": "Great Plains (14 states)",
    },
    "NYISO": {
        "name": "New York ISO",
        "projects_url": "https://www.nyiso.com/transmission-planning",
        "region": "New York",
    },
    "ISONE": {
        "name": "ISO New England",
        "projects_url": "https://www.iso-ne.com/system-planning/transmission-planning",
        "region": "New England (6 states)",
    },
}

# ---------------------------------------------------------------------------
# Parcel data sources
# ---------------------------------------------------------------------------
PARCEL_SOURCES = {
    "regrid": {
        "name": "REGRID",
        "api_base": "https://app.regrid.com/api/v2",
        "api_key": os.getenv("REGRID_API_KEY", ""),
        "description": "National parcel database — best coverage",
    },
    "eia860": {
        "name": "EIA Form 860",
        "url": "https://www.eia.gov/electricity/data/eia860/",
        "description": "Existing transmission & generation assets",
    },
    "hifld": {
        "name": "HIFLD (Homeland Infrastructure Foundation-Level Data)",
        "url": "https://hifld-geoplatform.opendata.arcgis.com/",
        "description": "Electric transmission lines shapefile",
    },
}

# ---------------------------------------------------------------------------
# Agent / scheduler settings
# ---------------------------------------------------------------------------
WEEKLY_SCAN_DAY  = "monday"     # schedule.every().monday
WEEKLY_SCAN_TIME = "06:00"      # 6 AM local time
ALERT_ON_NEW_PROJECTS    = True
ALERT_ON_NEW_FOR_SALE    = True
ALERT_MIN_SCORE_THRESHOLD = 60  # Only alert on HIGH+ priority parcels

# ---------------------------------------------------------------------------
# Demo / dev settings
# ---------------------------------------------------------------------------
DEMO_MODE = not bool(os.getenv("DATABASE_URL", "").startswith("postgresql"))
SAMPLE_PARCELS_PER_PROJECT = 150
