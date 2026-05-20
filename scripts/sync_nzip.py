"""
sync_nzip.py — Fáze 2 NZIP bulk discovery (exploratory inventory)

Stáhne CSV (i .csv.gz) pro datasety z `data/discovered_datasets.json` a vyextrahuje
strukturu (sloupce, počet řádků, rozsah roků, numerické metriky a jejich statistiky).
Cíl: pochopit strukturu napříč 207 datasety NZIP, ne generovat brief-ready JSON.

Výstup:
  data/nzip/_inventory.json — pole záznamů { id, status, columns, rows, year_range,
                              numeric_columns[{name, sum, min, max}], errors }

Spouštění:
  python scripts/sync_nzip.py                 # zpracuje vzorek z SAMPLE_IDS níže
  python scripts/sync_nzip.py --all           # zpracuje všechny s csv_url (kromě .7z)
  python scripts/sync_nzip.py --ids id1,id2   # zpracuje konkrétní IDs

Závislosti: pip install requests
"""

import argparse
import csv
import gzip
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DISCOVERED_PATH = ROOT / "data" / "discovered_datasets.json"
OUT_DIR = ROOT / "data" / "nzip"
INVENTORY_PATH = OUT_DIR / "_inventory.json"

# Vzorek 9 datasetů napříč kategoriemi pro první test F2.
# Pokrývá: NRHZS, NICDZ, rodičky, mortalita, NKIS, NOR, diabetes, hospitalizace, screening.
SAMPLE_IDS = [
    "2760-hromadne-vyrabene-lecive-pripravky-1-uroven-atc-otevrena-data",
    "2665-pacienti-centra-dusevniho-zdravi-otevrena-data",
    "2591-rodicky-cesko-otevrena-data",
    "2695-mortalita-vek-pohlavi-okresy-dlouhodoby-vyvoj-otevrena-data",
    "2705-cevni-mozkova-prihoda-otevrena-data",
    "1772-novotvary-preziti-otevrena-data",
    "1768-diabetes-mellitus-epidemiologie-otevrena-data",
    "2521-hospitalizacni-pripady-dlouhodoba-casova-rada-otevrena-data",
    "2326-mamografie-pokryti-uplne-trilete-otevrena-data",
]

REQUEST_DELAY_SEC = 0.5  # ohleduplnost vůči ÚZIS serveru
HTTP_TIMEOUT_SEC = 90
USER_AGENT = "Omnimedia-NZIP-Sync/0.1 (PR research, dataset discovery)"
# Inventory analyzuje strukturu, ne kompletní data → stačí vzorek.
# Některé NRHZS soubory mají miliony řádků; full pass by zabral hodiny.
MAX_ROWS_SCAN = 200_000


class _PrependedTextStream:
    """Iterable text stream — nejdřív emituje řádky z přečtené hlavičky, pak ze zbytku."""
    def __init__(self, head: str, rest):
        self._buffer = head
        self._rest = rest
        self._done_head = False

    def __iter__(self):
        return self

    def __next__(self):
        # csv.reader používá iter protocol — emituje řádek po řádku.
        # Sestavíme řádek až k '\n' z bufferu + dotahujeme z rest.
        while "\n" not in self._buffer:
            chunk = self._rest.read(8192) if not self._done_head else ""
            if not chunk:
                if self._buffer:
                    line, self._buffer = self._buffer, ""
                    return line
                raise StopIteration
            self._buffer += chunk
        nl = self._buffer.index("\n") + 1
        line = self._buffer[:nl]
        self._buffer = self._buffer[nl:]
        return line


def download_to_tempfile(url: str) -> tuple[str, int]:
    """Stáhne URL do tempfile (chunky 64 KB) a vrátí (cesta, velikost_bajtů).
    Volající má povinnost soubor po použití smazat (os.unlink)."""
    resp = requests.get(url, stream=True, timeout=HTTP_TIMEOUT_SEC,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(prefix="nzip_", suffix=".bin")
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
    finally:
        resp.close()
    return path, size


def open_local_csv(path: str, is_gz: bool):
    """Otevře lokální soubor (gz nebo plain) jako text-mode stream UTF-8."""
    binary = gzip.open(path, "rb") if is_gz else open(path, "rb")
    return io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline="")


