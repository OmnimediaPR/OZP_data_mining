"""
sync_nkis.py — synchronizace dat z Národního kardiologického informačního systému (NKIS)

Stahuje CSV "Otevřená data" ze stránek ÚZIS ČR, parsuje je
a ukládá jako JSON soubory do data/nkis/.

Spouští se přes GitHub Actions 1× měsíčně (viz .github/workflows/sync-nkis.yml)
nebo ručně:    python scripts/sync_nkis.py

Závislosti:    pip install requests
"""

import csv
import io
import json
import sys
from pathlib import Path
from datetime import datetime
import requests

# Adresář, kam ukládat JSON výstupy (relativně k umístění tohoto skriptu)
OUT_DIR = Path(__file__).parent.parent / "data" / "nkis"

# Definice datasetů — CSV "Otevřená data" z ÚZIS NKIS.
# url=None znamená "URL zatím nedoplněna" → dataset se přeskočí (skipped, ne failed).
# Doplň URL z NZIP stránek (sekce "Distribuce datové sady" → tlačítko "Stáhnout"):
#   hyp → https://www.nzip.cz/data/1663-hypertenze-otevrena-data
#   hf  → https://www.nzip.cz/data/1664-srdecni-selhani-epidemiologie-otevrena-data
#   kvo → https://www.nzip.cz/data/1666-kardiovaskularni-onemocneni-zatez-ceska-republika-otevrena-data
DATASETS = {
    "aim": {
        "label": "Akutní infarkt myokardu",
        "human_name": "Akutní infarkt myokardu",
        "description": "Akutní ucpání věnčité tepny — život ohrožující stav.",
        "code": "I21-I22",
        "url": "https://datanzis.uzis.gov.cz/data/OIS-01-NKIS/OIS-01-14/Otevrena-data-OIS-01-14-akutni-infarkt-myokardu.csv",
        "metric": "incidence_rocni",
        "metric_label": "Roční incidence v ČR",
        "relevant_for": ["kardiovaskulární prevence", "cholesterol", "kouření", "životní styl"],
        "trend_context": "Pokles odráží 23 katetrizačních center, statiny v primární prevenci, klesající kouření.",
    },
    "cmp": {
        "label": "Cévní mozková příhoda",
        "human_name": "Cévní mozková příhoda",
        "description": "Akutní porucha krevního zásobení mozku.",
        "code": "I60-I64",
        "url": "https://datanzis.uzis.gov.cz/data/OIS-01-NKIS/OIS-01-15/Otevrena-data-OIS-01-15-cevni-mozkova-prihoda.csv",
        "metric": "incidence_rocni",
        "metric_label": "Roční incidence v ČR",
        "relevant_for": ["prevence cévních mozkových příhod", "vysoký krevní tlak", "fibrilace síní", "neurologie"],
        "trend_context": "Pokles podobný jako u akutního infarktu myokardu — díky síti specializovaných center pro léčbu cévních mozkových příhod od roku 2011.",
    },
    "hyp": {
        "label": "Hypertenze (léčená)",
        "human_name": "Vysoký krevní tlak (hypertenze)",
        "description": "Chronicky zvýšený krevní tlak — hlavní rizikový faktor srdečních a mozkových příhod.",
        "code": "I10",
        "url": None,  # TODO: doplnit z NZIP 1663
        "metric": "prevalence_historie",
        "metric_label": "Léčení pacienti v ČR",
        "relevant_for": ["prevence", "životní styl", "cholesterol", "stárnutí populace"],
        "trend_context": "Cca 20 % populace ČR léčeno; u osob 65+ až 60 % populace.",
    },
    "hf": {
        "label": "Srdeční selhání",
        "human_name": "Srdeční selhání",
        "description": "Stav, kdy srdce nedokáže dostatečně pumpovat krev — často chronický důsledek prodělaného infarktu nebo dlouhodobého vysokého tlaku.",
        "code": "I50",
        "url": None,  # TODO: doplnit z NZIP 1664
        "metric": "prevalence_historie",
        "metric_label": "Léčení pacienti v ČR",
        "relevant_for": ["chronická onemocnění", "stárnutí populace", "kvalita života"],
        "trend_context": "Chronický důsledek prodělaných infarktů a hypertenze. Strmý růst je daň za úspěch akutní péče.",
    },
    "kvo": {
        "label": "Zátěž KVO v populaci ČR",
        "human_name": "Kardiovaskulární onemocnění (souhrn)",
        "description": "Souhrn všech srdečních a cévních diagnóz — pohled na celkovou zátěž populace.",
        "code": "I00-I99",
        "url": None,  # TODO: doplnit z NZIP 1666
        "metric": "prevalence_historie",
        "metric_label": "Pacienti s kardiovaskulárním onemocněním v ČR",
        "relevant_for": ["celkový kontext", "trend kardiovaskulárních onemocnění v ČR", "prevence"],
        "trend_context": "Souhrnný pohled na zátěž populace — zahrnuje nové i existující případy napříč všemi srdečními a cévními onemocněními.",
    },
}

