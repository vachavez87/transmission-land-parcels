"""
scrapers/base_scraper.py
Base scraper class providing shared session management, rate limiting,
retry logic, and User-Agent rotation for all RTO/parcel scrapers.
"""
import time
import random
import logging
from abc import ABC, abstractmethod
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Realistic user-agent pool — rotate to avoid simple bot detection
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]


class BaseScraper(ABC):
    """
    Abstract base class for all scrapers in this system.

    Provides:
        - Requests session with automatic retry on transient failures
        - Configurable rate limiting (delay between requests)
        - User-Agent rotation
        - Structured logging
        - Demo mode (returns mock data without making real HTTP calls)
    """

    SOURCE_NAME: str = "BaseSource"
    BASE_URL:    str = ""

    def __init__(
        self,
        delay_seconds: float = 2.0,
        timeout: int = 30,
        max_retries: int = 3,
        demo_mode: bool = False,
    ):
        self.delay_seconds = delay_seconds
        self.timeout       = timeout
        self.demo_mode     = demo_mode
        self._session: Optional[requests.Session] = None

        if not demo_mode:
            self._session = self._build_session(max_retries)

    # ------------------------------------------------------------------
    # Session setup
    # ------------------------------------------------------------------

    def _build_session(self, max_retries: int) -> requests.Session:
        session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://",  adapter)

        session.headers.update({
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
        })
        return session

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with rate limiting and header rotation."""
        if self.demo_mode:
            raise RuntimeError("get() called in demo mode — use mock data instead")

        time.sleep(self.delay_seconds + random.uniform(0, 0.5))
        self._session.headers["User-Agent"] = random.choice(_USER_AGENTS)

        logger.debug("GET %s", url)
        resp = self._session.get(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        """POST with rate limiting."""
        if self.demo_mode:
            raise RuntimeError("post() called in demo mode")

        time.sleep(self.delay_seconds)
        logger.debug("POST %s", url)
        resp = self._session.post(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def scrape_projects(self) -> list[dict]:
        """
        Scrape transmission projects from the source.

        Returns
        -------
        list of project dicts with keys:
            project_id, name, rto, voltage_kv, status, states,
            expected_cod, estimated_cost_m, route_description
        """

    @abstractmethod
    def get_mock_data(self) -> list[dict]:
        """Return realistic mock data for demo mode."""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> list[dict]:
        """Run the scraper (real or demo) and return project list."""
        if self.demo_mode:
            logger.info("[DEMO] %s — returning mock data", self.SOURCE_NAME)
            return self.get_mock_data()

        logger.info("Scraping %s → %s", self.SOURCE_NAME, self.BASE_URL)
        try:
            return self.scrape_projects()
        except Exception as exc:
            logger.error("Error scraping %s: %s", self.SOURCE_NAME, exc)
            return []

    def __repr__(self) -> str:
        mode = "DEMO" if self.demo_mode else "LIVE"
        return f"<{self.__class__.__name__} [{mode}] source={self.SOURCE_NAME}>"
