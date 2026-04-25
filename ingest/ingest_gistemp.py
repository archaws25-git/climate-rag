"""Ingest NASA GISTEMP v4 — download, parse, and chunk global temperature anomalies."""

import csv
import io
import json
import os
import urllib.request

OUTPUT_DIR = os.environ.get("CHUNK_OUTPUT_DIR", "/tmp/climate-rag-chunks")
GISTEMP_URL = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"


def download_gistemp():
    """Download GISTEMP v4 Land-Ocean Temperature Index CSV."""
    print(f"Downloading GISTEMP v4 from {GISTEMP_URL}...")
    req = urllib.request.Request(GISTEMP_URL)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse_and_chunk(csv_text: str) -> list[dict]:
    """Parse GISTEMP CSV and create chunks by decade."""
    reader = csv.reader(io.StringIO(csv_text))

    # Skip header line(s) — GISTEMP has a title row then column headers
    header = None
    for row in reader:
        if row and row[0].strip().isdigit():
            header_row = row
            break
        if row and "Year" in row[0]:
            header = row
            continue

    if not header:
        header = ["Year", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
                  "J-D", "D-N", "DJF", "MAM", "JJA", "SON"]

    # Group by decade
    decades = {}
    all_rows = []

    # Re-read from the numeric rows
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if not row or not row[0].strip().replace("-", "").isdigit():
            continue
        try:
            year = int(row[0].strip())
        except ValueError:
            continue
        if year < 1880 or year > 2030:
            continue

        decade = f"{(year // 10) * 10}s"
        annual_anomaly = row[13].strip() if len(row) > 13 else "***"

        if annual_anomaly == "***" or annual_anomaly == "":
            continue

        if decade not in decades:
            decades[decade] = []
        decades[decade].append({"year": year, "annual_anomaly": float(annual_anomaly)})

    chunks = []
    for decade, records in sorted(decades.items()):
        anomalies = [r["annual_anomaly"] for r in records]
        avg = sum(anomalies) / len(anomalies)
        years = [r["year"] for r in records]

        text = (
            f"GISTEMP v4 Global Land-Ocean Temperature Index — {decade}\n"
            f"Period: {min(years)}-{max(years)}\n"
            f"Baseline: 1951-1980 mean\n"
            f"Average annual anomaly: {avg:.3f}°C\n"
            f"Range: {min(anomalies):.3f}°C to {max(anomalies):.3f}°C\n"
            f"Year-by-year anomalies:\n"
        )
        for r in records:
            text += f"  {r['year']}: {r['annual_anomaly']:+.3f}°C\n"

        chunks.append({
            "chunk_id": f"gistemp_global_{decade}",
            "text": text,
            "metadata": {
                "dataset": "GISTEMP_v4",
                "region": "Global",
                "decade": decade,
                "time_range": f"{min(years)}-{max(years)}",
                "unit": "degrees_C_anomaly",
                "baseline": "1951-1980",
                "avg_anomaly": round(avg, 3),
            },
        })

    return chunks


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    csv_text = download_gistemp()
    chunks = parse_and_chunk(csv_text)

    output_path = os.path.join(OUTPUT_DIR, "gistemp_chunks.jsonl")
    with open(output_path, "w") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    print(f"Created {len(chunks)} GISTEMP chunks → {output_path}")


if __name__ == "__main__":
    main()
