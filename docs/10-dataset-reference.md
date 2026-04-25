# ClimateRAG — Dataset Reference Guide

**Date:** 2026-03-26 | **Version:** 1.0

---

## 1. NOAA GHCN v4 (Global Historical Climatology Network)

- **Provider:** NOAA National Centers for Environmental Information (NCEI)
- **Content:** Monthly temperature records from ~27,000+ stations worldwide since 1880
- **URL:** https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-monthly
- **API:** https://www.ncei.noaa.gov/access/services/data/v1
- **Format:** CSV/text
- **License:** Public domain (US Government work)
- **Scope for ClimateRAG:** US stations only, 1950-present (~500 MB)
- **Key fields:** station_id, date, TAVG, TMAX, TMIN, latitude, longitude, state
- **Update frequency:** Monthly
- **Citation:** Menne, M.J., C.N. Williams, B.E. Gleason, J.J. Rennie, and J.H. Lawrimore, 2018: The Global Historical Climatology Network Monthly Temperature Dataset, Version 4. J. Climate.

## 2. NASA GISTEMP v4

- **Provider:** NASA Goddard Institute for Space Studies (GISS)
- **Content:** Global surface temperature anomalies since 1880, 2x2 degree grid
- **URL:** https://data.giss.nasa.gov/gistemp/
- **Downloads:** https://data.giss.nasa.gov/gistemp/data_v4.html
- **Format:** CSV, NetCDF, Zarr
- **License:** NASA public domain
- **Scope for ClimateRAG:** Full global dataset (~100 MB)
- **Key fields:** year, month, anomaly (vs 1951-1980 baseline), latitude band
- **Baseline period:** 1951-1980
- **Update frequency:** Monthly (~10th of each month)
- **Citation:** GISTEMP Team, 2026: GISS Surface Temperature Analysis (GISTEMP), version 4. NASA GISS.
- **Data sources:** NOAA GHCN v4 (stations) + ERSST v5 (ocean)

## 3. NASA POWER

- **Provider:** NASA Langley Research Center
- **Content:** Solar radiation, temperature, precipitation, wind — 1981 to present
- **URL:** https://power.larc.nasa.gov/
- **API:** https://power.larc.nasa.gov/api/temporal/daily/point
- **Format:** JSON, CSV, NetCDF
- **License:** Public domain (NASA)
- **Resolution:** 0.5 x 0.625 degree (meteorology), 1 x 1 degree (solar)
- **Scope for ClimateRAG:** 6 US regions, 1981-present (~200 MB)
- **Key parameters:**
  - T2M: Temperature at 2 meters (C)
  - T2M_MAX / T2M_MIN: Daily max/min temperature
  - PRECTOTCORR: Precipitation corrected (mm/day)
  - ALLSKY_SFC_SW_DWN: All-sky surface shortwave downward irradiance (W/m2)
- **Rate limit:** Max 5 concurrent requests
- **Auth:** None required
- **Communities:** RE (Renewable Energy), AG (Agroclimatology), SB (Sustainable Buildings)

## 4. US Regions for NASA POWER Queries

| Region | Representative Lat/Lon | States |
|---|---|---|
| Southeast | 33.45, -84.39 (Atlanta) | GA, FL, AL, SC, NC, TN, MS, LA |
| Northeast | 40.71, -74.01 (New York) | NY, NJ, CT, MA, PA, ME, VT, NH, RI |
| Midwest | 41.88, -87.63 (Chicago) | IL, IN, OH, MI, WI, MN, IA, MO |
| West | 37.77, -122.42 (San Francisco) | CA, OR, WA, NV, AZ, UT, CO |
| Alaska | 61.22, -149.90 (Anchorage) | AK |
| Hawaii | 21.31, -157.86 (Honolulu) | HI |
