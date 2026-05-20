"""
sync_nor.py — synchronizace dat z Národního onkologického registru (NOR)

Stahuje "Otevřená data" Národního onkologického registru z data.mzcr.cz,
parsuje je a ukládá jako JSON soubory do data/nor/.

Na rozdíl od NKIS jsou NOR data **mikrodata** — jeden řádek CSV = jeden
případ rakoviny. Roční počet se počítá jako počet řádků dané diagnózy
(prefix podle MKN-10, např. "C50" pro rakovinu prsu) seskupený podle
roku diagnózy (rok_dg).

Spouští se přes GitHub Actions 1× měsíčně (viz .github/workflows/sync-nor.yml)
nebo ručně:    python scripts/sync_nor.py

Závislosti:    pip install requests
"""

import csv
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime
import requests

OUT_DIR = Path(__file__).parent.parent / "data" / "nor"

# Definice datasetů — každý odpovídá jednomu výstupnímu JSON v data/nor/.
# Jeden NOR CSV (např. NR-07-01 incidence) je sdílen mezi více onkologickými
# datasety — až jich bude víc, přidá se cache. Pro teď stahujeme per dataset.
DATASETS = {
    "prsa_incidence": {
        "label": "Rakovina prsu — incidence",
        "human_name": "Rakovina prsu",
        "description": "Zhoubný nádor prsní žlázy — nejčastější rakovina žen v Česku. Vzácně postihuje i muže (méně než 1 % případů).",
        "code": "C50",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "mamografický screening",
            "prevence rakoviny",
        ],
        "trend_context": "Nárůst odráží především stárnutí populace a lepší záchyt díky mamografickému screeningu zavedenému v Česku od roku 2002. Mortalita přitom dlouhodobě klesá — tedy víc žen rakovinu prsu má, ale méně z ní umírá.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
    },
    "plice_incidence": {
        "label": "Rakovina plic — incidence",
        "human_name": "Rakovina plic",
        "description": "Zhoubný nádor plicní tkáně — onkologický zabiják číslo jedna v Česku z hlediska úmrtnosti. Ve většině případů je spojen s kouřením.",
        "code": "C34",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kouření",
            "kvalita ovzduší",
            "prevence",
        ],
        "trend_context": "Dlouhodobý pokles u mužů odpovídá poklesu kouření. U žen incidence naopak roste, protože ženy začaly kouřit hromadně později. Po roce 2000 narůstá také podíl nekuřáků mezi pacienty.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
    },
    "prostata_incidence": {
        "label": "Rakovina prostaty — incidence",
        "human_name": "Rakovina prostaty",
        "description": "Zhoubný nádor předstojné žlázy — nejčastější rakovina mužů v Česku. Typicky se objevuje po šedesátém roce života.",
        "code": "C61",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "preventivní prohlídky",
            "stárnutí populace",
        ],
        "trend_context": "Strmý nárůst po roce 2000 odráží zavedení vyšetření krve na prostatický specifický antigen — díky němu se zachytí víc časných případů. Úmrtnost přitom roste mnohem pomaleji.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "rok_dg",
    },
    "kolorektum_incidence": {
        "label": "Rakovina tlustého střeva a konečníku — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku",
        "description": "Zhoubný nádor v tlustém střevě nebo konečníku — třetí nejčastější rakovina v Česku. Zahrnuje tračník, přechod mezi tračníkem a konečníkem a samotný konečník.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "životní styl",
            "prevence",
        ],
        "trend_context": "Česko mělo dlouhá léta nejvyšší úmrtnost na rakovinu tlustého střeva na světě. Pokles po roce 2000 souvisí s plošným screeningem (test na skryté krvácení do stolice a kolonoskopie) zavedeným v roce 2000 a rozšířeným v roce 2009.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
    },
    "melanom_incidence": {
        "label": "Zhoubný melanom kůže — incidence",
        "human_name": "Zhoubný melanom kůže",
        "description": "Nejnebezpečnější druh kožní rakoviny — vzniká z pigmentových buněk (melanocytů). Dá se úspěšně léčit, pokud se zachytí včas.",
        "code": "C43",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kůže",
            "ultrafialové záření",
            "prevence",
        ],
        "trend_context": "Strmý nárůst odráží především lepší záchyt — díky osvětě a preventivním prohlídkám u kožního lékaře — a změnu životního stylu (víc slunění, cestování do teplých zemí, solária). Úmrtnost roste mnohem pomaleji.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
    },
    "zaludek_incidence": {
        "label": "Rakovina žaludku — incidence",
        "human_name": "Rakovina žaludku",
        "description": "Zhoubný nádor žaludeční sliznice. Kdysi jedna z nejčastějších rakovin v Česku, dnes dlouhodobě ustupuje.",
        "code": "C16",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "životní styl",
            "prevence",
        ],
        "trend_context": "Dlouhodobý pokles odráží lepší kvalitu stravování (chlazení místo nasolování a uzení), čistou pitnou vodu a léčbu bakterie Helicobacter pylori, která stojí za velkou částí případů. V onkologii patří k tichým úspěchům posledních desetiletí.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "rok_dg",
    },
    "slinivka_incidence": {
        "label": "Rakovina slinivky břišní — incidence",
        "human_name": "Rakovina slinivky břišní",
        "description": "Zhoubný nádor slinivky břišní — jedna z onkologicky nejhůře léčitelných diagnóz. Pětileté přežití zůstává dlouhodobě pod deseti procenty.",
        "code": "C25",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "kouření",
            "obezita",
        ],
        "trend_context": "Počet nových případů se za posledních 45 let zhruba ztrojnásobil — odráží stárnutí populace, vyšší podíl obezity a kouření. Záchyt zůstává obtížný; nemoc se často projeví, až když je v pokročilém stadiu, protože slinivka leží hluboko v dutině břišní a první příznaky jsou nespecifické.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "rok_dg",
    },
    "mozek_incidence": {
        "label": "Zhoubný nádor mozku — incidence",
        "human_name": "Zhoubný nádor mozku",
        "description": "Zhoubný nádor mozkové tkáně. Zahrnuje především gliomy a další primární mozkové nádory dospělých i dětí.",
        "code": "C71",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "neurologie",
            "vzácná onemocnění",
            "kvalita života",
        ],
        "trend_context": "Počet zachycených případů se od konce sedmdesátých let zhruba ztrojnásobil. Velkou část nárůstu vysvětluje dostupnost magnetické rezonance — víc nádorů se popíše, ne víc jich skutečně vzniká. Roli hraje i stárnutí populace.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "rok_dg",
    },
    "leukemie_incidence": {
        "label": "Leukémie — incidence",
        "human_name": "Leukémie",
        "description": "Souhrn zhoubných onemocnění krvetvorné tkáně — zahrnuje lymfoblastickou, lymfocytární, myeloidní a další typy. U dětí jde o nejčastější rakovinu vůbec, u dospělých přibývá s věkem.",
        "code": "C91–C95",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "dětská onkologie",
            "transplantace kostní dřeně",
            "hematologie",
        ],
        "trend_context": "Roční počet nově zachycených leukémií se od konce sedmdesátých let zdvojnásobil — odráží stárnutí populace a lepší záchyt díky krevním testům. Dětské leukémie patří k onkologickým úspěchům — pětileté přežití dnes přesahuje 85 procent.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "rok_dg",
    },
}


