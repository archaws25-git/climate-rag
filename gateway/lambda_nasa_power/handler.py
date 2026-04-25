"""Lambda proxy for NASA POWER API — exposed as MCP tool via AgentCore Gateway."""

import json
import urllib.request
import urllib.parse

BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"


def handler(event, context):
    """Query NASA POWER API for climate parameters at a given location and time range.

    Expected event keys:
        latitude (float): Location latitude
        longitude (float): Location longitude
        start (str): Start date YYYYMMDD
        end (str): End date YYYYMMDD
        parameters (str): Comma-separated parameter codes e.g. "T2M,PRECTOTCORR"
        community (str): "RE" (renewable energy) or "AG" (agroclimatology)
    """
    params = {
        "parameters": event.get("parameters", "T2M,T2M_MAX,T2M_MIN"),
        "community": event.get("community", "RE"),
        "longitude": event.get("longitude", -84.39),
        "latitude": event.get("latitude", 33.45),
        "start": event.get("start", "20200101"),
        "end": event.get("end", "20201231"),
        "format": "JSON",
    }

    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        # Extract just the parameter values to keep response compact
        properties = data.get("properties", {})
        parameter_data = properties.get("parameter", {})

        return {
            "statusCode": 200,
            "body": json.dumps({
                "source": "NASA_POWER",
                "latitude": params["latitude"],
                "longitude": params["longitude"],
                "time_range": f"{params['start']}-{params['end']}",
                "parameters": parameter_data,
            }),
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
