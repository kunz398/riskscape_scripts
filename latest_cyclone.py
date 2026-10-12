
import json
import re
import sys
from dataclasses import dataclass

import requests

URL = "https://pacific-disaster-api.spc.int/partner_api/v1/cyclone_track/?format=json"
OUT_GEOJSON = "cyclone-latest.geojson"


@dataclass
class Cyclone:
    id: int
    cyclone_id: str
    name: str
    issue_time: str
    agency: str
    track_type: int
    track_file: str
    geometry: dict
    geojson_path: str


def fetch_records(url=URL):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def get_latest_cyclone(url=URL, track_type=None, save_to=OUT_GEOJSON):
    """Return the latest cyclone as a Cyclone object, or raise ValueError if none."""
    records = fetch_records(url)

    valid = [r for r in records if r.get("issued_time")]
    if track_type is not None:
        valid = [r for r in valid if r.get("cyclone_track_type") == track_type]
    if not valid:
        raise ValueError("No cyclone tracks found")

    latest = max(valid, key=lambda r: r["issued_time"])

    geometry = latest.get("geometry") or {}
    if not geometry.get("features"):
        raise ValueError(f"Latest record {latest.get('id')} has no track geometry")

    if save_to:
        with open(save_to, "w") as f:
            json.dump(geometry, f)

    cyclone_id = latest.get("cyclone_name") or ""
    return Cyclone(
        id=latest.get("id"),
        cyclone_id=cyclone_id,
        name=re.sub(r"^\d+_", "", cyclone_id),
        issue_time=latest["issued_time"],
        agency=latest.get("issued_agency"),
        track_type=latest.get("cyclone_track_type"),
        track_file=latest.get("track_file"),
        geometry=geometry,
        geojson_path=save_to,
    )


if __name__ == "__main__":
    try:
        c = get_latest_cyclone()
    except ValueError as e:
        sys.exit(str(e))
    print(f"CYCLONE_ID={c.cyclone_id}")
    print(f"CYCLONE_NAME={c.name}")
    print(f"ISSUE_TIME={c.issue_time}")