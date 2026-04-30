"""Lambda proxy for NOAA NCEI Access Data Service — exposed as MCP tool via Gateway."""

import json
import os
import urllib.request
import urllib.parse

BASE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
CDO_TOKEN = os.environ.get("NOAA_CDO_TOKEN", "")


def handler(event, context):
    """Query NOAA NCEI for historical climate observations.

    Expected event keys:
        dataset (str): e.g. "global-summary-of-the-month"
        stations (str): Comma-separated station IDs
        startDate (str): YYYY-MM-DD
        endDate (str): YYYY-MM-DD
        dataTypes (str): Comma-separated e.g. "TAVG,TMAX,TMIN,PRCP"
    """
    params = {
        "dataset": event.get("dataset", "global-summary-of-the-month"),
        "stations": event.get("stations", ""),
        "startDate": event.get("startDate", "2020-01-01"),
        "endDate": event.get("endDate", "2020-12-31"),
        "dataTypes": event.get("dataTypes", "TAVG,TMAX,TMIN"),
        "format": "json",
        "units": "metric",
    }

    # Remove empty params
    params = {k: v for k, v in params.items() if v}
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url)
        if CDO_TOKEN:
            req.add_header("token", CDO_TOKEN)

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        # Limit response size
        if isinstance(data, list) and len(data) > 100:
            data = data[:100]

        return {
            "statusCode": 200,
            "body": json.dumps({
                "source": "NOAA_NCEI",
                "dataset": params["dataset"],
                "record_count": len(data) if isinstance(data, list) else 1,
                "data": data,
            }),
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
