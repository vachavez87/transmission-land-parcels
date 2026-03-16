"""
scrapers/parcel_scraper.py
Scrapes parcel ownership data and real estate listing status from:
    - REGRID API   (national parcel database)
    - County GIS portals  (ArcGIS REST services)
    - Land.com / LandWatch (for-sale listing status)

In DEMO mode, returns mock parcel enrichment data.
"""
import logging
from typing import Optional

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class REGRIDScraper(BaseScraper):
    """
    Queries the REGRID parcel API to retrieve ownership and boundary data.
    Documentation: https://regrid.com/api

    Requires REGRID_API_KEY environment variable.

    Key endpoints:
        GET /api/v2/parcels/point?lat=&lon=   Parcel at a point
        GET /api/v2/parcels/bbox?west=&south=&east=&north=  Parcels in bbox
        GET /api/v2/parcels/{ll_uuid}          Single parcel by LL_UUID
    """

    SOURCE_NAME = "REGRID"
    BASE_URL    = "https://app.regrid.com/api/v2"

    def __init__(self, api_key: str = "", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def get_parcels_in_bbox(
        self,
        west: float, south: float,
        east: float, north: float,
        limit: int = 500,
    ) -> list[dict]:
        """Retrieve all parcels in a bounding box."""
        if self.demo_mode:
            return self.get_mock_data()

        url = f"{self.BASE_URL}/parcels/bbox"
        params = {
            "west":  west, "south": south,
            "east":  east, "north": north,
            "token": self.api_key,
            "limit": limit,
            "fields": "ll_uuid,owner,mailadd,siteadd,acres,landuse,zoning,geom",
        }
        resp = self.get(url, params=params)
        data = resp.json()

        return [
            {
                "parcel_id":        f["properties"].get("ll_uuid", ""),
                "owner":            f["properties"].get("owner", "Unknown"),
                "mailing_address":  f["properties"].get("mailadd", ""),
                "site_address":     f["properties"].get("siteadd", ""),
                "acreage":          f["properties"].get("acres", 0),
                "land_use":         f["properties"].get("landuse", ""),
                "zoning":           f["properties"].get("zoning", ""),
                "geometry":         f.get("geometry"),
            }
            for f in data.get("features", [])
        ]

    def scrape_projects(self) -> list[dict]:
        raise NotImplementedError("REGRIDScraper returns parcel data, not projects")

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "parcel_id": "DEMO-REGRID-0001",
                "owner":     "Smith Family Trust",
                "acreage":   240.5,
                "land_use":  "Agricultural",
                "zoning":    "A-1",
            },
        ]


class CountyGISScraper(BaseScraper):
    """
    Queries county-level GIS portals (typically ArcGIS REST Feature Services)
    to retrieve parcel data for counties without REGRID coverage.

    Pattern: many counties expose:
      https://<county-gis-server>/arcgis/rest/services/Parcels/FeatureServer/0/query

    Parameters for the ArcGIS query:
        geometry        : envelope or polygon in WGS84
        geometryType    : esriGeometryEnvelope
        spatialRel      : esriSpatialRelIntersects
        outFields       : APN,OWNER,SITEADDR,ACRES,LANDUSE
        f               : json
    """

    SOURCE_NAME = "CountyGIS"
    BASE_URL    = ""   # Set per-county

    def __init__(self, county_name: str, service_url: str, **kwargs):
        super().__init__(**kwargs)
        self.county_name = county_name
        self.BASE_URL    = service_url

    def query_bbox(
        self,
        west: float, south: float,
        east: float, north: float,
    ) -> list[dict]:
        """Query ArcGIS REST service for parcels in a bounding box."""
        if self.demo_mode:
            return self.get_mock_data()

        params = {
            "geometry":     f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope",
            "spatialRel":   "esriSpatialRelIntersects",
            "inSR":         "4326",
            "outSR":        "4326",
            "outFields":    "APN,OWNER,SITEADDR,ACRES,LANDUSE,SALE_DATE",
            "returnGeometry": "true",
            "f":            "json",
        }
        resp = self.get(f"{self.BASE_URL}/query", params=params)
        data = resp.json()

        return [
            {
                "parcel_id":  feat["attributes"].get("APN", ""),
                "owner":      feat["attributes"].get("OWNER", "Unknown"),
                "address":    feat["attributes"].get("SITEADDR", ""),
                "acreage":    feat["attributes"].get("ACRES", 0),
                "land_use":   feat["attributes"].get("LANDUSE", ""),
                "last_sale":  feat["attributes"].get("SALE_DATE", ""),
                "county":     self.county_name,
            }
            for feat in data.get("features", [])
        ]

    def scrape_projects(self) -> list[dict]:
        raise NotImplementedError("CountyGISScraper returns parcel data, not projects")

    def get_mock_data(self) -> list[dict]:
        return []


