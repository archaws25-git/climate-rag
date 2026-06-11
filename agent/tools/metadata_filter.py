"""Metadata pre-filtering for ClimateRAG hybrid search.

Applies hard filters BEFORE vector/BM25 search to reduce candidate set:
  - Temporal: decade range extracted from query
  - Geographic: region match OR radius-based city filter (50 miles)

This reduces the number of chunks the search considers, improving both
latency (less to score) and relevance (eliminates irrelevant decades/regions).
"""

import math
import re
from typing import Optional

# ── City Geocoding Lookup (from STATIONS dict in ingest_ghcn.py) ──────────────
# Maps city names/aliases to (lat, lon) for radius filtering.

CITY_COORDINATES = {
    # Southeast
    "atlanta": (33.63, -84.44),
    "miami": (25.79, -80.32),
    "charlotte": (35.21, -80.94),
    "nashville": (36.12, -86.69),
    "jacksonville": (30.49, -81.69),
    "new orleans": (29.98, -90.25),
    "nola": (29.98, -90.25),
    # Northeast
    "new york": (40.78, -73.97),
    "nyc": (40.78, -73.97),
    "new york city": (40.78, -73.97),
    "manhattan": (40.78, -73.97),
    "boston": (42.36, -71.01),
    "philadelphia": (39.87, -75.23),
    "philly": (39.87, -75.23),
    "washington": (38.85, -77.03),
    "washington dc": (38.85, -77.03),
    "dc": (38.85, -77.03),
    "pittsburgh": (40.49, -80.23),
    "hartford": (41.94, -72.68),
    # Midwest
    "chicago": (41.99, -87.91),
    "detroit": (42.21, -83.35),
    "minneapolis": (44.88, -93.23),
    "st louis": (38.75, -90.37),
    "saint louis": (38.75, -90.37),
    "indianapolis": (39.72, -86.27),
    "indy": (39.72, -86.27),
    "columbus": (40.00, -82.88),
    # West
    "los angeles": (33.94, -118.39),
    "la": (33.94, -118.39),
    "lax": (33.94, -118.39),
    "san francisco": (37.62, -122.37),
    "sf": (37.62, -122.37),
    "seattle": (47.45, -122.31),
    "denver": (39.83, -104.66),
    "phoenix": (33.43, -112.01),
    "portland": (45.59, -122.60),
    "las vegas": (36.07, -115.16),
    "vegas": (36.07, -115.16),
    "salt lake city": (40.78, -111.97),
    # South Central
    "dallas": (32.90, -97.02),
    "fort worth": (32.90, -97.02),
    "houston": (29.65, -95.28),
    "oklahoma city": (35.39, -97.60),
    "san antonio": (29.53, -98.47),
    "memphis": (35.06, -89.99),
    "little rock": (34.73, -92.24),
    # Alaska
    "anchorage": (61.17, -150.02),
    "fairbanks": (64.80, -147.87),
    "juneau": (58.36, -134.58),
    # Hawaii
    "honolulu": (21.33, -157.93),
    "hilo": (19.72, -155.05),
}

# Region name variants
REGION_ALIASES = {
    "southeast": "Southeast",
    "southeastern": "Southeast",
    "south east": "Southeast",
    "northeast": "Northeast",
    "northeastern": "Northeast",
    "north east": "Northeast",
    "midwest": "Midwest",
    "midwestern": "Midwest",
    "mid west": "Midwest",
    "west": "West",
    "western": "West",
    "south central": "South Central",
    "south-central": "South Central",
    "alaska": "Alaska",
    "hawaii": "Hawaii",
}