def download_csv_to_tempfile(url: str) -> Path | None:
    """Stáhne CSV ze zadané URL do dočasného souboru (streaming, ne do paměti).

    NOR CSV mívají 100+ MB, takže je stahujeme po blocích na disk.
    Vrací cestu k dočasnému souboru, nebo None při chybě.
    """
    try:
        print(f"  Stahuji {url} ...")
        response = requests.get(
            url,
            timeout=180,
            stream=True,
            headers={"User-Agent": "Omnimedia-NOR-Sync/1.0 (PR research)"},
        )
        response.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False
        )
        size = 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                tmp.write(chunk)
                size += len(chunk)
        tmp.close()
        print(f"  Staženo {size / 1024 / 1024:.1f} MB do {tmp.name}")
        return Path(tmp.name)
    except Exception as e:
        print(f"  CHYBA při stahování: {e}", file=sys.stderr)
        return None


def count_cases_by_year(
    csv_path: Path,
    diagnosis_col: str,
    diagnosis_prefix,
    year_col: str,
) -> list:
    """Spočítá počet řádků podle roku pro danou diagnózu.

    Filtruje řádky kde hodnota v `diagnosis_col` začíná na `diagnosis_prefix`
    (např. "C50" zachytí "C50", "C50.0", "C50.1" …) a počítá je seskupené
    podle roku ve sloupci `year_col`.

    `diagnosis_prefix` může být string ("C50") nebo seznam stringů
    (["C18", "C19", "C20"] pro kolorektum). Match je OR přes seznam.
    """
    # Normalizace na tuple pro str.startswith(tuple).
    if isinstance(diagnosis_prefix, str):
        prefixes = (diagnosis_prefix,)
    else:
        prefixes = tuple(diagnosis_prefix)

    counts: dict[int, int] = {}

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        dx_col = cols_lower.get(diagnosis_col.lower())
        yr_col = cols_lower.get(year_col.lower())

        if not dx_col or not yr_col:
            raise ValueError(
                f"CSV neobsahuje očekávané sloupce '{diagnosis_col}' / '{year_col}'. "
                f"Nalezené sloupce: {reader.fieldnames}"
            )

        for row in reader:
            dx = (row.get(dx_col) or "").strip()
            if not dx.startswith(prefixes):
                continue
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if not (1950 <= year <= 2030):
                continue
            counts[year] = counts.get(year, 0) + 1

    return [{"year": y, "value": counts[y]} for y in sorted(counts.keys())]


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

    return {"trend": trend, "delta": delta_pct, "peakYear": peak["year"]}


