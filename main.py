import json
import os
import sys
import time

import requests

from latest_cyclone import get_latest_cyclone

BASE_URL = "https://riskscape.nz"
PROJECT = "niwa/partner-training/kunal"
PROJECT_URL = f"{BASE_URL}/api/projects/by-full-slug/{PROJECT}"

USERNAME = "TOKEN"
API_KEY = "??"

CYCLONE_URL = "https://pacific-disaster-api.spc.int/partner_api/v1/cyclone_track/{id}?format=json"
MODEL_NAME = "tc"
URL_PARAM = "cyclone_url"
OUT_GEOJSON = "cyclone_tracks.geojson"

session = requests.Session()
session.auth = (USERNAME, API_KEY)
session.headers["Accept"] = "application/json"


def ping():
    r = session.get(f"{BASE_URL}/api/ping", timeout=30)
    print(f"[ping] {r.status_code}: {r.text[:200]}")
    if r.status_code == 401:
        sys.exit("[ping] unauthorised - check RISKSCAPE_TOKEN")
    r.raise_for_status()


def uploadToPlatform(dataset, remote_path):
    r = session.put(
        f"{PROJECT_URL}/files/by-path/{remote_path}",
        data=json.dumps(dataset).encode("utf-8"),
        headers={"Content-Type": "application/geo+json"},
        timeout=120,
    )
    if r.status_code != 204:
        sys.exit(f"[upload] failed: {r.status_code} {r.text}")
    print(f"[upload] -> {remote_path}")


def runModel(model_id, parameters):
    body = {
        "externalModelId": model_id,
        "managed": True,
        "parameters": parameters,
    }
    r = session.post(f"{PROJECT_URL}/runs/new", json=body, timeout=60)
    if not r.ok:
        sys.exit(f"[run] failed to start: {r.status_code} {r.text}")
    run = r.json()
    print(f"[run] started id={run['id']} state={run['state']}")
    return run["id"]


def pollRun(run_id, interval=5, timeout=1800):
    url = f"{BASE_URL}/api/model-runs/by-id/{run_id}"
    start = time.time()

    while True:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        run = r.json()

        if run.get("finished") is True:
            if run.get("state") == "FAILED":
                print(json.dumps(run, indent=2))
                sys.exit(f"[run] {run_id} FAILED")
            print(f"[run] {run_id} done: {run['state']}")
            return run

        if time.time() - start > timeout:
            sys.exit(f"[run] {run_id} timed out, still {run.get('state')}")

        print(f"[run] {run_id} {run.get('state')}... waiting {interval}s")
        time.sleep(interval)

def downloadOutputs(run_id, out_dir="downloads"):
    run_url = f"{BASE_URL}/api/model-runs/by-id/{run_id}"

    r = session.get(run_url, timeout=30)
    print(f"    HTTP {r.status_code} GET {run_url}")
    r.raise_for_status()
    run = r.json()

    outputs = run.get("outputs", [])
    if not outputs:
        print(f"[download] run {run_id} has no outputs")
        return

    folder = os.path.join(out_dir, str(run_id))
    os.makedirs(folder, exist_ok=True)

    for output in outputs:
        name = output["name"] if isinstance(output, dict) else output
        url = f"{run_url}/output/{name}/download"

        r = session.get(url, timeout=300, stream=True)
        print(f"    HTTP {r.status_code} GET {url}")
        if not r.ok:
            print(f"[download] {name} FAILED: {r.text[:200]}")
            continue

        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        print(f"[download] {name} -> {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":

    if not API_KEY:
        sys.exit("Set RISKSCAPE_TOKEN first: export RISKSCAPE_TOKEN=...")

    ping()

    try:
        cyclone = get_latest_cyclone(save_to=OUT_GEOJSON)
    except ValueError as e:
        print(f"[cyclone] skipping: {e}")
        sys.exit(0)

    print(f"[cyclone] {cyclone.cyclone_id} issued {cyclone.issue_time}")

    # remote_path = f"cyclones/{cyclone.cyclone_id}.geojson"
    # uploadToPlatform(cyclone.geometry, remote_path)

    run_id = runModel(
        MODEL_NAME,
        {
            URL_PARAM: {
                "label": f"Cyclone url ({cyclone.name} {cyclone.issue_time})",
                "value": f"'{CYCLONE_URL.format(id=cyclone.id)}'",
            }
        },
    )

    run = pollRun(run_id)
    print(f"[done] run {run_id} outputs: {run.get('outputs')}")

    # download  output
    downloadOutputs(run_id)