def sniff_dialect(sample: str) -> csv.Dialect:
    """Auto-detekce CSV oddělovače (středník vs čárka)."""
    try:
        return csv.Sniffer().sniff(sample[:4096], delimiters=";,\t")
    except csv.Error:
        return csv.excel


def parse_int_safe(s):
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    # ÚZIS někdy používá čárku jako desetinný oddělovač
    s = s.replace(",", ".")
    try:
        v = float(s)
        if v.is_integer():
            return int(v)
        return v
    except (ValueError, TypeError):
        return None


def analyze_csv(text_stream) -> dict:
    """Vyextrahuje inventář CSV: sloupce, řádky, year_range, numerické metriky.
    Argument je text-mode stream (může to být velký soubor — čte se inkrementálně)."""
    # Pro sniff dialect potřebujeme vzorek z hlavičky, ale stream musí pokračovat.
    # Trik: přečteme prvních ~4 KB, sniffneme, pak iterujeme přes prepended_stream.
    head = text_stream.read(8192)
    dialect = sniff_dialect(head)
    # Spoj přečtenou hlavičku se zbytkem streamu
    combined = _PrependedTextStream(head, text_stream)
    reader = csv.DictReader(combined, dialect=dialect)
    columns = list(reader.fieldnames or [])
    if not columns:
        return {"error": "CSV nemá hlavičku"}

    # Najdi sloupec roku — preferuj přesné 'rok'/'year', jinak vezmi první sloupec
    # začínající 'rok_' (rok_porodu, rok_dg, rok_umrti, rok_diagnozy…).
    year_col = None
    for c in columns:
        if c.lower().strip() in ("rok", "year"):
            year_col = c
            break
    if year_col is None:
        for c in columns:
            cl = c.lower().strip()
            if cl.startswith("rok_") or cl in ("year_dg", "year_diagnosis"):
                year_col = c
                break

    rows_total = 0
    years_seen = set()
    truncated = False
    # Pro každý sloupec: počet ne-prázdných, kolik je numerických, suma, min, max
    col_stats = {c: {"non_empty": 0, "numeric_count": 0, "sum": 0.0,
                     "min": None, "max": None, "sample_values": set()}
                 for c in columns}

    for row in reader:
        rows_total += 1
        if rows_total > MAX_ROWS_SCAN:
            truncated = True
            break
        if year_col:
            y = parse_int_safe(row.get(year_col))
            if isinstance(y, int) and 1950 <= y <= 2030:
                years_seen.add(y)

        for c in columns:
            v = row.get(c)
            if v is None or str(v).strip() == "":
                continue
            col_stats[c]["non_empty"] += 1
            num = parse_int_safe(v)
            if num is not None and not isinstance(num, bool):
                col_stats[c]["numeric_count"] += 1
                col_stats[c]["sum"] += float(num)
                cur_min = col_stats[c]["min"]
                cur_max = col_stats[c]["max"]
                if cur_min is None or num < cur_min:
                    col_stats[c]["min"] = num
                if cur_max is None or num > cur_max:
                    col_stats[c]["max"] = num
            else:
                # ulož pár ukázek textových hodnot (do 5 unikátních)
                if len(col_stats[c]["sample_values"]) < 5:
                    col_stats[c]["sample_values"].add(str(v)[:60])

    # Roztřiď sloupce na numerické a textové podle podílu numerických hodnot
    numeric_cols = []
    text_cols = []
    for c, st in col_stats.items():
        if st["non_empty"] == 0:
            continue
        is_numeric = st["numeric_count"] / st["non_empty"] >= 0.9
        if is_numeric:
            numeric_cols.append({
                "name": c,
                "rows": st["non_empty"],
                "sum": st["sum"],
                "min": st["min"],
                "max": st["max"],
            })
        else:
            text_cols.append({
                "name": c,
                "rows": st["non_empty"],
                "samples": sorted(st["sample_values"]),
            })

    return {
        "columns": columns,
        "rows_scanned": rows_total,
        "rows_truncated": truncated,
        "delimiter": dialect.delimiter,
        "year_column": year_col,
        "year_range": [min(years_seen), max(years_seen)] if years_seen else None,
        "years_count": len(years_seen),
        "numeric_columns": numeric_cols,
        "text_columns": text_cols,
    }