# 50 miles in degrees (approximate: 1 degree lat ≈ 69 miles)
RADIUS_MILES = 50
MILES_PER_DEGREE_LAT = 69.0


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in miles using Haversine formula."""
    r = 3959  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return r * 2 * math.asin(math.sqrt(a))


def extract_temporal_filter(query: str) -> Optional[tuple[str, str]]:
    """Extract temporal decade range from a query.

    Returns (min_decade, max_decade) as strings like ("1950s", "2020s"),
    or None if no temporal constraint detected.

    Handles:
      - "since 1950" → ("1950s", "2020s")
      - "from the 1950s to 2020s" → ("1950s", "2020s")
      - "in the 1990s" → ("1990s", "1990s")
      - "last 50 years" → computed from 2025
      - "over the last 30 years" → computed from 2025
    """
    query_lower = query.lower()

    # Pattern: "from the Xs to Ys" or "from X to Y"
    range_match = re.search(
        r'from\s+(?:the\s+)?(\d{4})s?\s+to\s+(?:the\s+)?(\d{4})s?',
        query_lower
    )
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return (f"{(start // 10) * 10}s", f"{(end // 10) * 10}s")

    # Pattern: "since XXXX"
    since_match = re.search(r'since\s+(?:the\s+)?(\d{4})s?', query_lower)
    if since_match:
        start = int(since_match.group(1))
        return (f"{(start // 10) * 10}s", "2020s")

    # Pattern: "in the XXXXs"
    decade_match = re.search(r'in\s+the\s+(\d{4})s', query_lower)
    if decade_match:
        decade = int(decade_match.group(1))
        return (f"{decade}s", f"{decade}s")

    # Pattern: "last N years" or "over the past N years"
    last_years_match = re.search(r'(?:last|past)\s+(\d+)\s+years?', query_lower)
    if last_years_match:
        years = int(last_years_match.group(1))
        start_year = 2025 - years
        return (f"{(start_year // 10) * 10}s", "2020s")

    return None


def extract_geo_filter(query: str) -> Optional[dict]:
    """Extract geographic filter from a query.

    Returns one of:
      - {"type": "radius", "lat": float, "lon": float, "city": str}
      - {"type": "region", "region": str}
      - None (no geographic constraint)

    Priority: city match (radius filter) > region match.
    """
    query_lower = query.lower()

    # Check for city mentions (longest match first to avoid partial matches)
    # Use word boundary check to prevent substring matches (e.g., "la" in "alaska")
    sorted_cities = sorted(CITY_COORDINATES.keys(), key=len, reverse=True)
    for city_name in sorted_cities:
        # Word boundary check: city must be preceded/followed by non-alpha or string edge
        pattern = r'(?<![a-z])' + re.escape(city_name) + r'(?![a-z])'
        if re.search(pattern, query_lower):
            lat, lon = CITY_COORDINATES[city_name]
            return {"type": "radius", "lat": lat, "lon": lon, "city": city_name}

    # Check for region mentions
    for alias, region in REGION_ALIASES.items():
        if alias in query_lower:
            return {"type": "region", "region": region}

    return None


def apply_metadata_filters(
    metadata: list[dict],
    query: str,
) -> tuple[list[int], int]:
    """Apply temporal + geographic filters and return indices of matching chunks.

    Args:
        metadata: The full metadata list (same order as FAISS index).
        query: The user's natural language query.

    Returns:
        Tuple of (valid_indices, expected_decades_per_entity).
        - valid_indices: List of valid indices into the metadata/FAISS index.
          Returns ALL indices if no filters match (no restriction).
        - expected_decades_per_entity: Number of decades in the temporal range
          (0 if no temporal filter detected). Used by multi-entity search to
          set appropriate result caps.
    """
    temporal = extract_temporal_filter(query)
    geo = extract_geo_filter(query)

    # Compute expected decades from temporal range
    expected_decades = 0
    if temporal is not None:
        min_decade, max_decade = temporal
        min_year = int(min_decade[:-1])
        max_year = int(max_decade[:-1])
        expected_decades = ((max_year - min_year) // 10) + 1

    # If no filters detected, return all indices (no restriction)
    if temporal is None and geo is None:
        return list(range(len(metadata))), expected_decades

    valid_indices = []

    for idx, meta_entry in enumerate(metadata):
        chunk_meta = meta_entry.get("metadata", {})

        # ── Temporal filter ───────────────────────────────────────
        if temporal is not None:
            min_decade, max_decade = temporal
            chunk_decade = chunk_meta.get("decade", "")
            if chunk_decade:
                # Compare decade strings (e.g., "1990s" >= "1950s")
                if not (min_decade <= chunk_decade <= max_decade):
                    continue

        # ── Geographic filter ─────────────────────────────────────
        if geo is not None:
            if geo["type"] == "region":
                chunk_region = chunk_meta.get("region", "")
                if chunk_region and chunk_region != geo["region"]:
                    # Allow global data through (GISTEMP)
                    if chunk_region != "Global":
                        continue
            elif geo["type"] == "radius":
                chunk_lat = chunk_meta.get("lat")
                chunk_lon = chunk_meta.get("lon")
                if chunk_lat is not None and chunk_lon is not None:
                    distance = haversine_miles(
                        geo["lat"], geo["lon"],
                        float(chunk_lat), float(chunk_lon)
                    )
                    if distance > RADIUS_MILES:
                        continue
                # If chunk has no lat/lon (e.g., GISTEMP global), let it through

        valid_indices.append(idx)

    # If filters are too restrictive (0 results), fall back to all indices
    if not valid_indices:
        return list(range(len(metadata))), expected_decades

    return valid_indices, expected_decades