# Globální názvy sloupců, které jsou stejné napříč datasety. Hledá se case-insensitive.
# Konkrétní metrický sloupec (počet osob/případů) je per-dataset — viz pole "metric"
# v DATASETS. ÚZIS CSV obsahuje více ukazatelů (incidence_rocni, prevalence_historie,
# incidence_primarni, mortalita_specificka) a podle datasetu vybíráme ten správný.
YEAR_COL = "rok"
# Filtr na ne-prázdný okres bydliště — aby se nezapočítaly subtotal/souhrnné řádky.
FILTER_COL = "okres_bydliste"


def download_csv(url: str) -> str | None:
    """Stáhne CSV ze zadané URL a vrátí jako text. Vrací None při chybě."""
    try:
        print(f"  Stahuji {url}...")
        response = requests.get(url, timeout=60, headers={
            "User-Agent": "Omnimedia-NKIS-Sync/1.0 (PR research)"
        })
        response.raise_for_status()
        # ÚZIS CSV bývá UTF-8, občas i Windows-1250 — necháme requests detekovat.
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return response.text
    except Exception as e:
        print(f"  CHYBA při stahování: {e}", file=sys.stderr)
        return None


def parse_csv(csv_text: str, metric: str) -> list:
    """Vyextrahuje časovou řadu (year, value) z CSV textu.

    CSV obsahuje stratifikované řádky (rok × pohlaví × věk × kraj × okres).
    Pro celorepublikový roční součet sečteme všechny řádky daného roku,
    ale jen ty s vyplněným okresem (vyhodí subtotal řádky, kde okres chybí).

    Parametr `metric` = název sloupce s počtem (např. "incidence_rocni",
    "prevalence_historie") — různý dataset má různý ukazatel.
    """
    # Auto-detekce oddělovače (středník vs čárka). ÚZIS používá obvykle středník.
    sample = csv_text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)

    if not reader.fieldnames:
        raise ValueError("CSV nemá hlavičku")

    # Najdi jména sloupců case-insensitive (toleruje "Rok" i "rok").
    cols_lower = {c.lower(): c for c in reader.fieldnames}
    year_col = cols_lower.get(YEAR_COL.lower())
    value_col = cols_lower.get(metric.lower())
    filter_col = cols_lower.get(FILTER_COL.lower())

    if not year_col or not value_col:
        raise ValueError(
            f"CSV neobsahuje očekávané sloupce '{YEAR_COL}' / '{metric}'. "
            f"Nalezené sloupce: {reader.fieldnames}"
        )

    sums = {}  # rok -> součet hodnot napříč stratifikacemi
    for row in reader:
        # Filtruj subtotal řádky (kde okres není vyplněn). Pokud filtr sloupec neexistuje,
        # přeskočíme tuto kontrolu — bereme všechny řádky.
        if filter_col and not (row.get(filter_col) or "").strip():
            continue

        try:
            year = int(row[year_col])
        except (ValueError, TypeError):
            continue
        if not (2000 <= year <= 2030):
            continue

        try:
            value = int(row[value_col])
        except (ValueError, TypeError):
            continue

        sums[year] = sums.get(year, 0) + value

    return [{"year": y, "value": sums[y]} for y in sorted(sums.keys())]


