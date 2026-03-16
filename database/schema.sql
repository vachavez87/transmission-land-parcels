-- database/schema.sql
-- PostGIS schema for the Transmission Land Parcel Identification System
-- Apply with: psql transmission_db -f database/schema.sql

-- ===========================================================================
-- Extensions
-- ===========================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ===========================================================================
-- Tables
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Transmission projects (one row per planned line project)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transmission_projects (
    project_id          TEXT        PRIMARY KEY,
    name                TEXT        NOT NULL,
    rto                 TEXT        NOT NULL,          -- MISO | PJM | ERCOT | …
    voltage_kv          INTEGER,
    line_type           TEXT        DEFAULT 'AC',       -- AC | DC | HVDC
    status              TEXT,
    length_miles        NUMERIC(8,2),
    estimated_cost_m    NUMERIC(10,2),                 -- millions USD
    expected_cod        TEXT,                          -- e.g. "2027-Q3"
    states              TEXT,                          -- comma-separated abbrevs
    source_url          TEXT,
    scraped_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Transmission line geometries (PostGIS LineString, WGS84)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transmission_lines (
    id              SERIAL      PRIMARY KEY,
    project_id      TEXT        NOT NULL REFERENCES transmission_projects(project_id)
                                ON DELETE CASCADE,
    geom            GEOMETRY(LineString, 4326) NOT NULL,
    segment_order   INTEGER     DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_transmission_lines_geom
    ON transmission_lines USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_transmission_lines_project
    ON transmission_lines(project_id);

-- ---------------------------------------------------------------------------
-- Corridor polygons (buffered ROW areas)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corridors (
    id                  SERIAL      PRIMARY KEY,
    project_id          TEXT        NOT NULL REFERENCES transmission_projects(project_id)
                                    ON DELETE CASCADE,
    buffer_feet         INTEGER     NOT NULL DEFAULT 300,
    total_width_ft      INTEGER     GENERATED ALWAYS AS (buffer_feet * 2) STORED,
    corridor_area_sqmi  NUMERIC(10,4),
    geom                GEOMETRY(Polygon, 4326) NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_corridors_geom
    ON corridors USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_corridors_project
    ON corridors(project_id);

-- ---------------------------------------------------------------------------
-- Land parcels (from REGRID / county GIS sources)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parcels (
    parcel_id           TEXT        PRIMARY KEY,
    owner               TEXT,
    owner_type          TEXT,
    county              TEXT,
    state               CHAR(2),
    land_use            TEXT,
    acreage             NUMERIC(12,2),
    for_sale            BOOLEAN     DEFAULT FALSE,
    asking_price_usd    BIGINT,
    assessed_value_usd  BIGINT,
    geom                GEOMETRY(Polygon, 4326) NOT NULL,
    data_source         TEXT,
    last_checked        DATE,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parcels_geom
    ON parcels USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_parcels_state_county
    ON parcels(state, county);

CREATE INDEX IF NOT EXISTS idx_parcels_for_sale
    ON parcels(for_sale) WHERE for_sale = TRUE;

-- ---------------------------------------------------------------------------
-- Parcel scores (one row per parcel per scan run)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parcel_scores (
    id                  SERIAL      PRIMARY KEY,
    scan_run_id         INTEGER,                       -- FK → scan_runs
    parcel_id           TEXT        NOT NULL REFERENCES parcels(parcel_id)
                                    ON DELETE CASCADE,
    corridor_project_id TEXT,
    in_corridor         BOOLEAN     DEFAULT FALSE,
    intersection_pct    NUMERIC(5,1),
    dist_to_line_miles  NUMERIC(8,3),
    corridor_score      NUMERIC(5,1),
    distance_score      NUMERIC(5,1),
    land_use_score      NUMERIC(5,1),
    size_score          NUMERIC(5,1),
    sale_score          NUMERIC(5,1),
    total_score         NUMERIC(5,1),
    priority            TEXT        CHECK (priority IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    scored_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parcel_scores_total
    ON parcel_scores(total_score DESC);

CREATE INDEX IF NOT EXISTS idx_parcel_scores_priority
    ON parcel_scores(priority);

CREATE INDEX IF NOT EXISTS idx_parcel_scores_run
    ON parcel_scores(scan_run_id);

-- ---------------------------------------------------------------------------
-- Scan run log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scan_runs (
    id                  SERIAL      PRIMARY KEY,
    run_type            TEXT        DEFAULT 'weekly',  -- weekly | manual | initial
    projects_scraped    INTEGER,
    parcels_analyzed    INTEGER,
    new_for_sale        INTEGER,
    new_projects        INTEGER,
    run_started_at      TIMESTAMPTZ DEFAULT now(),
    run_completed_at    TIMESTAMPTZ,
    status              TEXT        DEFAULT 'in_progress',
    notes               TEXT
);

-- ===========================================================================
-- Views
-- ===========================================================================

-- High-priority parcels currently for sale
CREATE OR REPLACE VIEW v_high_priority_for_sale AS
SELECT
    p.parcel_id,
    p.owner,
    p.county,
    p.state,
    p.land_use,
    p.acreage,
    p.asking_price_usd,
    ps.total_score,
    ps.priority,
    ps.dist_to_line_miles,
    ps.corridor_project_id,
    p.geom
FROM parcels p
JOIN (
    -- Most recent score per parcel
    SELECT DISTINCT ON (parcel_id)
        parcel_id, total_score, priority,
        dist_to_line_miles, corridor_project_id
    FROM parcel_scores
    ORDER BY parcel_id, scored_at DESC
) ps ON ps.parcel_id = p.parcel_id
WHERE p.for_sale = TRUE
  AND ps.priority IN ('CRITICAL', 'HIGH')
ORDER BY ps.total_score DESC;

-- Corridor coverage summary per project
CREATE OR REPLACE VIEW v_corridor_summary AS
SELECT
    tp.project_id,
    tp.name,
    tp.rto,
    tp.voltage_kv,
    tp.status,
    tp.expected_cod,
    tp.estimated_cost_m,
    COUNT(DISTINCT pa.parcel_id)                           AS total_parcels_in_corridor,
    COUNT(DISTINCT pa.parcel_id) FILTER (WHERE pa.for_sale)AS for_sale_in_corridor,
    SUM(pa.acreage)                                        AS total_acres_in_corridor,
    MAX(ps.scored_at)                                      AS last_scored
FROM transmission_projects tp
LEFT JOIN corridors c       ON c.project_id = tp.project_id
LEFT JOIN parcels   pa      ON ST_Intersects(pa.geom, c.geom)
LEFT JOIN (
    SELECT DISTINCT ON (parcel_id)
        parcel_id, priority, scored_at
    FROM parcel_scores ORDER BY parcel_id, scored_at DESC
) ps ON ps.parcel_id = pa.parcel_id
GROUP BY tp.project_id, tp.name, tp.rto, tp.voltage_kv,
         tp.status, tp.expected_cod, tp.estimated_cost_m;

-- ===========================================================================
-- Useful spatial query examples (for documentation / DB manager use)
-- ===========================================================================

-- Find all parcels within 1 mile of a given project's centerline:
--   SELECT p.*
--   FROM parcels p
--   JOIN transmission_lines tl ON tl.project_id = 'MISO-2024-001'
--   WHERE ST_DWithin(
--       p.geom::geography,
--       tl.geom::geography,
--       1609.34   -- 1 mile in meters
--   );

-- Parcels overlapping a corridor, with % intersection:
--   SELECT p.parcel_id, p.owner,
--       ROUND((ST_Area(ST_Intersection(p.geom, c.geom)::geography)
--            / ST_Area(p.geom::geography)) * 100, 1) AS intersection_pct
--   FROM parcels p
--   JOIN corridors c ON ST_Intersects(p.geom, c.geom)
--   WHERE c.project_id = 'MISO-2024-001';