def find_dataset(discovered: list, ds_id: str) -> dict | None:
    for x in discovered:
        if x.get("id") == ds_id:
            return x
    return None


def process_one(meta: dict) -> dict:
    """Stáhne CSV pro jeden dataset a vrátí inventory záznam."""
    ds_id = meta["id"]
    url = meta.get("csv_url")
    record = {
        "id": ds_id,
        "title": meta.get("title"),
        "category": meta.get("category", {}).get("name"),
        "csv_url": url,
        "status": "pending",
    }

    if not url:
        record["status"] = "no_csv_url"
        return record

    if url.endswith(".7z"):
        record["status"] = "skipped_7z"
        record["note"] = "Formát 7z neumíme dekomprimovat bez py7zr."
        return record

    print(f"  [{ds_id[:60]}] stahuji…")
    tmp_path = None
    try:
        tmp_path, bytes_dl = download_to_tempfile(url)
        record["bytes"] = bytes_dl
    except Exception as e:
        record["status"] = "download_failed"
        record["error"] = str(e)[:300]
        print(f"    CHYBA stahování: {e}", file=sys.stderr)
        return record

    try:
        text = open_local_csv(tmp_path, is_gz=url.endswith(".gz"))
        analysis = analyze_csv(text)
        text.close()
        if "error" in analysis:
            record["status"] = "parse_failed"
            record["error"] = analysis["error"]
        else:
            record["status"] = "ok"
            record.update(analysis)
            yr = analysis.get("year_range")
            yr_str = f"{yr[0]}–{yr[1]}" if yr else "—"
            trunc = " (TRUNCATED)" if analysis.get("rows_truncated") else ""
            print(f"    OK: {analysis['rows_scanned']} řádků{trunc}, "
                  f"{len(analysis['columns'])} sloupců, "
                  f"roky {yr_str}, "
                  f"{len(analysis['numeric_columns'])} numerických")
    except Exception as e:
        record["status"] = "parse_failed"
        record["error"] = str(e)[:300]
        print(f"    CHYBA parsování: {e}", file=sys.stderr)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--all", action="store_true",
                        help="Zpracuj všechny datasety s csv_url (cca 200, ~15-30 min)")
    parser.add_argument("--ids", type=str,
                        help="Čárkou oddělený seznam ID (přepíše SAMPLE_IDS i --all)")
    args = parser.parse_args()

    if not DISCOVERED_PATH.exists():
        print(f"CHYBA: {DISCOVERED_PATH} neexistuje. Spusť nejdřív discover_nzip.py.",
              file=sys.stderr)
        sys.exit(1)

    discovered = json.loads(DISCOVERED_PATH.read_text())["datasets"]
    print(f"Discovered: {len(discovered)} datasetů celkem")

    # Vyber co zpracovat
    if args.ids:
        wanted_ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    elif args.all:
        wanted_ids = [x["id"] for x in discovered if x.get("csv_url")]
    else:
        wanted_ids = SAMPLE_IDS

    print(f"Ke zpracování: {len(wanted_ids)} datasetů\n")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for i, ds_id in enumerate(wanted_ids, 1):
        meta = find_dataset(discovered, ds_id)
        if not meta:
            print(f"[{i}/{len(wanted_ids)}] {ds_id}: NENALEZEN v discovered_datasets.json",
                  file=sys.stderr)
            results.append({"id": ds_id, "status": "not_in_discovered"})
            continue

        print(f"[{i}/{len(wanted_ids)}] {meta.get('title', ds_id)[:80]}")
        rec = process_one(meta)
        results.append(rec)
        if i < len(wanted_ids):
            time.sleep(REQUEST_DELAY_SEC)

    # Sumarizace
    by_status = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    print(f"\n=== NZIP F2 inventory — hotovo ===")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")

    inventory = {
        "generated_at": datetime.now().isoformat(),
        "total": len(results),
        "by_status": by_status,
        "datasets": results,
    }
    INVENTORY_PATH.write_text(json.dumps(inventory, ensure_ascii=False, indent=2))
    print(f"\nUloženo do {INVENTORY_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
