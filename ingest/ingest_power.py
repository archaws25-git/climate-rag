"""Ingest NASA POWER — query API for US regions and chunk by region+year."""

import json
import os
import time
import urllib.request
import urllib.parse

OUTPUT_DIR = os.environ.get("CHUNK_OUTPUT_DIR", "/tmp/climate-rag-chunks")

BASE_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
PARAMETERS = "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,ALLSKY_SFC_SW_DWN"

REGIONS = {
    "Southeast": {"lat": 33.45, "lon": -84.39, "city": "Atlanta, GA"},
    "Northeast": {"lat": 40.71, "lon": -74.01, "city": "New York, NY"},
    "Midwest": {"lat": 41.88, "lon": -87.63, "city": "Chicago, IL"},
    "West": {"lat": 37.77, "lon": -122.42, "city": "San Francisco, CA"},
    "Alaska": {"lat": 61.22, "lon": -149.90, "city": "Anchorage, AK"},
    "Hawaii": {"lat": 21.31, "lon": -157.86, "city": "Honolulu, HI"},
}


def query_power_api(lat, lon, start_year, end_year):
    """Query NASA POWER monthly API for a location and time range."""
    params = {
        "parameters": PARAMETERS,
        "community": "RE",
        "longitude": lon,
        "latitude": lat,
        "start": str(start_year),
        "end": str(end_year),
        "format": "JSON",
    }
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  Warning: API call failed ({e})")
        return None


def chunk_power_data(region_name, region_info, data) -> list[dict]:
    """Create chunks from NASA POWER API response, grouped by decade."""
    if not data:
        return []

    properties = data.get("properties", {})
    param_data = properties.get("parameter", {})

    if not param_data or "T2M" not in param_data:
        return []

    # Group by decade
    decades = {}
    for date_key, temp in param_data.get("T2M", {}).items():
        if temp == -999.0:
            continue
        year = int(date_key[:4])
        decade = f"{(year // 10) * 10}s"
        if decade not in decades:
            decades[decade] = {"temps": [], "years": set()}
        decades[decade]["temps"].append(temp)
        decades[decade]["years"].add(year)

    chunks = []
    for decade, info in sorted(decades.items()):
        avg = sum(info["temps"]) / len(info["temps"])
        years = sorted(info["years"])

        text = (
            f"NASA POWER Monthly Data — {region_name} ({region_info['city']})\n"
            f"Coordinates: {region_info['lat']}°N, {region_info['lon']}°W\n"
            f"Decade: {decade} | Period: {min(years)}-{max(years)}\n"
            f"Average temperature (T2M): {avg:.1f}°C ({avg * 9/5 + 32:.1f}°F)\n"
            f"Range: {min(info['temps']):.1f}°C to {max(info['temps']):.1f}°C\n"
            f"Observations: {len(info['temps'])} monthly records\n"
        )

        chunks.append({
            "chunk_id": f"power_{region_name.lower()}_{decade}",
            "text": text,
            "metadata": {
                "dataset": "NASA_POWER",
                "region": region_name,
                "city": region_info["city"],
                "lat": region_info["lat"],
                "lon": region_info["lon"],
                "decade": decade,
                "time_range": f"{min(years)}-{max(years)}",
                "avg_temp_c": round(avg, 1),
                "parameters": PARAMETERS,
            },
        })

    return chunks


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_chunks = []

    for region_name, region_info in REGIONS.items():
        print(f"Querying NASA POWER for {region_name}...")
        data = query_power_api(region_info["lat"], region_info["lon"], 1981, 2025)
        chunks = chunk_power_data(region_name, region_info, data)
        all_chunks.extend(chunks)
        print(f"  Created {len(chunks)} chunks")
        time.sleep(2)  # Rate limit: max 5 concurrent

    output_path = os.path.join(OUTPUT_DIR, "power_chunks.jsonl")
    with open(output_path, "w") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk) + "\n")

    print(f"Created {len(all_chunks)} NASA POWER chunks → {output_path}")


if __name__ == "__main__":
    main()