class LandListingScraper(BaseScraper):
    """
    Scrapes land-for-sale listings from Land.com and LandWatch to identify
    parcels currently on the market in transmission corridors.

    These sites are scraped by:
        1. Searching within a bounding box or state/county filter
        2. Parsing listing cards for address, acreage, price, coordinates
        3. Cross-referencing coordinates with scored parcel polygons
    """

    SOURCE_NAME = "LandListings"
    BASE_URL    = "https://www.land.com"

    def scrape_projects(self) -> list[dict]:
        raise NotImplementedError("LandListingScraper returns listing data, not RTO projects")

    def scrape_listings_in_state(self, state: str, county: Optional[str] = None) -> list[dict]:
        """
        Scrape current land listings for a state (and optional county).
        Returns list of listing dicts with lat/lon for overlay matching.
        """
        if self.demo_mode:
            return self.get_mock_data()

        search_url = f"{self.BASE_URL}/for-sale/{state.lower()}/"
        if county:
            search_url += f"{county.lower().replace(' ', '-')}-county/"

        resp = self.get(search_url)
        soup = BeautifulSoup(resp.text, "lxml")

        listings = []
        for card in soup.select("div.listing-card, div[data-testid='listing-card']"):
            title    = card.select_one(".listing-title, h2")
            price_el = card.select_one(".listing-price, [data-testid='price']")
            acres_el = card.select_one(".listing-acres, [data-testid='acres']")
            lat_el   = card.get("data-lat") or card.select_one("[data-lat]")
            lon_el   = card.get("data-lon") or card.select_one("[data-lon]")

            if not title:
                continue

            try:
                price = int(price_el.get_text(strip=True).replace("$", "").replace(",", "")) \
                        if price_el else None
                acres = float(acres_el.get_text(strip=True).split()[0]) if acres_el else 0
                lat   = float(lat_el) if lat_el and not hasattr(lat_el, "get") else None
                lon   = float(lon_el) if lon_el and not hasattr(lon_el, "get") else None
            except (ValueError, TypeError):
                continue

            listings.append({
                "title":       title.get_text(strip=True),
                "state":       state,
                "county":      county or "",
                "asking_price": price,
                "acreage":     acres,
                "lat":         lat,
                "lon":         lon,
                "source":      "land.com",
            })

        return listings

    def get_mock_data(self) -> list[dict]:
        return [
            {
                "title": "240-Acre Farm – Sullivan County, IN",
                "state": "IN", "county": "Sullivan",
                "asking_price": 1_680_000, "acreage": 240,
                "lat": 39.10, "lon": -87.45, "source": "land.com",
            },
            {
                "title": "160-Acre Row Crop – Effingham County, IL",
                "state": "IL", "county": "Effingham",
                "asking_price": 960_000, "acreage": 160,
                "lat": 39.05, "lon": -88.60, "source": "land.com",
            },
            {
                "title": "380-Acre Ranch – Concho County, TX",
                "state": "TX", "county": "Concho",
                "asking_price": 1_520_000, "acreage": 380,
                "lat": 31.25, "lon": -99.80, "source": "landwatch.com",
            },
        ]
