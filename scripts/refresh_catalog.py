#!/usr/bin/env python3
"""Ověří, že všechny csv_url v data/catalog.json jsou dostupné, a aktualizuje last_seen."""

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"
TIMEOUT_S = 30
RANGE_BYTES = 8191
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def check_url(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{RANGE_BYTES}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if resp.status in (200, 206):
                return True, f"HTTP {resp.status}"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"network: {e.reason}"
    except TimeoutError:
        return False, f"timeout po {TIMEOUT_S}s"


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    today = date.today().isoformat()

    ok_count = 0
    fail_count = 0
    changed = False

    for ds in catalog["datasets"]:
        ds_id = ds["id"]
        ok, info = check_url(ds["csv_url"])
        if ok:
            if ds.get("last_seen") != today:
                ds["last_seen"] = today
                changed = True
            print(f"  OK   {ds_id:30s} {info}")
            ok_count += 1
        else:
            print(f"  FAIL {ds_id:30s} {info}  ({ds['csv_url']})", file=sys.stderr)
            fail_count += 1

    if changed:
        catalog["updated"] = today
        CATALOG_PATH.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n→ catalog.json přepsán (updated = {today})")
    else:
        print("\n→ catalog.json beze změny")

    print(f"\nSouhrn: {ok_count} OK, {fail_count} FAIL z {len(catalog['datasets'])} datasetů")
    return 0


if __name__ == "__main__":
    sys.exit(main())
