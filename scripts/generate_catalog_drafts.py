#!/usr/bin/env python3
"""Vygeneruje draft entries pro data/catalog.json z dataset_headers.json.

Heuristicky odhadne technická pole (year_column, value_column, aggregation,
csv_format, csv_encoding) a texty (human_name, description, relevant_for)
ofrancuje z NZIP metadat. Nechává prázdné/označené pole, která vyžadují
lidskou revizi (trend_context, metric_label, finální category).

Výstup: docs/discovery/catalog_drafts.json — seznam draft entries
ve struktuře schema 2.1, kterou Dan postupně schvaluje per batch.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADERS_PATH = ROOT / "docs" / "discovery" / "dataset_headers.json"
SELECTION_PATH = ROOT / "docs" / "discovery" / "catalog_selection.json"
DRAFTS_PATH = ROOT / "docs" / "discovery" / "catalog_drafts.json"

NRHZS_CAT = "Národní registr hrazených zdravotních služeb: otevřená data"

# NZIP category → brief-level tematický blok (pro pole `category` v catalog.json)
CATEGORY_MAP = {
    "Národní kardiologický informační systém: otevřená data": "kardio",
    "Národní onkologický registr: otevřená data": "onko",
    "Národní onkologický registr – modul Národní onkologický program: otevřená data": "onko",
    "Informační systém screeningu karcinomu tlustého střeva a konečníku: otevřená data": "screening",
    "Informační systém screeningu karcinomu prsu: otevřená data": "screening",
    "Informační systém screeningu karcinomu hrdla děložního: otevřená data": "screening",
    "Informační systém screeningu karcinomu prostaty: otevřená data": "screening",
    "Informační systém screeningu karcinomu plic: otevřená data": "screening",
    "Centrální evidence dat populačních preventivních programů: otevřená data": "prevence",
    "Národní informační systém péče o duševní zdraví: otevřená data": "duševní zdraví",
    "Národní registr reprodukčního zdraví – modul rodiček: otevřená data": "reprodukce",
    "Národní registr reprodukčního zdraví – modul novorozenců: otevřená data": "reprodukce",
    "Národní registr reprodukčního zdraví – modul vrozených vad: otevřená data": "reprodukce",
    "Národní registr reprodukčního zdraví – modul potratů: otevřená data": "reprodukce",
    "Národní registr reprodukčního zdraví – modul asistované reprodukce: otevřená data": "reprodukce",
    "List o prohlídce zemřelého: otevřená data": "mortalita",
    "Národní informační systém paliativní péče: otevřená data": "mortalita",
    "Národní registr hospitalizovaných: otevřená data": "hospitalizace",
    "Národní registr intenzivní péče: otevřená data": "hospitalizace",
    "Lůžkový fond: otevřená data": "hospitalizace",
    "Národní registr úrazů: otevřená data": "úrazy",
    "Národní registr úrazů – modul dopravních úrazů: otevřená data": "úrazy",
    "Informační systém infekční nemoci (mimo COVID-19): otevřená data": "infekce",
    "Informační systém infekční nemoci – COVID-19: otevřená data": "infekce",
    "Registr pohlavních nemocí: otevřená data": "infekce",
    "Registr tuberkulózy: otevřená data": "infekce",
    "Centrální evidence očkování: otevřená data": "infekce",
    "Národní registr hrazených zdravotních služeb: otevřená data": "ostatní",  # NRHZS subset má smíšená témata, opravím per dataset
    "Informační systém screeningu sluchu u novorozenců: otevřená data": "prevence",
    "Další prevence u novorozenců a dětí: otevřená data": "prevence",
    "Národní diabetologický registr: otevřená data": "ostatní",
    "Zdravotnická technika: otevřená data": "ostatní",
    "NRIP – Národní informační systém anesteziologické péče: otevřená data": "hospitalizace",
    "Národní registr kloubních náhrad: otevřená data": "ostatní",
    "Výkazy zdravotní péče: otevřená data": "ostatní",
    "Roční hlášení počtu nežádoucích událostí pro centrální hodnocení: otevřená data": "hospitalizace",
}

# NZIP category → human source name (pro pole `source`)
SOURCE_MAP = {
    "Národní kardiologický informační systém: otevřená data": "Národní kardiologický informační systém (ÚZIS)",
    "Národní onkologický registr: otevřená data": "Národní onkologický registr (ÚZIS)",
    "Národní onkologický registr – modul Národní onkologický program: otevřená data": "Národní onkologický program (ÚZIS)",
    "Informační systém screeningu karcinomu tlustého střeva a konečníku: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Informační systém screeningu karcinomu prsu: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Informační systém screeningu karcinomu hrdla děložního: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Informační systém screeningu karcinomu prostaty: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Informační systém screeningu karcinomu plic: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Centrální evidence dat populačních preventivních programů: otevřená data": "Centrální evidence preventivních programů (ÚZIS)",
    "Národní informační systém péče o duševní zdraví: otevřená data": "Národní informační systém péče o duševní zdraví (ÚZIS)",
    "Národní registr reprodukčního zdraví – modul rodiček: otevřená data": "Národní registr reprodukčního zdraví (ÚZIS)",
    "Národní registr reprodukčního zdraví – modul novorozenců: otevřená data": "Národní registr reprodukčního zdraví (ÚZIS)",
    "Národní registr reprodukčního zdraví – modul vrozených vad: otevřená data": "Národní registr reprodukčního zdraví (ÚZIS)",
    "Národní registr reprodukčního zdraví – modul potratů: otevřená data": "Národní registr reprodukčního zdraví (ÚZIS)",
    "Národní registr reprodukčního zdraví – modul asistované reprodukce: otevřená data": "Národní registr reprodukčního zdraví (ÚZIS)",
    "List o prohlídce zemřelého: otevřená data": "List o prohlídce zemřelého (ÚZIS)",
    "Národní informační systém paliativní péče: otevřená data": "Národní informační systém paliativní péče (ÚZIS)",
    "Národní registr hospitalizovaných: otevřená data": "Národní registr hospitalizovaných (ÚZIS)",
    "Národní registr intenzivní péče: otevřená data": "Národní registr intenzivní péče (ÚZIS)",
    "Lůžkový fond: otevřená data": "Lůžkový fond ČR (ÚZIS)",
    "Národní registr úrazů: otevřená data": "Národní registr úrazů (ÚZIS)",
    "Národní registr úrazů – modul dopravních úrazů: otevřená data": "Národní registr úrazů (ÚZIS)",
    "Informační systém infekční nemoci (mimo COVID-19): otevřená data": "Informační systém infekční nemoci (ÚZIS)",
    "Informační systém infekční nemoci – COVID-19: otevřená data": "Informační systém infekční nemoci COVID-19 (ÚZIS)",
    "Registr pohlavních nemocí: otevřená data": "Registr pohlavních nemocí (ÚZIS)",
    "Registr tuberkulózy: otevřená data": "Registr tuberkulózy (ÚZIS)",
    "Centrální evidence očkování: otevřená data": "Centrální evidence očkování (ÚZIS)",
    "Národní registr hrazených zdravotních služeb: otevřená data": "Národní registr hrazených zdravotních služeb (ÚZIS)",
    "Informační systém screeningu sluchu u novorozenců: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Další prevence u novorozenců a dětí: otevřená data": "Národní screeningové centrum (ÚZIS)",
    "Národní diabetologický registr: otevřená data": "Národní diabetologický registr (ÚZIS)",
    "Zdravotnická technika: otevřená data": "Zdravotnická technika v ČR (ÚZIS)",
    "NRIP – Národní informační systém anesteziologické péče: otevřená data": "Národní informační systém anesteziologické péče (ÚZIS)",
    "Národní registr kloubních náhrad: otevřená data": "Národní registr kloubních náhrad (ÚZIS)",
    "Výkazy zdravotní péče: otevřená data": "Výkazy zdravotní péče (ÚZIS)",
    "Roční hlášení počtu nežádoucích událostí pro centrální hodnocení: otevřená data": "Hlášení nežádoucích událostí v lůžkové péči (ÚZIS)",
}

# Datasety, které víme, že jsou windows-1250
WIN1250_IDS = {
    "1820-dopravni-urazy-diagnozy-t-otevrena-data",
    "2355-umrti-pocet-rok-vek-pohlavi-kapitola-mkn-10-otevrena-data",
    "2579-preventivni-prohlidky-pokryti-otevrena-data",
}


def shorten_id(nzip_id: str) -> str:
    """Z 'NNNN-popis-otevrena-data' udělej kratší slug 'popis'."""
    s = re.sub(r"^\d+-", "", nzip_id)
    s = re.sub(r"-otevrena-data$", "", s)
    s = s.replace("-", "_")
    return s


def clean_human_name(title: str) -> str:
    """Odstraní '(otevřená data)' suffix."""
    return re.sub(r"\s*\(otevřená data\)\s*$", "", title).strip()


def shorten_description(desc: str) -> str:
    """První 1-2 věty z popisu, ale max ~280 znaků. Odstraní zkratky v závorkách."""
    if not desc:
        return ""
    # Odstraní "( ZKRATKA )" patterny — feedback: žádné zkratky v description.
    # Matche typicky `(KVO)`, `( KVO )`, `(NRHZS)` apod.
    cleaned = re.sub(r"\s*\(\s*[A-ZÁ-Ž]{2,}(?:[- ][A-ZÁ-Ž]{2,})?\s*\)\s*", " ", desc)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Vezme prvních pár vět končících tečkou nebo otazníkem
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    out = ""
    for s in sentences:
        if len(out) + len(s) > 280:
            break
        out = (out + " " + s).strip()
    return out


def extract_mkn_codes(text: str) -> str | None:
    """Vytáhne MKN-10 kódy ze stringu (např. I21-I22, C50, X60-X84)."""
    matches = re.findall(r"\b[A-Z]\d{2}(?:[-–.]?\d{2})?(?:[-–][A-Z]\d{2}(?:\.\d+)?)?\b", text or "")
    return ", ".join(sorted(set(matches))) if matches else None


YEAR_COLUMN_NAMES = {
    "rok", "rok_dg", "rok_umrti", "umrti_rok", "rok_porodu", "rok_narozeni",
    "rok_pece", "rok_vakcinace", "rok_diagnozy", "rok_zachyceni",
    "rok_screeningu", "rok_dispenzarizace", "rok_kontroly",
}


def detect_year_column(columns: list[str]) -> str | None:
    """Najde sloupec s rokem. Preferuje přesný 'rok', pak varianty."""
    cols_lower = [c.lower().lstrip("﻿") for c in columns]
    # Přesný 'rok'
    for i, c in enumerate(cols_lower):
        if c == "rok":
            return columns[i].lstrip("﻿")
    # Specifické varianty (z YEAR_COLUMN_NAMES)
    for variant in YEAR_COLUMN_NAMES:
        if variant == "rok":
            continue
        for i, c in enumerate(cols_lower):
            if c == variant:
                return columns[i]
    # Cokoliv obsahující "rok" jako samostatné slovo (ne v rok_kod, rok_ctvrtleti, …)
    for i, c in enumerate(cols_lower):
        if "rok" in c and "kod" not in c and "ctvrtleti" not in c and "icz" not in c and "icp" not in c:
            return columns[i]
    return None


def is_numeric_string(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    return bool(re.match(r"^-?\d+([.,]\d+)?$", s))


VALUE_COLUMN_PATTERNS = [
    r"^incidence",
    r"^prevalence",
    r"^mortalita",
    r"^hospitalizace_rocni$",
    r"^hospitalizace$",
    r"^pocet$",
    r"^pocet_(?!predch)",  # 'pocet_predch_UPT' není value column, jen znak rodičky
    r"^mnozstvi$",
    r"_celkem$",
    r"_pocet$",
    r"^pripady$",
    r"^hodnota$",
    r"^zem(reli)?_",  # zemreli_pocet, zem_celkem
    r"^pocet_oslovenych",
    r"^pocet_vysetren",
    r"^pocet_pripadu",
    r"^pocet_pacientu",
    r"^pocet_dialyzovanych",
    r"^pocet_jeden",
    r"^pocet_hosp",
    r"^pocet_UOP$",
    r"^pocet_pristroju",
    r"^pocet_operaci",
    r"^pocet_pacientodnu",
    r"^NU_absolutni_pocet$",
    r"^DCCI$",  # polymorbidita index
    r"^predcasne_zemreli_pocet",
    r"^ocekavatelne_zemreli_pocet",
    r"^zemreli_doma_pocet",
]

# Sloupce, které jsou ID identifikátorem řádku (= per-event tabulka).
ID_COLUMN_NAMES = {
    "id", "id_urazu", "id_pacient", "id_pacienta", "id_rodicky", "id_porodu",
    "id_diteti", "id_novorozence", "id_zemreleho", "id_zaznamu", "id_hospitalizace",
    "id_potratu", "id_vady",
}


VALUE_NAME_HINTS = (
    "pocet", "mnozstvi", "incidence", "prevalence", "mortalita",
    "hospitalizace", "pripady", "zemreli", "vysetren", "hodnota",
    "_celkem", "uop", "delka", "narod_",
)


def has_explicit_value_column(columns: list[str]) -> bool:
    """True pokud aspoň jeden sloupec má jméno typické pro hodnotu."""
    for c in columns:
        cl = c.lower()
        if any(h in cl for h in VALUE_NAME_HINTS):
            # Vynech 'rok_*' a podobné dimenze
            if cl.startswith("rok") or cl in YEAR_COLUMN_NAMES:
                continue
            return True
    return False


def is_per_event_table(d: dict) -> bool:
    """Per-event = jeden řádek = jedna událost.
    Indikátory:
    - První sloupec je ID_* identifikátor → JISTĚ per-event
    - NEBO: nemá žádný explicitní value column (pocet/incidence/…) A
      většina numerických sloupců jsou binární 0/1 indikátory
    """
    cols = d["columns"]
    sample = d["sample_rows"]
    if not cols or not sample:
        return False
    first_col_lower = cols[0].lower().lstrip("﻿")
    if first_col_lower in ID_COLUMN_NAMES:
        return True

    # Pokud má dataset explicitní value column, ne per-event.
    if has_explicit_value_column(cols):
        return False

    # Spočítat numerické sloupce a kolik z nich jsou binární
    numeric_idxs = []
    binary_count = 0
    for i, c in enumerate(cols):
        if i >= len(sample[0]):
            continue
        v = sample[0][i].strip() if sample[0][i] else ""
        if is_numeric_string(v):
            numeric_idxs.append(i)
            if v in ("0", "1"):
                binary_count += 1
    if numeric_idxs and binary_count / len(numeric_idxs) >= 0.7:
        return True
    return False


def detect_value_column(d: dict) -> tuple[str | None, str]:
    """Najde value column. Vrátí (column_name, aggregation_hint).

    Pokud nemáme jasný value column (s "pocet"/"incidence"/atd. v názvu),
    vracíme count_rows. Žádný fallback na "poslední numerický sloupec" —
    ten typicky chybí, protože reprodukční registry mají dimenze, ne hodnoty.
    """
    cols = d["columns"]
    sample = d["sample_rows"]
    if not sample or not cols:
        return None, "count_rows"

    if is_per_event_table(d):
        return None, "count_rows"

    # Hledat preferenční názvy
    for pat in VALUE_COLUMN_PATTERNS:
        for i, c in enumerate(cols):
            cl = c.lower()
            if re.search(pat, cl, re.IGNORECASE):
                if i < len(sample[0]) and is_numeric_string(sample[0][i]):
                    # Skip year columns (false positive)
                    if cl in YEAR_COLUMN_NAMES or cl.startswith("rok"):
                        continue
                    return c, "sum_column"

    return None, "count_rows"


def build_relevant_for(keywords: list[str], category: str) -> list[str]:
    """Vyrobí 3-6 tagů z keywords + kategorie."""
    out = [category] if category else []
    # Vynech NZIS/ÚZIS technické tagy
    skip = {"NZIS", "ÚZIS", "NRHZS", "NKIS", "NOR", "NRRZ", "otevřená data", "populace"}
    for kw in keywords:
        if kw in skip:
            continue
        if len(out) >= 6:
            break
        if kw not in out:
            out.append(kw)
    return out[:6]


def build_draft(d: dict, today: str) -> dict:
    nzip_id = d["id"]
    category_name = d["category_name"]
    columns = d["columns"]

    is_gz = d.get("is_gzipped", False)
    is_win = nzip_id in WIN1250_IDS

    # Year/date column
    year_col = detect_year_column(columns)
    date_col = None
    if not year_col:
        # Najít sloupec začínající "datum" (datum, datum_umrti, datum_porodu, …)
        for c in columns:
            cl = c.lower().lstrip("﻿")
            if cl == "datum" or cl.startswith("datum_"):
                date_col = c
                break

    # Value column + aggregation
    value_col, agg = detect_value_column(d)
    if date_col and not year_col:
        # COVID 2072 má kumulativní *_celkem hodnoty → last_in_year.
        # Ostatní (např. 2517 jednotlivá úmrtí) — date_to_year + count_rows nebo sum.
        if nzip_id == "2072-covid-19-zakladni-prehled":
            agg = "last_in_year"
        else:
            agg = "date_to_year"

    # Slug ID
    short_id = shorten_id(nzip_id)

    draft = {
        "id": short_id,
        "_nzip_id": nzip_id,
        "category": CATEGORY_MAP.get(category_name, "ostatní"),
        "human_name": clean_human_name(d["title"]),
        "description": shorten_description(d["description"]),
        "relevant_for": build_relevant_for(d.get("keywords", []), CATEGORY_MAP.get(category_name, "ostatní")),
        "trend_context": "",  # k revizi — feedback říká nepsat tvrdé kvantifikátory bez dat
        "source_type": "national",
        "source": SOURCE_MAP.get(category_name, f"{category_name} (ÚZIS)"),
        "code": extract_mkn_codes(d["title"] + " " + (d.get("description") or "")),
        "csv_url": d["csv_url"],
        "source_url": d["source_url"],
        "year_column": year_col,
        "filter_column": None,  # k revizi per dataset
        "row_match": None,
        "aggregation": agg,
        "value_column": value_col,
        "metric_label": "",  # k revizi
        "last_seen": today,
        "_review_flags": [],
    }

    # Date column je v schema 2.1
    if date_col:
        draft["date_column"] = date_col

    # Optional komprese/encoding (jen pokud non-default)
    if is_gz:
        draft["csv_format"] = "gzip"
    if is_win:
        draft["csv_encoding"] = "windows-1250"

    # Review flagy — co bude potřeba projít ručně
    if not year_col and not date_col:
        draft["_review_flags"].append("CHYBÍ_ROK_NEBO_DATUM")
    if not value_col and agg == "sum_column":
        draft["_review_flags"].append("NEPODAŘILO_SE_NAJÍT_VALUE_COLUMN")
    if not draft["description"]:
        draft["_review_flags"].append("PRÁZDNÝ_POPIS")
    if not draft["trend_context"]:
        draft["_review_flags"].append("DOPLNIT_TREND_CONTEXT")
    if not draft["metric_label"]:
        draft["_review_flags"].append("DOPLNIT_METRIC_LABEL")
    if category_name == NRHZS_CAT:
        draft["_review_flags"].append("NRHZS_OVĚŘIT_AGGREGATION")

    return draft


def main() -> int:
    from datetime import date
    today = date.today().isoformat()

    headers = json.loads(HEADERS_PATH.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))

    exclude = set(selection["exclude_ids"])
    nrhzs_keep = set(selection["nrhzs_keep_ids"])
    id_rename = selection.get("id_rename", {})

    drafts = []
    for d in headers["datasets"]:
        if d["id"] in exclude:
            continue
        if d["category_name"] == NRHZS_CAT and d["id"] not in nrhzs_keep:
            continue
        draft = build_draft(d, today)
        # Custom ID rename (např. souhrnné NOR datasety)
        if d["id"] in id_rename:
            draft["id"] = id_rename[d["id"]]
        drafts.append(draft)

    # Setřídit podle category → human_name
    drafts.sort(key=lambda x: (x["category"], x["human_name"]))

    # Statistiky
    print(f"Vygenerováno draft entries: {len(drafts)}")
    from collections import Counter
    cat_c = Counter(d["category"] for d in drafts)
    print("\nPo brief-kategorii:")
    for c, n in cat_c.most_common():
        print(f"  {n:3d}  {c}")

    print("\nReview flags:")
    flag_c = Counter()
    for d in drafts:
        for f in d["_review_flags"]:
            flag_c[f] += 1
    for f, n in flag_c.most_common():
        print(f"  {n:3d}  {f}")

    output = {
        "generated_at": today,
        "schema_version": "2.1",
        "total": len(drafts),
        "drafts": drafts,
    }
    DRAFTS_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n→ {DRAFTS_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
