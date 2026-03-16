"""
scrapers/rto_scraper.py
Individual scraper classes for each US RTO/ISO plus a unified manager.

Covered RTOs:
    MISO   — Midcontinent ISO (15 states + Manitoba)
    PJM    — PJM Interconnection (13 states + DC)
    ERCOT  — Electric Reliability Council of Texas
    CAISO  — California ISO
    SPP    — Southwest Power Pool
    NYISO  — New York ISO
    ISONE  — ISO New England

In LIVE mode each scraper hits the real website and parses the transmission
project / queue tables.  In DEMO mode (default) each returns realistic mock
data so the pipeline runs without an internet connection.
"""
import logging
from typing import Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


# ===========================================================================
# MISO
# ===========================================================================

class MISOScraper(BaseScraper):
    """
    Scrapes MISO's Transmission Expansion Planning (MTEP) project list.
    Source: https://www.misoenergy.org/planning/transmission-planning/
    """
    SOURCE_NAME = "MISO"
    BASE_URL    = "https://www.misoenergy.org/planning/transmission-planning/"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        # MISO publishes MTEP appendices as downloadable Excel/PDF links.
        # We look for table rows or linked documents listing project IDs.
        for row in soup.select("table.project-table tr"):
            cells = row.find_all("td")
            if len(cells) >= 5:
                projects.append({
                    "project_id":       cells[0].get_text(strip=True),
                    "name":             cells[1].get_text(strip=True),
                    "rto":              "MISO",
                    "voltage_kv":       int(cells[2].get_text(strip=True).replace("kV", "") or 0),
                    "status":           cells[3].get_text(strip=True),
                    "states":           cells[4].get_text(strip=True),
                    "expected_cod":     cells[5].get_text(strip=True) if len(cells) > 5 else "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "MISO-2024-001", "name": "Midwest 500kV Backbone Expansion",
                "rto": "MISO", "voltage_kv": 500, "status": "Approved – Environmental Review",
                "states": "MO, IL, IN", "expected_cod": "2027-Q3", "estimated_cost_m": 1200,
                "length_miles": 248,
            },
            {
                "project_id": "MISO-2024-019", "name": "Lake Erie Loop Upgrade",
                "rto": "MISO", "voltage_kv": 345, "status": "Planning Study",
                "states": "MI, OH, IN", "expected_cod": "2028-Q2", "estimated_cost_m": 540,
                "length_miles": 190,
            },
            {
                "project_id": "MISO-2025-003", "name": "Gateway South 765kV Extension",
                "rto": "MISO", "voltage_kv": 765, "status": "Conceptual",
                "states": "IL, MO, AR", "expected_cod": "2029-Q1", "estimated_cost_m": 2100,
                "length_miles": 380,
            },
        ]


# ===========================================================================
# PJM
# ===========================================================================

class PJMScraper(BaseScraper):
    """
    Scrapes PJM's Regional Transmission Expansion Plan (RTEP) project list.
    Source: https://www.pjm.com/planning/rtep-process
    """
    SOURCE_NAME = "PJM"
    BASE_URL    = "https://www.pjm.com/planning/transmission-expansion"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        for row in soup.select("div.transmission-project, tr.project-row"):
            cells = row.find_all(["td", "div"])
            if len(cells) >= 4:
                projects.append({
                    "project_id": cells[0].get_text(strip=True),
                    "name":       cells[1].get_text(strip=True),
                    "rto":        "PJM",
                    "voltage_kv": _parse_kv(cells[2].get_text(strip=True)),
                    "status":     cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "states":     "",
                    "expected_cod":     "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "PJM-2024-047", "name": "Ohio–Pennsylvania Grid Reliability Line",
                "rto": "PJM", "voltage_kv": 345, "status": "FERC Application Filed",
                "states": "PA, OH", "expected_cod": "2027-Q1", "estimated_cost_m": 680,
                "length_miles": 162,
            },
            {
                "project_id": "PJM-2024-061", "name": "Mid-Atlantic Offshore Wind Connection",
                "rto": "PJM", "voltage_kv": 500, "status": "Competitive Window Open",
                "states": "NJ, DE, MD", "expected_cod": "2028-Q3", "estimated_cost_m": 1450,
                "length_miles": 95,
            },
        ]


