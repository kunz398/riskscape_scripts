import json
import mimetypes
import os
import sys
from pathlib import Path

import requests

from latest_cyclone import get_latest_cyclone

BASE_URL = "https://riskscape.nz"
PROJECT = "niwa/partner-training/kunal"
PROJECT_URL = f"{BASE_URL}/api/projects/by-full-slug/{PROJECT}"

USERNAME = "TOKEN"
API_KEY = "??"

MODEL_NAME = "tc"
OUTPUT_DIR = Path("output")
CHUNK_SIZE = 1024 * 1024 # 1mb append

session = requests.Session()
session.auth = (USERNAME, API_KEY)
session.headers["Accept"] = "application/json"


# print the HTTP status of every API call
def log_status(r, *args, **kwargs):
    print(f"    HTTP {r.status_code} {r.request.method} {r.url}")

session.hooks["response"].append(log_status)


def check(r, what):
    if not r.ok:
        sys.exit(f"[{what}] failed: {r.status_code} {r.text}")
    return r


def report(r, what):
    """Like check() but doesn't exit - returns True/False."""
    ok = r.ok
    print(f"[{what}] {'ok' if ok else 'FAILED'}: {r.status_code} {r.text[:300]}")
    return ok


# 1. Create the model run record (Platform does NOT run anything)
def createRun(cyclone_name, issue_time):
    body = {
        "externalModelId": MODEL_NAME,
        "managed": False,
        "parameters": {
            "track": {
                "label": "Track",
                "value": f"Cyclone-Tracks/{cyclone_name}/{issue_time}.geojson",
            },
            "cyclone_name": {"label": "Cyclone name", "value": cyclone_name},
            "issue_time": {"label": "Issue time", "value": issue_time},
        },
    }
    r = check(session.post(f"{PROJECT_URL}/runs/new", json=body, timeout=60), "create run")
    run = r.json()
    with open("model_run_response.txt", "w") as f:
        json.dump(run, f, indent=2)
    print(f"[run] created id={run['id']} state={run['state']}")
    return f"{BASE_URL}/api/model-runs/by-id/{run['id']}"


# 2. Create an output, 3. send content in chunks, 4. mark the output complete
def publishOutput(run_url, path):
    name = path.stem
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".csv":
        media_type = "application/csv"

    # 2. create empty output - response gives us its uri
    r = session.post(f"{run_url}/output",
                     json={"name": name, "mediaType": media_type}, timeout=60)
    if not report(r, f"create output {name}"):
        return False

    output_url = BASE_URL + r.json()["uri"]

    # 3. send content in chunks to {uri}/content
    appended = True
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            r = session.post(f"{output_url}/content", data=chunk,
                             headers={"Content-Type": "application/octet-stream"},
                             timeout=120)
            if not report(r, f"content {name}"):
                appended = False
                break

    # 4. say we are done with this output (always, so it isn't left open)
    r = session.post(f"{output_url}/complete", timeout=60)
    completed = report(r, f"complete output {name}")

    if completed:
        size = r.json().get("sizeBytes")
        print(f"[output] {name} ({media_type}) <- {path}  sizeBytes={size}")
    return appended and completed


# 5.  done with the model - it should move to finished/completed
def completeRun(run_url):
    return report(session.post(f"{run_url}/complete", timeout=60), "complete run")


if __name__ == "__main__":
    files = sorted(p for p in OUTPUT_DIR.iterdir() if p.is_file()) if OUTPUT_DIR.is_dir() else []
    if not files:
        sys.exit(f"No output files found in {OUTPUT_DIR}/ - run the model locally first")

    cyclone = get_latest_cyclone(save_to=None)
    print(f"[cyclone] {cyclone.name} issued {cyclone.issue_time}")

    run_url = createRun(cyclone.name, cyclone.issue_time)

    all_ok = True
    try:
        for path in files:
            if not publishOutput(run_url, path):
                all_ok = False
    finally:
        # always close the run, even if an output failed or something crashed
        if not completeRun(run_url):
            all_ok = False

    if not all_ok:
        sys.exit("[done] finished with errors - see FAILED lines above")
    print("[done] all outputs published and run completed")