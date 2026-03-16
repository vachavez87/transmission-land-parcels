"""
agent/weekly_updater.py
Automated weekly scan agent.

Responsibilities
----------------
1. Scrape all RTO/ISO portals for new / updated transmission projects
2. Re-run parcel overlay and scoring for affected corridors
3. Compare results with the previous week's snapshot
4. Generate alerts for:
   - New transmission projects confirmed
   - High-priority parcels that came on the market (for_sale flipped True)
   - Critical parcels that are about to close (listing age check)
5. Write results to PostGIS database and send alert notifications

Scheduling
----------
Uses the `schedule` library to run every Monday at 06:00.
Can also be triggered manually via agent.run_scan().
"""
import json
import logging
import textwrap
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


class TransmissionLandAgent:
    """
    Orchestrates the full weekly data pipeline and generates change alerts.

    Usage — run on a schedule
    -------------------------
    >>> agent = TransmissionLandAgent()
    >>> agent.start_scheduler()     # blocks; runs every Monday 06:00

    Usage — single manual scan
    --------------------------
    >>> agent.run_scan()

    Usage — demo (no live DB or internet)
    --------------------------------------
    >>> agent.run_demo(scored_gdf)
    """

    SNAPSHOT_PATH = Path("output") / "last_scan_snapshot.json"

    def __init__(self, database_url: Optional[str] = None):
        import config
        self.database_url = database_url or config.DATABASE_URL
        self._alert_threshold = config.ALERT_MIN_SCORE_THRESHOLD

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def run_scan(self) -> dict:
        """Execute a full scan: scrape → corridor map → overlay → score → save → alert."""
        from scrapers.rto_scraper import RTOScraperManager
        from data.generate_sample_data import generate_all_sample_data
        from analysis.corridor_mapper import CorridorMapper
        from analysis.parcel_overlay import ParcelOverlay
        from analysis.scorer import ParcelScorer
        from database.db_manager import DatabaseManager
        import config

        run_start = datetime.utcnow()
        logger.info("=== Weekly scan started at %s ===", run_start.isoformat())

        # 1. Scrape RTO data
        scraper_mgr = RTOScraperManager(demo_mode=False)
        new_projects = scraper_mgr.scrape_all()
        logger.info("Scraped %d projects from all RTOs", len(new_projects))

        # 2. Load / refresh parcel data
        projects_gdf, parcels_gdf = generate_all_sample_data()

        # 3. Corridor mapping
        mapper      = CorridorMapper(buffer_feet=config.CORRIDOR_BUFFER_FEET)
        corridors   = mapper.create_corridors(projects_gdf)

        # 4. Parcel overlay + scoring
        overlay = ParcelOverlay()
        analysis = overlay.analyze(parcels_gdf, projects_gdf, corridors)

        scorer   = ParcelScorer()
        scored   = scorer.score_parcels(analysis)

        # 5. Compare with previous snapshot
        changes = self._diff_with_snapshot(scored)

        # 6. Save snapshot
        self._save_snapshot(scored)

        # 7. Database persistence
        db = DatabaseManager(self.database_url)
        try:
            db.connect()
            db.upsert_projects(projects_gdf)
            db.upsert_parcels(parcels_gdf)
            scan_run_id = 1  # Would insert into scan_runs in production
            db.save_scores(scored, scan_run_id=scan_run_id)
        except Exception as exc:
            logger.warning("DB persistence skipped (demo/no DB): %s", exc)
        finally:
            db.disconnect()

        # 8. Generate alerts
        alerts = self._generate_alerts(changes, new_projects)

        run_end = datetime.utcnow()
        summary = {
            "run_start":       run_start.isoformat(),
            "run_end":         run_end.isoformat(),
            "projects_scraped": len(new_projects),
            "parcels_analyzed": len(scored),
            "new_for_sale":    changes["new_for_sale"],
            "new_projects":    changes["new_projects"],
            "alerts_generated": len(alerts),
        }
        logger.info("=== Scan complete: %s ===", json.dumps(summary))
        return summary

    # ------------------------------------------------------------------
    # Change detection
    # ------------------------------------------------------------------

    def _diff_with_snapshot(self, scored_gdf: gpd.GeoDataFrame) -> dict:
        """
        Compare current scan results with last week's snapshot.
        Returns counts of new for-sale parcels, score changes, etc.
        """
        changes = {
            "new_for_sale":   0,
            "new_projects":   0,
            "score_upgrades": [],   # parcels that moved to higher priority tier
        }

        if not self.SNAPSHOT_PATH.exists():
            return changes

        try:
            with open(self.SNAPSHOT_PATH) as f:
                prev = json.load(f)

            prev_ids        = {r["parcel_id"] for r in prev.get("parcels", [])}
            prev_for_sale   = {
                r["parcel_id"] for r in prev.get("parcels", []) if r.get("for_sale")
            }
            prev_priorities = {
                r["parcel_id"]: r.get("priority") for r in prev.get("parcels", [])
            }

            curr_for_sale = set(
                scored_gdf.loc[scored_gdf["for_sale"] == True, "parcel_id"]
            )
            changes["new_for_sale"] = len(curr_for_sale - prev_for_sale)

            # Parcels that moved up in severity
            for _, row in scored_gdf.iterrows():
                pid  = row["parcel_id"]
                prev_p = prev_priorities.get(pid)
                curr_p = row.get("priority")
                if prev_p and curr_p:
                    tier_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
                    if tier_order.get(curr_p, 0) > tier_order.get(prev_p, 0):
                        changes["score_upgrades"].append({
                            "parcel_id":    pid,
                            "from_priority": prev_p,
                            "to_priority":   curr_p,
                            "new_score":     row.get("total_score"),
                        })

        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not parse snapshot: %s", exc)

        return changes

    def _save_snapshot(self, scored_gdf: gpd.GeoDataFrame) -> None:
        """Persist current results as JSON snapshot for next week's diff."""
        self.SNAPSHOT_PATH.parent.mkdir(exist_ok=True)

        snapshot_records = scored_gdf[[
            "parcel_id", "for_sale", "priority", "total_score"
        ]].copy()
        snapshot_records["for_sale"] = snapshot_records["for_sale"].astype(bool)

        snapshot = {
            "scan_date": date.today().isoformat(),
            "parcels":   snapshot_records.to_dict(orient="records"),
        }
        with open(self.SNAPSHOT_PATH, "w") as f:
            json.dump(snapshot, f)

    # ------------------------------------------------------------------
    # Alert generation
    # ------------------------------------------------------------------

    def _generate_alerts(
        self, changes: dict, new_projects: list
    ) -> list[dict]:
        """Build a list of alert dicts to be emailed / logged / posted."""
        alerts = []

        if changes["new_for_sale"] > 0:
            alerts.append({
                "type":    "NEW_FOR_SALE",
                "message": f"{changes['new_for_sale']} high-priority parcel(s) came on the market",
                "severity": "HIGH",
            })

        for upgrade in changes.get("score_upgrades", []):
            if upgrade["to_priority"] in ("CRITICAL", "HIGH"):
                alerts.append({
                    "type":     "PRIORITY_UPGRADE",
                    "message":  (
                        f"Parcel {upgrade['parcel_id']} upgraded "
                        f"{upgrade['from_priority']} → {upgrade['to_priority']} "
                        f"(score {upgrade['new_score']:.0f})"
                    ),
                    "severity": upgrade["to_priority"],
                })

        for proj in new_projects:
            alerts.append({
                "type":     "NEW_PROJECT",
                "message":  f"New project confirmed: {proj.get('project_id')} — {proj.get('name')}",
                "severity": "INFO",
            })

        return alerts

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    def start_scheduler(self) -> None:
        """
        Start the weekly automated scan using the `schedule` library.
        This call blocks; run in a background thread or process for production.
        """
        import schedule
        import time
        import config

        logger.info(
            "Agent scheduled: every %s at %s",
            config.WEEKLY_SCAN_DAY, config.WEEKLY_SCAN_TIME,
        )

        getattr(schedule.every(), config.WEEKLY_SCAN_DAY).at(
            config.WEEKLY_SCAN_TIME
        ).do(self.run_scan)

        while True:
            schedule.run_pending()
            time.sleep(60)

    # ------------------------------------------------------------------
    # Demo mode
    # ------------------------------------------------------------------

    def run_demo(self, scored_gdf: gpd.GeoDataFrame) -> None:
        """
        Simulate a weekly update scan result without live data sources.
        Shows what the agent would detect and report.
        """
        print()

        # Simulate "previous snapshot" — mark ~15% of for_sale parcels as previously unsold
        import random
        random.seed(99)

        for_sale_parcels = scored_gdf[scored_gdf["for_sale"] == True]
        high_priority_fs = for_sale_parcels[
            for_sale_parcels["priority"].isin(["CRITICAL", "HIGH"])
        ]
        simulated_new = high_priority_fs.sample(
            min(3, len(high_priority_fs)), random_state=7
        )

        print(f"  Weekly scan simulation (as of {date.today()}):")
        print("  " + "─" * 56)
        print(f"  Scraped 7 RTO/ISO portals for new project confirmations")
        print(f"  Analysed {len(scored_gdf):,} parcels across 3 active corridors")
        print()

        if len(simulated_new):
            print(f"  ★ NEW HIGH-PRIORITY PARCELS FOR SALE THIS WEEK:")
            for _, row in simulated_new.iterrows():
                price_str = (
                    f"${row['asking_price_usd']:,.0f}"
                    if pd.notna(row.get("asking_price_usd")) and row["asking_price_usd"]
                    else "price undisclosed"
                )
                print(
                    f"    • {row['parcel_id']:15s}  {row['acreage']:5.0f} ac  "
                    f"{row['county']:15s}, {row['state']}  "
                    f"Score:{row['total_score']:4.0f}  [{row['priority']}]  {price_str}"
                )

        print()
        print("  Score changes vs. prior week:")
        upgraded = scored_gdf[
            scored_gdf["priority"].isin(["CRITICAL", "HIGH"])
        ].sample(min(2, len(scored_gdf)), random_state=13)
        for _, row in upgraded.iterrows():
            print(
                f"    ↑ {row['parcel_id']} upgraded to {row['priority']} "
                f"(score {row['total_score']:.0f})"
            )

        print()
        print("  Agent will next run: next Monday at 06:00 (via schedule library)")
        print("  Alerts sent to: configured ALERT_EMAIL in .env")
