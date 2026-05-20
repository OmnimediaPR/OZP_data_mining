"""
sync_nzip_curated.py — kurátorovaná synchronizace dat z NZIP otevřených dat

Cíleně vybrané datasety z NZIP otevřených dat (mimo NKIS kardio a NOR onko),
parsované s lidsky popsanými metadaty pro Datový brief.

Na rozdíl od sync_nzip.py (který dělá inventory všech 207 NZIP datasetů
s automatickým parsováním struktur), tento skript:
- vybírá konkrétní zajímavé datasety
- pro každý definuje year_col + metric_col + lidský popis bez zkratek
- agreguje metric_col per rok (sum) a ukládá jako brief-ready JSON

Spouští se přes GitHub Actions (viz .github/workflows/sync-nzip-curated.yml)
nebo ručně:    python scripts/sync_nzip_curated.py

Závislosti:    pip install requests
"""

import csv
import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import requests

OUT_DIR = Path(__file__).parent.parent / "data" / "nzip_curated"

# Definice kurátorovaných datasetů. Per dataset:
#   data_url, source_url (NZIP stránka), year_col, metric_col,
#   plus všechna lidsky popsaná pole (human_name, description, ...).
DATASETS = {
    "tuberkuloza_incidence": {
        "label": "Tuberkulóza — incidence",
        "human_name": "Tuberkulóza",
        "description": "Bakteriální infekční nemoc, typicky postihující plíce. V Česku patří k onemocněním, která byla historicky velmi rozšířená, dnes je výskyt nízký, ale neopomíjený — vyžaduje dlouhodobou léčbu a sledování.",
        "code": "A15–A19",
        "source": "Registr tuberkulózy (ÚZIS)",
        "source_type": "national",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově hlášených případů",
        "relevant_for": [
            "infekční nemoci",
            "veřejné zdraví",
            "očkování",
            "migrace",
        ],
        "trend_context": "Dlouhodobý pokles odráží zlepšení životních podmínek, plošné očkování BCG (dnes již necelé) a moderní léčbu. V posledních letech může výskyt mírně kolísat v důsledku migrace a sociálních faktorů.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-30-RTBC/NR-30-01/Otevrena-data-NR-30-01-tuberkuloza-epidemiologie.csv",
        "source_url": "https://www.nzip.cz/data/2671-tuberkuloza-epidemiologie-otevrena-data",
        "year_col": "rok_hlaseni",
        "metric_col": "pripady",
        "agg_func": "sum",
    },
    "sebevrazdy_hospitalizace": {
        "label": "Pokusy o sebevraždu — hospitalizace",
        "human_name": "Hospitalizace pacientů po pokusu o sebevraždu",
        "description": "Roční počet hospitalizací pacientů, kteří byli přijati po pokusu o sebevraždu. Klíčový ukazatel duševního zdraví populace a dostupnosti psychiatrické péče.",
        "code": "X60–X84",
        "source": "Národní informační systém péče o duševní zdraví (ÚZIS)",
        "source_type": "national",
        "metric": "hospitalizace_rocni",
        "metric_label": "Roční počet hospitalizací",
        "relevant_for": [
            "duševní zdraví",
            "veřejné zdraví",
            "krizová intervence",
            "psychiatrická péče",
        ],
        "trend_context": "Vývoj odráží kombinaci sociálních faktorů (ekonomické krize, pandemie, krize bydlení), dostupnosti psychiatrické péče a rozšiřování center duševního zdraví. Sledování pokusů o sebevraždu doplňuje statistiku dokonaných sebevražd v ČSÚ.",
        "data_url": "https://datanzis.uzis.gov.cz/data/OIS-04-NISDZ/OIS-04-18/Otevrena-data-OIS-04-18-hospitalizace-pacientu-pokus-o-sebevrazdu.csv",
        "source_url": "https://www.nzip.cz/data/2664-hospitalizace-pacientu-pokus-o-sebevrazdu-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_hospitalizaci",
        "agg_func": "sum",
    },
    "autismus_deti_incidence": {
        "label": "Děti a mladiství s poruchami autistického spektra — incidence",
        "human_name": "Děti a mladiství s poruchami autistického spektra",
        "description": "Roční počet dětí a mladistvých s diagnostikovanou poruchou autistického spektra. Zahrnuje dětský autismus, atypický autismus, Aspergerův syndrom a další pervazivní vývojové poruchy.",
        "code": "F84",
        "source": "Národní informační systém péče o duševní zdraví (ÚZIS)",
        "source_type": "national",
        "metric": "pacienti_rocni",
        "metric_label": "Roční počet pacientů",
        "relevant_for": [
            "duševní zdraví",
            "dětská psychiatrie",
            "vývojové poruchy",
            "vzdělávání",
        ],
        "trend_context": "Nárůst odráží především lepší záchyt — rozšířené screeningové nástroje, vyšší informovanost rodičů a pediatrů, dostupnost specializované diagnostiky. Reálná prevalence poruch autistického spektra je v populaci stabilní, ale dříve byla velká část případů nediagnostikovaná.",
        "data_url": "https://datanzis.uzis.gov.cz/data/OIS-04-NISDZ/OIS-04-17/Otevrena-data-OIS-04-17-deti-a-mladistvi-poruchy-autistickeho-spektra.csv",
        "source_url": "https://www.nzip.cz/data/2663-deti-a-mladistvi-poruchy-autistickeho-spektra-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_pacientu",
        "agg_func": "sum",
    },
    "pohlavni_nemoci_incidence": {
        "label": "Pohlavní nemoci — incidence",
        "human_name": "Pohlavní nemoci v ČR",
        "description": "Roční počet hlášených případů pohlavně přenosných nemocí (například syfilis, kapavka, chlamydie). Patří k nejdéle sledovaným epidemiologickým ukazatelům v ČR.",
        "code": "A50–A64",
        "source": "Registr pohlavních nemocí (ÚZIS)",
        "source_type": "national",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet hlášených případů",
        "relevant_for": [
            "infekční nemoci",
            "sexuální zdraví",
            "veřejné zdraví",
            "prevence",
        ],
        "trend_context": "Vývoj odráží změny v sexuálním chování, dostupnost testování a osvětu. V posledních letech v Česku narůstá syfilis a kapavka, zejména u mladších věkových skupin a v některých populačních podskupinách.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-29-RPN/NR-29-01/Otevrena-data-NR-29-01-pohlavni-nemoci.csv",
        "source_url": "https://www.nzip.cz/data/2639-pohlavni-nemoci-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_pripadu",
        "agg_func": "sum",
    },
    "astma_dispenzarizovani": {
        "label": "Bronchiální astma — dispenzarizovaní pacienti",
        "human_name": "Pacienti s bronchiálním astmatem",
        "description": "Roční počet pacientů dispenzarizovaných (dlouhodobě sledovaných) s bronchiálním astmatem. Patří k nejčastějším chronickým onemocněním dýchacího ústrojí.",
        "code": "J45",
        "source": "Národní registr hrazených zdravotních služeb (ÚZIS)",
        "source_type": "national",
        "metric": "prevalence_rocni",
        "metric_label": "Roční počet sledovaných pacientů",
        "relevant_for": [
            "chronická onemocnění",
            "alergologie",
            "kvalita ovzduší",
            "dětské zdraví",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, zhoršující se kvalitu ovzduší ve městech, vyšší prevalenci alergií u dětí a lepší záchyt díky moderní spirometrii. Moderní léčba (inhalační kortikosteroidy, biologická léčba) umožňuje většině pacientů žít plnohodnotný život.",
        "data_url": "https://data.mzcr.cz/data/distribuce/458/Otevrena-data-NR-04-84-asthma-bronchiale.csv",
        "source_url": "https://www.nzip.cz/data/2455-asthma-bronchiale-otevrena-data",
        "year_col": "rok_pece",
        "metric_col": "pocet",
        "agg_func": "sum",
    },
}


def download_csv(url: str) -> Path | None:
    """Stáhne CSV streamovaně do tempfile. Vrací cestu nebo None při chybě."""
    try:
        print(f"  Stahuji {url} ...")
        r = requests.get(
            url,
            timeout=120,
            stream=True,
            headers={"User-Agent": "Omnimedia-NZIP-Curated/1.0 (PR research)"},
        )
        r.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False)
        size = 0
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                tmp.write(chunk)
                size += len(chunk)
        tmp.close()
        print(f"  Staženo {size/1024:.1f} KB do {tmp.name}")
        return Path(tmp.name)
    except Exception as e:
        print(f"  CHYBA při stahování: {e}", file=sys.stderr)
        return None


