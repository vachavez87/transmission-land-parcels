# ⚡ Transmission Land Parcel Identification System

> Automated pipeline to identify, score, and monitor land parcels likely needed for high-voltage transmission line right-of-way (ROW) acquisition across the United States.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat&logo=python&logoColor=white)
![GeoPandas](https://img.shields.io/badge/GeoPandas-0.14%2B-139C5A?style=flat&logo=pandas&logoColor=white)
![PostGIS](https://img.shields.io/badge/PostGIS-enabled-336791?style=flat&logo=postgresql&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-000000?style=flat&logo=flask&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat)

---

## Overview

This system collects planned high-voltage transmission line projects from all seven US RTOs/ISOs, maps their Right-of-Way corridors, overlays parcel boundaries, checks what is for sale, and scores each parcel on a **0–100 acquisition-likelihood scale**. A weekly agent re-runs the pipeline automatically and alerts on new listings and priority upgrades.

**Live demo:** `python server.py` → open `http://localhost:5000`

---

## Skills Demonstrated

| Skill | Implementation |
|-------|---------------|
| **Python** | Flask server, pipeline orchestration, scoring engine, weekly agent (`schedule`) |
| **GeoPandas** | EPSG:5070 corridor buffering, `sjoin`, centroid distance, intersection % |
| **PostGIS** | `ST_Intersects`, `ST_DWithin`, `ST_Buffer`, `ST_Area`, GIST indexes, spatial views |
| **Web Scraping** | 7 RTO/ISO scrapers + REGRID API + Land.com/LandWatch listing scrapers |
| **Energy Data** | RTO project queues, FERC filings, EIA-860, HIFLD grid topology |
| **Real Estate Data** | Parcel ownership, assessed value, for-sale listings, county GIS portals |

---

## Architecture

```
┌──────────────────────┐     ┌───────────────────────┐     ┌──────────────────────┐
│   Web Scrapers       │────▶│  Corridor Mapper       │────▶│   Parcel Scorer      │
│  MISO / PJM / ERCOT  │     │  (GeoPandas + Shapely) │     │  Multi-factor 0-100  │
│  CAISO / SPP / NYISO │     │  Buffer → ROW polygon  │     │  corridor + dist +   │
│  ISO-NE + REGRID API │     │  EPSG:5070 projection  │     │  land use + size +   │
│  Land.com / LandWatch│     │  300 ft each side      │     │  sale status         │
└──────────────────────┘     └───────────────────────┘     └──────────────────────┘
          │                             │                              │
          ▼                             ▼                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              PostGIS Database                                   │
│  transmission_projects | transmission_lines | corridors | parcels | parcel_scores│
│  Spatial indexes (GIST) · ST_Buffer · ST_Intersects · ST_Distance · ST_Within   │
└─────────────────────────────────────────────────────────────────────────────────┘
          │                                        │
          ▼                                        ▼
┌──────────────────────┐              ┌───────────────────────┐
│   Weekly Agent       │              │  Flask + Folium        │
│  (schedule library)  │              │  Dashboard + REST API  │
│  New projects/parcels│              │  Interactive HTML map  │
│  Alert generation    │              │  Layer control/popups  │
└──────────────────────┘              └───────────────────────┘
```

---

## Scoring Algorithm

Each parcel receives a **0–100 score** across five weighted factors:

| Factor | Max Points | Description |
|--------|:----------:|-------------|
| Corridor Intersection | **35** | Does the parcel overlap the buffered ROW polygon? Sliding scale by overlap % |
| Distance to Centerline | **25** | Parcel centroid proximity to the transmission line (table lookup) |
| Land Use Type | **15** | Agricultural / pasture preferred — easier easement negotiation |
| Sale / Market Status | **15** | Currently listed for sale = immediate acquisition opportunity |
| Parcel Size | **10** | Larger parcels yield more efficient ROW agreements |

**Priority Tiers**

| Tier | Score Range | Meaning |
|------|:-----------:|---------|
| 🔴 CRITICAL | 80 – 100 | Almost certainly required for ROW |
| 🟠 HIGH | 60 – 79 | Very likely in the corridor path |
| 🟡 MEDIUM | 40 – 59 | May be needed — monitor closely |
| 🟢 LOW | 0 – 39 | Unlikely to be acquired |

---

## Project Structure

```
transmission-land-parcels/
│
├── server.py                        Flask web server + REST API
├── main.py                          CLI demo — runs full pipeline
├── config.py                        Scoring weights, corridor params, RTO URLs
├── requirements.txt
├── .env.example
│
├── data/
│   └── generate_sample_data.py      Synthetic transmission + parcel GeoJSON
│
├── scrapers/
│   ├── base_scraper.py              Base class: session mgmt, rate limiting, UA rotation
│   ├── rto_scraper.py               MISO, PJM, ERCOT, CAISO, SPP, NYISO, ISO-NE scrapers
│   └── parcel_scraper.py            REGRID API, county GIS (ArcGIS REST), Land.com
│
├── analysis/
│   ├── corridor_mapper.py           Buffer → ROW corridor polygons (EPSG:5070)
│   ├── parcel_overlay.py            sjoin + distance + intersection %
│   └── scorer.py                    Multi-factor 0–100 scoring engine
│
├── database/
│   ├── schema.sql                   PostGIS schema, GIST indexes, spatial views
│   └── db_manager.py                SQLAlchemy + psycopg2 spatial operations
│
├── agent/
│   └── weekly_updater.py            Automated weekly scan + diff + alert agent
│
├── visualization/
│   └── map_renderer.py              Folium interactive map with layer control
│
├── templates/
│   ├── dashboard.html               Dark-themed dashboard UI
│   └── map.html                     Full-screen map page
│
└── output/
    └── demo_map.html                Generated interactive map (auto-created)
```

---

## Quick Start

### Demo Mode (no database required)

```bash
git clone https://github.com/your-username/transmission-land-parcels.git
cd transmission-land-parcels

pip install -r requirements.txt

# Option A — web server + dashboard
python server.py
# open http://localhost:5000

# Option B — CLI output only
python main.py
# open output/demo_map.html
```

### Full Mode (with PostGIS)

```bash
# 1. Create PostGIS database
createdb transmission_db
psql transmission_db -c "CREATE EXTENSION postgis;"
psql transmission_db -f database/schema.sql

# 2. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, REGRID_API_KEY, etc.

# 3. Run
python server.py
```

---

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/` | Dashboard UI |
| `GET` | `/map` | Full-screen interactive map |
| `GET` | `/api/stats` | Summary statistics (JSON) |
| `GET` | `/api/projects` | All transmission projects (GeoJSON) |
| `GET` | `/api/parcels/top` | Top 50 scored parcels (JSON) |
| `GET` | `/api/parcels/for-sale` | High-priority for-sale parcels (JSON) |
| `GET` | `/api/refresh` | Re-run pipeline and return updated stats |

**Example — `/api/stats`**

```json
{
  "total_projects": 3,
  "total_parcels": 450,
  "priority": { "CRITICAL": 0, "HIGH": 23, "MEDIUM": 55, "LOW": 372 },
  "for_sale_high_priority": 7,
  "rtos_covered": ["MISO", "PJM", "ERCOT", "CAISO", "SPP", "NYISO", "ISO-NE"]
}
```

---

## Data Sources

| Data Type | Source | Method |
|-----------|--------|--------|
| Transmission project queue | MISO, PJM, ERCOT, CAISO, SPP, NYISO, ISO-NE portals | Web scraping |
| Parcel boundaries | REGRID API, county GIS portals (ArcGIS REST) | REST API + scraping |
| For-sale listings | Land.com, LandWatch | Web scraping |
| Grid topology | EIA-860, HIFLD Open Data | API download |
| Permitting status | FERC eLibrary, state PUC filings | Web scraping |

---

## RTOs / ISOs Covered

| RTO/ISO | Region | Scraper Class |
|---------|--------|---------------|
| MISO | Midwest (15 states + Manitoba) | `MISOScraper` |
| PJM | Mid-Atlantic & parts of Midwest | `PJMScraper` |
| ERCOT | Texas (90% of state) | `ERCOTScraper` |
| CAISO | California | `CAISOScraper` |
| SPP | Great Plains (14 states) | `SPPScraper` |
| NYISO | New York | `NYISOScraper` |
| ISO-NE | New England (6 states) | `ISONEScraper` |

---

## PostGIS Query Examples

```sql
-- Parcels directly inside the ROW corridor
SELECT p.parcel_id, p.owner, p.acreage
FROM   parcels p
JOIN   corridors c ON ST_Intersects(p.geom, c.geom)
WHERE  c.project_id = 'MISO-2024-001';

-- Parcels within 1 mile of a centerline
SELECT p.parcel_id,
       ST_Distance(p.geom::geography, tl.geom::geography) / 1609.34 AS dist_mi
FROM   parcels p
JOIN   transmission_lines tl ON tl.project_id = 'MISO-2024-001'
WHERE  ST_DWithin(p.geom::geography, tl.geom::geography, 1609.34);

-- Intersection percentage per parcel
SELECT p.parcel_id,
       ROUND(
           ST_Area(ST_Intersection(p.geom, c.geom)::geography)
           / ST_Area(p.geom::geography) * 100, 1
       ) AS pct_in_corridor
FROM   parcels p
JOIN   corridors c ON ST_Intersects(p.geom, c.geom);
```

---

## Weekly Agent

The `TransmissionLandAgent` runs automatically every Monday at 06:00 and:

1. Re-scrapes all 7 RTO/ISO portals for new or updated projects
2. Re-runs corridor mapping and parcel scoring
3. Diffs results against the prior week's snapshot
4. Generates alerts for new projects, new for-sale listings, and priority upgrades
5. Persists results to PostGIS and sends email notifications

```python
from agent.weekly_updater import TransmissionLandAgent

agent = TransmissionLandAgent()
agent.start_scheduler()   # blocks; runs every Monday 06:00
```

---

## Requirements

```
Python 3.10+
flask>=3.0
geopandas>=0.14
shapely>=2.0
folium>=0.15
sqlalchemy>=2.0        # PostGIS live mode
psycopg2-binary        # PostGIS live mode
requests
beautifulsoup4
lxml
schedule
python-dotenv
```

```bash
pip install -r requirements.txt
```

---

## License

MIT — free to use and modify.