def compute_meta(series: list) -> dict:
    """Spočítá meta-informace pro frontend (trend, delta, peak)."""
    if not series or len(series) < 2:
        return {"trend": "unknown", "delta": 0, "peakYear": None}

    first = series[0]
    last = series[-1]
    if first["value"] == 0:
        delta_pct = 0
    else:
        delta_pct = round(((last["value"] - first["value"]) / first["value"]) * 100)

    peak = max(series, key=lambda r: r["value"])

    if delta_pct > 10:
        trend = "up"
    elif delta_pct < -10:
        trend = "down"
    else:
        trend = "plateau"

    return {
        "trend": trend,
        "delta": delta_pct,
        "peakYear": peak["year"]
    }


def sync_one(dataset_id: str, cfg: dict) -> str:
    """Stáhne, naparsuje a uloží jeden dataset.

    Vrací: "ok" (úspěch), "skipped" (url=None) nebo "failed" (chyba stahování/parsování).
    """
    print(f"\n[{dataset_id}] {cfg['label']} ({cfg['code']})")

    if cfg["url"] is None:
        print(f"  PŘESKOČENO: URL zatím nedoplněna (TODO).")
        return "skipped"

    csv_text = download_csv(cfg["url"])
    if csv_text is None:
        return "failed"

    try:
        series = parse_csv(csv_text, cfg["metric"])
        if not series:
            print(f"  CHYBA: žádná použitelná data v CSV", file=sys.stderr)
            return "failed"
    except Exception as e:
        print(f"  CHYBA při parsování: {e}", file=sys.stderr)
        return "failed"

    meta = compute_meta(series)

    out = {
        "id": dataset_id,
        "label": cfg["label"],
        "human_name": cfg["human_name"],
        "description": cfg["description"],
        "code": cfg["code"],
        "source": "NRHZS / NKIS",
        "source_type": "national",
        "metric": cfg["metric"],
        "metric_label": cfg["metric_label"],
        "relevant_for": cfg["relevant_for"],
        "trend_context": cfg["trend_context"],
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "coverage": f"{series[0]['year']}–{series[-1]['year']}",
        "trend": meta["trend"],
        "delta": meta["delta"],
        "peakYear": meta["peakYear"],
        "data": series,
        "source_url": cfg["url"],
    }

    out_path = OUT_DIR / f"{dataset_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"  OK: {len(series)} let dat, delta {meta['delta']:+}%, "
          f"uloženo do {out_path.relative_to(OUT_DIR.parent.parent)}")
    return "ok"


def main():
    print(f"NKIS sync — start v {datetime.now().isoformat()}")

    results = {}
    for ds_id, cfg in DATASETS.items():
        results[ds_id] = sync_one(ds_id, cfg)

    ok = [k for k, v in results.items() if v == "ok"]
    skipped = [k for k, v in results.items() if v == "skipped"]
    failed = [k for k, v in results.items() if v == "failed"]

    print(f"\n=== NKIS sync — hotovo ===")
    print(f"  OK ({len(ok)}): {', '.join(ok) if ok else '—'}")
    print(f"  Přeskočeno ({len(skipped)}): {', '.join(skipped) if skipped else '—'}")
    print(f"  Selhalo ({len(failed)}): {', '.join(failed) if failed else '—'}")

    # Skript končí úspěšně, pokud aspoň jeden dataset prošel.
    if not ok:
        print("\nŽÁDNÝ DATASET NEPROŠEL. Pravděpodobné příčiny:", file=sys.stderr)
        print("  1. ÚZIS přejmenoval CSV soubory (zkontroluj URL v DATASETS)", file=sys.stderr)
        print("  2. ÚZIS server je dočasně nedostupný", file=sys.stderr)
        print("  3. Změnila se struktura CSV (sloupce rok / metrika / okres_bydliste)", file=sys.stderr)
        sys.exit(1)

    if failed:
        # Částečné selhání — vrátíme exit 2, aby workflow zalogoval varování,
        # ale úspěšné datasety se přesto commitnou.
        sys.exit(2)


if __name__ == "__main__":
    main()