# ===========================================================================
# ERCOT
# ===========================================================================

class ERCOTScraper(BaseScraper):
    """
    Scrapes ERCOT's Competitive Renewable Energy Zone (CREZ) and
    Transmission Improvement Plan (TIP) tables.
    Source: https://www.ercot.com/gridinfo/transmission
    """
    SOURCE_NAME = "ERCOT"
    BASE_URL    = "https://www.ercot.com/gridinfo/transmission"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 4:
                projects.append({
                    "project_id": cells[0].get_text(strip=True),
                    "name":       cells[1].get_text(strip=True),
                    "rto":        "ERCOT",
                    "voltage_kv": _parse_kv(cells[2].get_text(strip=True)),
                    "status":     cells[3].get_text(strip=True),
                    "states":     "TX",
                    "expected_cod":     cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "ERCOT-2024-012", "name": "West Texas Renewable Export Corridor",
                "rto": "ERCOT", "voltage_kv": 345, "status": "Notice to Proceed Issued",
                "states": "TX", "expected_cod": "2026-Q4", "estimated_cost_m": 890,
                "length_miles": 315,
            },
            {
                "project_id": "ERCOT-2024-031", "name": "Panhandle Wind Collection Line",
                "rto": "ERCOT", "voltage_kv": 345, "status": "Environmental Permitting",
                "states": "TX", "expected_cod": "2027-Q2", "estimated_cost_m": 420,
                "length_miles": 210,
            },
        ]


# ===========================================================================
# CAISO
# ===========================================================================

class CAISOScraper(BaseScraper):
    """
    Scrapes CAISO's Transmission Planning Process (TPP) project list.
    Source: https://www.caiso.com/planning/Pages/TransmissionPlanning/default.aspx
    """
    SOURCE_NAME = "CAISO"
    BASE_URL    = "https://www.caiso.com/planning/Pages/TransmissionPlanning/default.aspx"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        for row in soup.select("tr.project, table.transmission-projects tr"):
            cells = row.find_all("td")
            if cells:
                projects.append({
                    "project_id": cells[0].get_text(strip=True),
                    "name":       cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    "rto":        "CAISO",
                    "voltage_kv": _parse_kv(cells[2].get_text(strip=True)) if len(cells) > 2 else 0,
                    "status":     cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "states":     "CA",
                    "expected_cod":     "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "CAISO-2024-008", "name": "Central Valley 500kV Transmission Project",
                "rto": "CAISO", "voltage_kv": 500, "status": "CPUC Certificate Pending",
                "states": "CA", "expected_cod": "2027-Q4", "estimated_cost_m": 760,
                "length_miles": 130,
            },
        ]


# ===========================================================================
# SPP
# ===========================================================================

class SPPScraper(BaseScraper):
    """
    Scrapes SPP's Integrated Transmission Planning (ITP) projects.
    Source: https://www.spp.org/engineering/transmission-planning/
    """
    SOURCE_NAME = "SPP"
    BASE_URL    = "https://www.spp.org/engineering/transmission-planning/"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 3:
                projects.append({
                    "project_id": cells[0].get_text(strip=True),
                    "name":       cells[1].get_text(strip=True),
                    "rto":        "SPP",
                    "voltage_kv": _parse_kv(cells[2].get_text(strip=True)),
                    "status":     cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "states":     "",
                    "expected_cod":     "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "SPP-2024-022", "name": "Southern Plains 345kV Collector",
                "rto": "SPP", "voltage_kv": 345, "status": "Board Approved",
                "states": "KS, OK", "expected_cod": "2027-Q1", "estimated_cost_m": 380,
                "length_miles": 185,
            },
        ]


# ===========================================================================
# NYISO
# ===========================================================================

