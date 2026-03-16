"""
database/db_manager.py
SQLAlchemy + psycopg2 manager for the PostGIS transmission database.

In DEMO mode (no DATABASE_URL pointing to a real Postgres instance),
all methods print the SQL that *would* run, demonstrating PostGIS knowledge
without requiring a live database connection.
"""
import logging
import textwrap
from typing import Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages all database interactions for the transmission land parcel system.

    Supports both LIVE mode (real PostGIS connection) and DEMO mode
    (prints SQL examples to illustrate PostGIS proficiency).

    Usage — Live mode
    -----------------
    >>> from sqlalchemy import create_engine
    >>> db = DatabaseManager(database_url="postgresql://user:pass@host/db")
    >>> db.connect()
    >>> db.upsert_projects(projects_gdf)
    >>> db.upsert_parcels(parcels_gdf)
    >>> db.save_scores(scored_gdf, scan_run_id=1)
    >>> top_parcels = db.query_high_priority_for_sale(min_score=60)

    Usage — Demo mode
    -----------------
    >>> db = DatabaseManager()   # no DATABASE_URL → auto demo mode
    >>> db.demo_mode()
    """

    def __init__(self, database_url: Optional[str] = None):
        import config
        self.database_url = database_url or config.DATABASE_URL
        self._engine      = None
        self._is_demo     = not self.database_url.startswith("postgresql://user:")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        """Create SQLAlchemy engine (live mode only)."""
        if self._is_demo:
            raise RuntimeError("connect() called in demo mode — no real DB configured")

        from sqlalchemy import create_engine
        self._engine = create_engine(self.database_url, pool_pre_ping=True)
        logger.info("Connected to PostGIS database.")

    def disconnect(self):
        if self._engine:
            self._engine.dispose()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_projects(self, projects_gdf: gpd.GeoDataFrame) -> int:
        """
        Upsert transmission projects + geometries (ON CONFLICT DO UPDATE).
        Returns number of rows upserted.
        """
        if self._is_demo:
            raise RuntimeError("Live DB not configured")

        with self._engine.begin() as conn:
            # Write attribute table
            attr_df = projects_gdf.drop(columns="geometry").copy()
            attr_df.to_sql(
                "transmission_projects", conn,
                if_exists="replace", index=False, method="multi",
            )
            # Write geometries via geopandas (uses psycopg2 + PostGIS)
            projects_gdf.to_postgis(
                "transmission_lines", conn,
                if_exists="append", index=False,
            )
        return len(projects_gdf)

    def upsert_parcels(self, parcels_gdf: gpd.GeoDataFrame) -> int:
        """Upsert land parcels with PostGIS geometry."""
        if self._is_demo:
            raise RuntimeError("Live DB not configured")

        with self._engine.begin() as conn:
            parcels_gdf.to_postgis(
                "parcels", conn,
                if_exists="append", index=False, chunksize=500,
            )
        return len(parcels_gdf)

    def save_scores(
        self,
        scored_gdf: gpd.GeoDataFrame,
        scan_run_id: int,
    ) -> int:
        """Save scored parcel results for a scan run."""
        if self._is_demo:
            raise RuntimeError("Live DB not configured")

        score_cols = [
            "parcel_id", "corridor_project", "in_corridor",
            "intersection_pct", "dist_to_line_miles",
            "corridor_score", "distance_score", "land_use_score",
            "size_score", "sale_score", "total_score", "priority",
        ]
        df = scored_gdf[[c for c in score_cols if c in scored_gdf.columns]].copy()
        df["scan_run_id"] = scan_run_id

        with self._engine.begin() as conn:
            df.to_sql(
                "parcel_scores", conn,
                if_exists="append", index=False, method="multi",
            )
        return len(df)

    # ------------------------------------------------------------------
    # Read operations (raw PostGIS SQL)
    # ------------------------------------------------------------------

    def query_high_priority_for_sale(self, min_score: float = 60) -> pd.DataFrame:
        """
        Return high-priority parcels currently for sale using the
        v_high_priority_for_sale PostGIS view.
        """
        if self._is_demo:
            raise RuntimeError("Live DB not configured")

        sql = """
            SELECT parcel_id, owner, county, state, land_use, acreage,
                   asking_price_usd, total_score, priority, dist_to_line_miles
            FROM   v_high_priority_for_sale
            WHERE  total_score >= %(min_score)s
            ORDER  BY total_score DESC
            LIMIT  100
        """
        with self._engine.connect() as conn:
            return pd.read_sql(sql, conn, params={"min_score": min_score})

    def query_parcels_in_corridor(self, project_id: str) -> gpd.GeoDataFrame:
        """
        Use ST_Intersects to find all parcels within a project's corridor.
        Returns parcel GeoDataFrame.
        """
        if self._is_demo:
            raise RuntimeError("Live DB not configured")

        sql = """
            SELECT p.parcel_id, p.owner, p.county, p.state,
                   p.land_use, p.acreage, p.for_sale,
                   ROUND((
                       ST_Area(ST_Intersection(p.geom, c.geom)::geography)
                       / ST_Area(p.geom::geography)
                   ) * 100, 1) AS intersection_pct,
                   p.geom
            FROM   parcels p
            JOIN   corridors c ON ST_Intersects(p.geom, c.geom)
            WHERE  c.project_id = %(project_id)s
        """
        with self._engine.connect() as conn:
            return gpd.read_postgis(
                sql, conn, geom_col="geom",
                params={"project_id": project_id},
            )

    def query_parcels_within_miles(
        self,
        project_id: str,
        radius_miles: float = 1.0,
    ) -> gpd.GeoDataFrame:
        """
        ST_DWithin (geography) — distance search in miles around a line.
        """
        if self._is_demo:
            raise RuntimeError("Live DB not configured")

        radius_m = radius_miles * 1_609.34
        sql = """
            SELECT  p.parcel_id, p.owner, p.county, p.state,
                    p.land_use, p.acreage, p.for_sale,
                    ROUND(
                        ST_Distance(p.geom::geography, tl.geom::geography) / 1609.34,
                        3
                    ) AS dist_to_line_miles,
                    p.geom
            FROM    parcels p
            JOIN    transmission_lines tl ON tl.project_id = %(project_id)s
            WHERE   ST_DWithin(
                        p.geom::geography,
                        tl.geom::geography,
                        %(radius_m)s
                    )
            ORDER   BY dist_to_line_miles
        """
        with self._engine.connect() as conn:
            return gpd.read_postgis(
                sql, conn, geom_col="geom",
                params={"project_id": project_id, "radius_m": radius_m},
            )

    # ------------------------------------------------------------------
    # Demo mode — print SQL examples without a live DB
    # ------------------------------------------------------------------

    def demo_mode(self) -> None:
        """Print PostGIS schema excerpts and query examples."""
        print()
        print("  PostGIS database schema (excerpt):")
        print("  " + "─" * 56)
        ddl = textwrap.dedent("""
          CREATE TABLE parcels (
            parcel_id  TEXT PRIMARY KEY,
            owner      TEXT,
            land_use   TEXT,
            acreage    NUMERIC(12,2),
            for_sale   BOOLEAN,
            geom       GEOMETRY(Polygon, 4326)   ← PostGIS geometry
          );
          CREATE INDEX idx_parcels_geom ON parcels USING GIST(geom);
        """).strip()
        for line in ddl.split("\n"):
            print("  " + line)

        print()
        print("  Sample PostGIS spatial queries:")
        print("  " + "─" * 56)

        queries = [
            (
                "ST_Intersects — parcels inside corridor",
                """
                SELECT p.parcel_id, p.owner, p.acreage
                FROM   parcels p
                JOIN   corridors c ON ST_Intersects(p.geom, c.geom)
                WHERE  c.project_id = 'MISO-2024-001';
                """,
            ),
            (
                "ST_DWithin — parcels within 1 mile of centerline",
                """
                SELECT p.parcel_id,
                       ST_Distance(p.geom::geography,
                                   tl.geom::geography) / 1609.34 AS dist_mi
                FROM   parcels p
                JOIN   transmission_lines tl USING (project_id)
                WHERE  ST_DWithin(p.geom::geography,
                                  tl.geom::geography, 1609.34);
                """,
            ),
            (
                "ST_Area + ST_Intersection — intersection percentage",
                """
                SELECT p.parcel_id,
                  ROUND(ST_Area(ST_Intersection(p.geom, c.geom)::geography)
                      / ST_Area(p.geom::geography) * 100, 1) AS pct_in_corridor
                FROM parcels p
                JOIN corridors c ON ST_Intersects(p.geom, c.geom);
                """,
            ),
        ]

        for title, sql in queries:
            print(f"\n  [{title}]")
            for line in textwrap.dedent(sql).strip().split("\n"):
                print("  " + line)

        print(
            "\n  (Connect a real PostGIS instance via DATABASE_URL in .env "
            "to run live queries)"
        )


# ------------------------------------------------------------------
# Module-level __init__ files
# ------------------------------------------------------------------