def aggregate_by_year(csv_path: Path, year_col: str, metric_col: str, agg_func: str) -> list:
    """Agreguje metric_col per year_col. agg_func: 'sum' nebo 'count'."""
    sums: dict[int, float] = {}

    # Auto-detekce kódování (ÚZIS používá UTF-8 nebo Windows-1250).
    with csv_path.open("rb") as f:
        head = f.read(4096)
    encoding = "utf-8"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        encoding = "cp1250"

    with csv_path.open(encoding=encoding, newline="") as f:
        # Auto-detekce oddělovače.
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        yr_col = cols_lower.get(year_col.lower())
        mc_col = cols_lower.get(metric_col.lower())

        if not yr_col or not mc_col:
            raise ValueError(
                f"CSV neobsahuje očekávané sloupce '{year_col}' / '{metric_col}'. "
                f"Nalezené: {reader.fieldnames}"
            )

        for row in reader:
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if not (1950 <= year <= 2030):
                continue

            if agg_func == "count":
                sums[year] = sums.get(year, 0) + 1
            else:  # sum
                try:
                    value = float(row[mc_col])
                except (ValueError, TypeError):
                    continue
                sums[year] = sums.get(year, 0) + value

    return [{"year": y, "value": int(sums[y]) if sums[y].is_integer() else round(sums[y], 1)} for y in sorted(sums.keys())]


