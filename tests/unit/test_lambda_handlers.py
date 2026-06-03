"""Tests for the Lambda proxy handlers (NASA POWER and NOAA NCEI)."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from gateway.lambda_nasa_power.handler import handler as nasa_handler
from gateway.lambda_noaa_ncei.handler import handler as noaa_handler


class TestNasaPowerHandler:
    """Tests for the NASA POWER Lambda proxy."""

    def test_successful_response(self):
        """Should return 200 with structured data on success."""
        fake_api_response = json.dumps({
            "properties": {
                "parameter": {
                    "T2M": {"20200101": 5.2, "20200102": 6.1},
                    "T2M_MAX": {"20200101": 10.1, "20200102": 11.3},
                }
            }
        }).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = fake_api_response
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = nasa_handler(
                {
                    "latitude": 33.45,
                    "longitude": -84.39,
                    "start": "20200101",
                    "end": "20200102",
                    "parameters": "T2M,T2M_MAX",
                },
                None,
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["source"] == "NASA_POWER"
        assert "parameters" in body
        assert "T2M" in body["parameters"]

    def test_uses_default_parameters(self):
        """Should use default values when event fields are missing."""
        fake_api_response = json.dumps({
            "properties": {"parameter": {"T2M": {}}}
        }).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = fake_api_response
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = nasa_handler({}, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        # Should use defaults
        assert body["latitude"] == 33.45
        assert body["longitude"] == -84.39

    def test_api_error_returns_500(self):
        """Should return 500 with error message when API call fails."""
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("Connection timeout"),
        ):
            result = nasa_handler(
                {"latitude": 0, "longitude": 0, "start": "20200101", "end": "20200102"},
                None,
            )

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "error" in body
        assert "Connection timeout" in body["error"]

    def test_response_includes_time_range(self):
        """Response body should include the queried time range."""
        fake_api_response = json.dumps({
            "properties": {"parameter": {}}
        }).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = fake_api_response
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = nasa_handler(
                {
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "start": "20150101",
                    "end": "20151231",
                },
                None,
            )

        body = json.loads(result["body"])
        assert body["time_range"] == "20150101-20151231"


class TestNoaaNceiHandler:
    """Tests for the NOAA NCEI Lambda proxy."""

    def test_successful_response(self):
        """Should return 200 with structured data on success."""
        fake_data = [
            {"STATION": "USW00013874", "DATE": "2020-01-01", "TAVG": "5.2"},
            {"STATION": "USW00013874", "DATE": "2020-02-01", "TAVG": "7.8"},
        ]
        fake_api_response = json.dumps(fake_data).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = fake_api_response
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = noaa_handler(
                {
                    "dataset": "global-summary-of-the-month",
                    "stations": "USW00013874",
                    "startDate": "2020-01-01",
                    "endDate": "2020-12-31",
                },
                None,
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["source"] == "NOAA_NCEI"
        assert body["record_count"] == 2
        assert body["dataset"] == "global-summary-of-the-month"

    def test_truncates_large_response(self):
        """Should limit response to 100 records max."""
        fake_data = [{"STATION": f"USW{i:08d}", "TAVG": "10.0"} for i in range(150)]
        fake_api_response = json.dumps(fake_data).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = fake_api_response
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = noaa_handler(
                {
                    "dataset": "global-summary-of-the-month",
                    "startDate": "2020-01-01",
                    "endDate": "2020-12-31",
                },
                None,
            )

        body = json.loads(result["body"])
        assert body["record_count"] == 100

    def test_api_error_returns_500(self):
        """Should return 500 with error message when API call fails."""
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("Service unavailable"),
        ):
            result = noaa_handler(
                {
                    "dataset": "global-summary-of-the-month",
                    "startDate": "2020-01-01",
                    "endDate": "2020-12-31",
                },
                None,
            )

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "error" in body
        assert "Service unavailable" in body["error"]

    def test_empty_params_removed(self):
        """Empty string parameters should be filtered out of the URL."""
        fake_api_response = json.dumps([]).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = fake_api_response
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_url:
            noaa_handler(
                {
                    "dataset": "global-summary-of-the-month",
                    "stations": "",  # Empty — should be filtered
                    "startDate": "2020-01-01",
                    "endDate": "2020-12-31",
                },
                None,
            )

        # Verify the URL does not contain "stations="
        called_url = mock_url.call_args[0][0].full_url
        assert "stations=" not in called_url