class NYISOScraper(BaseScraper):
    """
    Scrapes NYISO's Comprehensive Reliability Plan (CRP) projects.
    Source: https://www.nyiso.com/transmission-planning
    """
    SOURCE_NAME = "NYISO"
    BASE_URL    = "https://www.nyiso.com/transmission-planning"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 4:
                projects.append({
                    "project_id": cells[0].get_text(strip=True),
                    "name":       cells[1].get_text(strip=True),
                    "rto":        "NYISO",
                    "voltage_kv": _parse_kv(cells[2].get_text(strip=True)),
                    "status":     cells[3].get_text(strip=True),
                    "states":     "NY",
                    "expected_cod":     "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "NYISO-2024-005", "name": "Champlain Hudson Power Express Upgrades",
                "rto": "NYISO", "voltage_kv": 345, "status": "Permitting – Article VII",
                "states": "NY", "expected_cod": "2027-Q3", "estimated_cost_m": 1100,
                "length_miles": 339,
            },
        ]


# ===========================================================================
# ISO-NE
# ===========================================================================

class ISONEScraper(BaseScraper):
    """
    Scrapes ISO New England's Regional System Plan (RSP) projects.
    Source: https://www.iso-ne.com/system-planning/transmission-planning
    """
    SOURCE_NAME = "ISO-NE"
    BASE_URL    = "https://www.iso-ne.com/system-planning/transmission-planning"

    def scrape_projects(self) -> list[dict]:
        resp = self.get(self.BASE_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        projects = []
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 4:
                projects.append({
                    "project_id": cells[0].get_text(strip=True),
                    "name":       cells[1].get_text(strip=True),
                    "rto":        "ISO-NE",
                    "voltage_kv": _parse_kv(cells[2].get_text(strip=True)),
                    "status":     cells[3].get_text(strip=True),
                    "states":     "",
                    "expected_cod":     "",
                    "estimated_cost_m": None,
                })
        return projects

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "project_id": "ISONE-2024-003", "name": "New England Clean Energy Connect",
                "rto": "ISO-NE", "voltage_kv": 345, "status": "Under Construction",
                "states": "ME, NH, MA", "expected_cod": "2025-Q4", "estimated_cost_m": 950,
                "length_miles": 145,
            },
        ]


# ===========================================================================
# Unified manager
# ===========================================================================

class RTOScraperManager:
    """
    Orchestrates all RTO scrapers — runs them all and returns a combined
    list of transmission projects.
    """

    _SCRAPER_CLASSES = [
        MISOScraper, PJMScraper, ERCOTScraper, CAISOScraper,
        SPPScraper, NYISOScraper, ISONEScraper,
    ]

    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode
        self.scrapers  = [cls(demo_mode=demo_mode) for cls in self._SCRAPER_CLASSES]

    def scrape_all(self) -> list[dict]:
        """Run all scrapers and return merged project list."""
        all_projects = []
        for scraper in self.scrapers:
            projects = scraper.run()
            all_projects.extend(projects)
            logger.info("  %s: collected %d projects", scraper.SOURCE_NAME, len(projects))
        return all_projects

    def demo_scrape(self) -> None:
        """
        Print a demo summary of what each scraper would collect,
        showing the web-scraping logic without real HTTP calls.
        """
        print()
        total = 0
        for scraper in self.scrapers:
            mock = scraper.get_mock_data()
            print(f"  [{scraper.SOURCE_NAME:8s}] → {len(mock):2d} project(s) found")
            for p in mock:
                status_str = p.get("status", "")[:40]
                print(
                    f"           • {p['project_id']:20s} {p['voltage_kv']:>3}kV  "
                    f"{p.get('length_miles', '?'):>4} mi  [{status_str}]"
                )
            total += len(mock)

        print(f"\n  Total: {total} active transmission projects across all RTOs/ISOs")
        print(
            "  (Live mode would parse HTML tables / download XLSX queue files "
            "from each RTO's website)"
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_kv(text: str) -> int:
    """Extract integer kV value from strings like '345 kV', '500kV'."""
    import re
    m = re.search(r"(\d{2,4})", text)
    return int(m.group(1)) if m else 0