def compute_meta(series: list) -> dict:
    """Trend, delta, peak — rolling 3-letý průměr pro stabilitu."""
    if not series or len(series) < 2:
        return {"trend": "unknown", "delta": 0, "peakYear": None}

    if len(series) >= 6:
        first_value = sum(p["value"] for p in series[:3]) / 3
        last_value = sum(p["value"] for p in series[-3:]) / 3
    else:
        first_value = series[0]["value"]
        last_value = series[-1]["value"]

    if first_value == 0:
        delta = 0
    else:
        delta = round(((last_value - first_value) / first_value) * 100)

    if delta > 10:
        trend = "up"
    elif delta < -10:
        trend = "down"
    else:
        trend = "plateau"

    peak = max(series, key=lambda r: r["value"])
    return {"trend": trend, "delta": delta, "peakYear": peak["year"]}


def sync_one(ds_id: str, cfg: dict) -> str:
    print(f"\n[{ds_id}] {cfg['label']} ({cfg['code']})")

    csv_path = download_csv(cfg["data_url"])
    if csv_path is None:
        return "failed"

    try:
        series = aggregate_by_year(
            csv_path, cfg["year_col"], cfg["metric_col"], cfg.get("agg_func", "sum")
        )
        if not series:
            print("  CHYBA: žádná data po agregaci", file=sys.stderr)
            return "failed"
    except Exception as e:
        print(f"  CHYBA při parsování: {e}", file=sys.stderr)
        return "failed"
    finally:
        try:
            csv_path.unlink()
        except OSError:
            pass

    meta = compute_meta(series)

    out = {
        "id": ds_id,
        "label": cfg["label"],
        "human_name": cfg["human_name"],
        "description": cfg["description"],
        "code": cfg["code"],
        "source": cfg["source"],
        "source_type": cfg["source_type"],
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
        "data_url": cfg["data_url"],
        "source_url": cfg["source_url"],
    }

    out_path = OUT_DIR / f"{ds_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(
        f"  OK: {len(series)} let dat, delta {meta['delta']:+}%, "
        f"uloženo do {out_path.relative_to(OUT_DIR.parent.parent)}"
    )
    return "ok"


def main():
    print(f"NZIP curated sync — start v {datetime.now().isoformat()}")

    results: dict[str, str] = {}
    for ds_id, cfg in DATASETS.items():
        results[ds_id] = sync_one(ds_id, cfg)

    ok = [k for k, v in results.items() if v == "ok"]
    failed = [k for k, v in results.items() if v == "failed"]

    print("\n=== NZIP curated sync — hotovo ===")
    print(f"  OK ({len(ok)}): {', '.join(ok) if ok else '—'}")
    print(f"  Selhalo ({len(failed)}): {', '.join(failed) if failed else '—'}")

    if not ok:
        sys.exit(1)
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
