"""Tests for metadata pre-filtering (temporal + geographic)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from tools.metadata_filter import (
    apply_metadata_filters,
    extract_geo_filter,
    extract_temporal_filter,
    haversine_miles,
)


class TestTemporalFilter:
    """Tests for extract_temporal_filter."""

    def test_since_year(self):
        result = extract_temporal_filter("How has temperature changed since 1950?")
        assert result == ("1950s", "2020s")

    def test_since_decade(self):
        result = extract_temporal_filter("What happened since the 1980s?")
        assert result == ("1980s", "2020s")

    def test_from_to_range(self):
        result = extract_temporal_filter("from the 1950s to 2020s")
        assert result == ("1950s", "2020s")

    def test_from_to_years(self):
        result = extract_temporal_filter("from 1960 to 2010")
        assert result == ("1960s", "2010s")

    def test_in_the_decade(self):
        result = extract_temporal_filter("What was the temperature in the 1990s?")
        assert result == ("1990s", "1990s")

    def test_last_50_years(self):
        result = extract_temporal_filter("temperature trends over the last 50 years")
        assert result is not None
        min_decade, max_decade = result
        assert min_decade == "1970s"
        assert max_decade == "2020s"

    def test_last_30_years(self):
        result = extract_temporal_filter("climate in the past 30 years")
        assert result is not None
        min_decade, max_decade = result
        assert min_decade == "1990s"

    def test_no_temporal_constraint(self):
        result = extract_temporal_filter("What is the temperature in Atlanta?")
        assert result is None

    def test_no_temporal_for_generic(self):
        result = extract_temporal_filter("climate data for Southeast")
        assert result is None


class TestGeoFilter:
    """Tests for extract_geo_filter."""

    def test_city_match_new_york(self):
        result = extract_geo_filter("temperature in New York")
        assert result is not None
        assert result["type"] == "radius"
        assert result["city"] == "new york"
        assert abs(result["lat"] - 40.78) < 0.01

    def test_city_match_nyc(self):
        result = extract_geo_filter("NYC temperature trends")
        assert result is not None
        assert result["type"] == "radius"
        assert result["city"] == "nyc"

    def test_city_match_la(self):
        result = extract_geo_filter("climate in LA since 1950")
        assert result is not None
        assert result["type"] == "radius"
        assert result["city"] == "la"

    def test_city_match_chicago(self):
        result = extract_geo_filter("Chicago temperature in the 1990s")
        assert result is not None
        assert result["type"] == "radius"
        assert result["city"] == "chicago"

    def test_region_match_southeast(self):
        result = extract_geo_filter("temperature trends in the Southeast")
        assert result is not None
        assert result["type"] == "region"
        assert result["region"] == "Southeast"

    def test_region_match_midwest(self):
        result = extract_geo_filter("Midwest precipitation data")
        assert result is not None
        assert result["type"] == "region"
        assert result["region"] == "Midwest"

    def test_region_match_alaska(self):
        result = extract_geo_filter("Alaska warming rates")
        assert result is not None
        assert result["type"] == "region"
        assert result["region"] == "Alaska"

    def test_no_geo_constraint(self):
        result = extract_geo_filter("global temperature anomalies")
        assert result is None

    def test_city_takes_priority_over_region(self):
        # "Atlanta" is a city, even though it's in the Southeast
        result = extract_geo_filter("Atlanta temperature in Southeast")
        assert result is not None
        assert result["type"] == "radius"
        assert result["city"] == "atlanta"


class TestHaversine:
    """Tests for haversine distance calculation."""

    def test_same_point(self):
        assert haversine_miles(40.78, -73.97, 40.78, -73.97) == 0.0

    def test_known_distance(self):
        # NYC to Boston is approximately 190 miles
        dist = haversine_miles(40.78, -73.97, 42.36, -71.01)
        assert 180 < dist < 220

    def test_short_distance(self):
        # Two nearby points should be < 50 miles
        dist = haversine_miles(40.78, -73.97, 40.90, -73.80)
        assert dist < 50


class TestApplyMetadataFilters:
    """Tests for the full apply_metadata_filters function."""

    @pytest.fixture
    def sample_metadata(self):
        """Create sample metadata matching the real index structure."""
        return [
            {"metadata": {"region": "Southeast", "decade": "1990s", "lat": 33.63, "lon": -84.44}},
            {"metadata": {"region": "Southeast", "decade": "2000s", "lat": 33.63, "lon": -84.44}},
            {"metadata": {"region": "Northeast", "decade": "1990s", "lat": 40.78, "lon": -73.97}},
            {"metadata": {"region": "Northeast", "decade": "2000s", "lat": 40.78, "lon": -73.97}},
            {"metadata": {"region": "West", "decade": "1990s", "lat": 33.94, "lon": -118.39}},
            {"metadata": {"region": "Global", "decade": "1990s"}},
            {"metadata": {"region": "Global", "decade": "2000s"}},
        ]

    def test_no_filter_returns_all(self, sample_metadata):
        indices = apply_metadata_filters(sample_metadata, "what is the temperature?")
        assert len(indices) == len(sample_metadata)

    def test_region_filter(self, sample_metadata):
        indices = apply_metadata_filters(sample_metadata, "temperature in the Southeast")
        # Should include Southeast + Global (Global passes through)
        for idx in indices:
            region = sample_metadata[idx]["metadata"].get("region", "")
            assert region in ("Southeast", "Global")

    def test_temporal_filter(self, sample_metadata):
        indices = apply_metadata_filters(sample_metadata, "temperature in the 1990s")
        for idx in indices:
            decade = sample_metadata[idx]["metadata"].get("decade", "")
            assert decade == "1990s"

    def test_combined_filter(self, sample_metadata):
        indices = apply_metadata_filters(
            sample_metadata, "Southeast temperature in the 1990s"
        )
        for idx in indices:
            meta = sample_metadata[idx]["metadata"]
            assert meta.get("decade") == "1990s"
            assert meta.get("region") in ("Southeast", "Global")

    def test_fallback_on_empty_result(self, sample_metadata):
        # A filter so restrictive it matches nothing should fall back to all
        indices = apply_metadata_filters(
            sample_metadata, "temperature in Antarctica in the 1800s"
        )
        # "Antarctica" won't match any city/region, "1800s" won't match any decade
        # So temporal filter applies but finds nothing → fallback to all
        assert len(indices) == len(sample_metadata)
