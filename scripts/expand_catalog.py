#!/usr/bin/env python3
"""Analytický krok pro rozšíření data/catalog.json.

Načte docs/discovery/discovered_datasets.json, vyhodí technické číselníky,
pro každý zbylý dataset fetchne začátek CSV (Range request, gzip-aware)
a vyplivne docs/discovery/dataset_headers.json se strukturou hlavičky
a pár ukázkovými řádky.

Žádný zápis do data/catalog.json — to je až další krok po vyhodnocení.
"""

import csv
import io
import json
import sys
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISCOVERED_PATH = ROOT / "docs" / "discovery" / "discovered_datasets.json"
OUTPUT_PATH = ROOT / "docs" / "discovery" / "dataset_headers.json"

# Kategorie, které vynecháváme (čistě technické číselníky a metadata).
SKIP_CATEGORIES = {
    "Číselníky: otevřená data",
    "Klasifikační systém CZ-DRG: otevřená data",
    "Národní zdravotnický informační portál: otevřená data",
    "Národní zdravotnický informační systém (NZIS): otevřená data",
    "Národní registr poskytovatelů zdravotních služeb: otevřená data",
}

FETCH_BYTES = 262143  # 256 KB stačí na hlavičku + desítky řádků i u větších CSV
TIMEOUT_S = 60
MAX_WORKERS = 8
SAMPLE_ROWS = 5

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_partial(url: str) -> tuple[bytes, str]:
    """Stáhne prvních FETCH_BYTES bajtů. Vrátí (data, info_or_error)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{FETCH_BYTES}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        data = resp.read()
        return data, f"HTTP {resp.status}"


def decompress_gzip_partial(data: bytes) -> bytes:
    """Inkrementálně dekomprimuje co nejvíc z neúplného gzip streamu."""
    decompressor = zlib.decompressobj(31)  # 31 = gzip + auto-detect
    out = bytearray()
    chunk = 16384
    for i in range(0, len(data), chunk):
        try:
            out.extend(decompressor.decompress(data[i:i + chunk]))
        except zlib.error:
            break
    return bytes(out)


def detect_delimiter(sample: str) -> str:
    """Vrátí ';' nebo ',' podle toho, který je v první řádce častější."""
    first_line = sample.split("\n", 1)[0]
    return ";" if first_line.count(";") >= first_line.count(",") else ","


def parse_csv_sample(text: str) -> tuple[str, list[str], list[list[str]]]:
    """Z textového výpisu vytáhne delimiter, hlavičku a SAMPLE_ROWS řádků."""
    # Normalizace konců řádků — csv.reader nesnese osamocené \r v polích.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    delimiter = detect_delimiter(normalized)
    reader = csv.reader(io.StringIO(normalized), delimiter=delimiter)
    rows = []
    try:
        for row in reader:
            rows.append(row)
            if len(rows) > SAMPLE_ROWS + 1:
                break
    except csv.Error as e:
        # Pokud i tak praskne (např. nevyvážené uvozovky), vrátíme co jsme stihli.
        rows.append([f"<csv_error: {e}>"])
    if not rows:
        return delimiter, [], []
    header = rows[0]
    sample = rows[1:SAMPLE_ROWS + 1]
    return delimiter, header, sample


def analyze_dataset(ds: dict) -> dict:
    out = {
        "id": ds["id"],
        "title": ds["title"],
        "description": ds.get("description", ""),
        "category_name": ds["category"]["name"],
        "source_url": ds["source_page_url"],
        "csv_url": ds["csv_url"],
        "keywords": ds.get("keywords", []),
        "update_date": ds.get("update_date"),
        "is_gzipped": ds["csv_url"].lower().endswith(".gz"),
        "fetch_status": "pending",
        "delimiter": None,
        "columns": [],
        "sample_rows": [],
        "encoding": None,
    }
    try:
        data, info = fetch_partial(ds["csv_url"])
    except urllib.error.HTTPError as e:
        out["fetch_status"] = f"http_error: {e.code}"
        return out
    except urllib.error.URLError as e:
        out["fetch_status"] = f"network_error: {e.reason}"
        return out
    except TimeoutError:
        out["fetch_status"] = "timeout"
        return out
    except Exception as e:  # noqa: BLE001
        out["fetch_status"] = f"other: {type(e).__name__}: {e}"
        return out

    if out["is_gzipped"]:
        raw = decompress_gzip_partial(data)
        if not raw:
            out["fetch_status"] = "gzip_decompress_empty"
            return out
    else:
        raw = data

    text = None
    for enc in ("utf-8", "windows-1250"):
        try:
            text = raw.decode(enc)
            out["encoding"] = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
        out["encoding"] = "utf-8 (with replacements)"

    delimiter, header, sample = parse_csv_sample(text)
    out["delimiter"] = delimiter
    out["columns"] = header
    out["sample_rows"] = sample
    out["fetch_status"] = "ok"
    return out


def main() -> int:
    discovered = json.loads(DISCOVERED_PATH.read_text(encoding="utf-8"))
    all_datasets = [d for d in discovered["datasets"] if d.get("csv_url")]
    keep = [d for d in all_datasets if d["category"]["name"] not in SKIP_CATEGORIES]
    skip_count = len(all_datasets) - len(keep)

    print(f"Datasetů s CSV celkem: {len(all_datasets)}")
    print(f"  → vynecháno (technické): {skip_count}")
    print(f"  → ke zpracování: {len(keep)}")
    print(f"Fetch: až {FETCH_BYTES // 1024} KB per dataset, {MAX_WORKERS} paralelně\n")

    results = []
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(analyze_dataset, d): d for d in keep}
        for fut in as_completed(futures):
            result = fut.result()
            results.append(result)
            completed += 1
            status = result["fetch_status"]
            marker = "OK  " if status == "ok" else "FAIL"
            print(f"  [{completed:3d}/{len(keep)}] {marker} {result['id'][:60]:60s} {status if status != 'ok' else ''}")

    results.sort(key=lambda r: r["id"])

    ok = sum(1 for r in results if r["fetch_status"] == "ok")
    fail = len(results) - ok

    output = {
        "generated_at": json.loads(DISCOVERED_PATH.read_text(encoding="utf-8")).get("generated_at"),
        "fetched_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "total": len(results),
        "ok": ok,
        "fail": fail,
        "skip_categories": sorted(SKIP_CATEGORIES),
        "datasets": results,
    }
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n→ {OUTPUT_PATH.relative_to(ROOT)} ({ok} OK / {fail} FAIL z {len(results)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