def sync_one(dataset_id: str, cfg: dict) -> str:
    """Stáhne, naparsuje a uloží jeden dataset.

    Vrací: "ok" (úspěch) nebo "failed" (chyba stahování/parsování).
    """
    print(f"\n[{dataset_id}] {cfg['label']} ({cfg['code']})")

    csv_path = download_csv_to_tempfile(cfg["data_url"])
    if csv_path is None:
        return "failed"

    try:
        series = count_cases_by_year(
            csv_path,
            cfg["diagnosis_col"],
            cfg["diagnosis_prefix"],
            cfg["year_col"],
        )
        if not series:
            print("  CHYBA: žádná data po filtru diagnózy", file=sys.stderr)
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
        "id": dataset_id,
        "label": cfg["label"],
        "human_name": cfg["human_name"],
        "description": cfg["description"],
        "code": cfg["code"],
        "source": "Národní onkologický registr (ÚZIS)",
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
        "data_url": cfg["data_url"],
        "source_url": cfg["source_url"],
    }

    out_path = OUT_DIR / f"{dataset_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(
        f"  OK: {len(series)} let dat, delta {meta['delta']:+}%, "
        f"uloženo do {out_path.relative_to(OUT_DIR.parent.parent)}"
    )
    return "ok"


def main():
    print(f"NOR sync — start v {datetime.now().isoformat()}")

    results = {}
    for ds_id, cfg in DATASETS.items():
        results[ds_id] = sync_one(ds_id, cfg)

    ok = [k for k, v in results.items() if v == "ok"]
    failed = [k for k, v in results.items() if v == "failed"]

    print("\n=== NOR sync — hotovo ===")
    print(f"  OK ({len(ok)}): {', '.join(ok) if ok else '—'}")
    print(f"  Selhalo ({len(failed)}): {', '.join(failed) if failed else '—'}")

    if not ok:
        print("\nŽÁDNÝ DATASET NEPROŠEL. Pravděpodobné příčiny:", file=sys.stderr)
        print("  1. data.mzcr.cz přejmenoval CSV (zkontroluj data_url v DATASETS)", file=sys.stderr)
        print("  2. data.mzcr.cz server je dočasně nedostupný", file=sys.stderr)
        print("  3. Změnila se struktura CSV (sloupce diagnoza_kod / rok_dg)", file=sys.stderr)
        sys.exit(1)

    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
