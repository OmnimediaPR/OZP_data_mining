"""
summarize_inventory.py — shrne data/nzip/_inventory.json do přehledné tabulky.

Říká nám:
  • Kolik datasetů má `rok` / `rok_*` sloupec → kandidáti pro time-series parser
  • Které mají nejdelší časovou řadu
  • Distribuci podle kategorií
  • Návrh top datasetů pro F2b curated parser
"""

import json
from collections import Counter
from pathlib import Path

INV_PATH = Path(__file__).parent.parent / "data" / "nzip" / "_inventory.json"


def main():
    if not INV_PATH.exists():
        print(f"CHYBA: {INV_PATH} neexistuje.")
        return

    inv = json.loads(INV_PATH.read_text())
    datasets = inv["datasets"]
    total = inv["total"]

    print(f"=== F2 inventory — souhrn {total} datasetů ===\n")

    # Status breakdown
    print("Stav stahování:")
    for s, c in sorted(inv["by_status"].items(), key=lambda x: -x[1]):
        print(f"  {c:4d}  {s}")

    ok = [d for d in datasets if d.get("status") == "ok"]
    print(f"\n=== {len(ok)} úspěšně naparsovaných ===")

    # Year column coverage
    with_year = [d for d in ok if d.get("year_column")]
    without_year = [d for d in ok if not d.get("year_column")]
    print(f"\nSloupec rok / rok_*:")
    print(f"  {len(with_year):4d}  má rozpoznatelný roční sloupec")
    print(f"  {len(without_year):4d}  bez ročního sloupce (možná cross-tab nebo per-pacient)")

    # Rok column names distribution
    year_cols = Counter(d["year_column"] for d in with_year if d.get("year_column"))
    print(f"\n  Konkrétní názvy ročních sloupců:")
    for col, c in year_cols.most_common():
        print(f"    {c:4d}× {col}")

    # Delka casove rady (top 10)
    print(f"\n=== Top 10 datasetů s nejdelší časovou řadou ===")
    with_range = [d for d in with_year if d.get("year_range")]
    with_range.sort(
        key=lambda d: (d["year_range"][1] - d["year_range"][0]), reverse=True
    )
    for d in with_range[:10]:
        r = d["year_range"]
        years_span = r[1] - r[0] + 1
        print(f"  {years_span:3d} let ({r[0]}-{r[1]})  {d['id'][:60]}")

    # Kategorie
    print(f"\n=== Pokrytí podle kategorií (mezi OK) ===")
    cats = Counter(d.get("category") for d in ok)
    for cat, c in cats.most_common():
        print(f"  {c:3d}  {cat}")

    # Selhání / přeskočené
    failed = [d for d in datasets if d.get("status") != "ok"]
    if failed:
        print(f"\n=== {len(failed)} neúspěšných ({inv['by_status']}) ===")
        by_status = {}
        for d in failed:
            by_status.setdefault(d["status"], []).append(d)
        for status, items in by_status.items():
            print(f"\n  [{status}] ({len(items)})")
            for d in items[:5]:
                err = d.get("error", "")[:80]
                print(f"    {d['id'][:55]}  {err}")
            if len(items) > 5:
                print(f"    … a dalších {len(items) - 5}")

    # F2b kandidáti: malé datasety s `rok` a krátkou řadou → snadno curatable
    print(f"\n=== Návrh top 20 kandidátů pro F2b (curated parser) ===")
    print("(s rokem, ≤ 50k řádků, ≥ 5 let dat — snadná curation, malý objem)")
    candidates = [
        d for d in with_range
        if d.get("rows_scanned", 0) < 50_000
        and not d.get("rows_truncated")
        and (d["year_range"][1] - d["year_range"][0]) >= 4
    ]
    candidates.sort(key=lambda d: -(d["year_range"][1] - d["year_range"][0]))
    for d in candidates[:20]:
        r = d["year_range"]
        years_span = r[1] - r[0] + 1
        print(f"  {years_span:3d} let ({r[0]}-{r[1]})  "
              f"{d['rows_scanned']:>7,} řádků  {d['id'][:55]}")
    print(f"\nCelkem kandidátů: {len(candidates)}")


if __name__ == "__main__":
    main()
