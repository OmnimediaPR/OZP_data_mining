"""
discover_nzip.py — discovery všech otevřených datasetů na portálu NZIP.cz

Stáhne sitemap-data-posts.xml (kompletní seznam URL datasetů), pro každý
fetchne detailní stránku a vyextrahuje meta: kategorii, název, popis, datum
aktualizace, URL CSV, klíčová slova a zdrojový odkaz.

Žádné stahování CSV samotných — tahle fáze jen mapuje, co je vůbec k dispozici.
Výstup: data/discovered_datasets.json (seznam objektů).

Spuštění:
    python scripts/discover_nzip.py              # všechny datasety ze sitemap
    python scripts/discover_nzip.py --limit 10   # jen prvních 10 (test)
    python scripts/discover_nzip.py --limit 10 --offset 50  # 10 od pozice 50

Závislosti:
    pip install requests beautifulsoup4
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

SITEMAP_URL = "https://www.nzip.cz/sitemaps/sitemap-data-posts.xml"
OUT_PATH = Path(__file__).parent.parent / "data" / "discovered_datasets.json"

USER_AGENT = "Omnimedia-NZIP-Discovery/1.0 (PR research)"
REQUEST_TIMEOUT = 60
# Mezi requesty na NZIP malý odstup, aby to nebylo agresivní.
SLEEP_BETWEEN_FETCHES = 0.3


def fetch_sitemap_urls() -> list[str]:
    """Stáhne sitemap-data-posts.xml a vrátí seznam URL datasetů."""
    print(f"Stahuji sitemap: {SITEMAP_URL}")
    r = requests.get(SITEMAP_URL, timeout=REQUEST_TIMEOUT,
                     headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    r.raise_for_status()
    # Sitemap je XML; nepotřebujeme plný XML parser, regex na <loc> je dost.
    urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
    # Filtruj jen URL datasetů (pattern /data/CISLO-...) — sitemap by měl mít jen ty,
    # ale pro jistotu.
    urls = [u for u in urls if re.search(r"/data/\d+-", u)]
    print(f"  Nalezeno {len(urls)} URL datasetů")
    return urls


def extract_slug(url: str) -> str:
    """Z URL https://www.nzip.cz/data/2704-akutni-infarkt-myokardu vrátí
    "2704-akutni-infarkt-myokardu"."""
    m = re.search(r"/data/(\d+-[^/?#]+)", url)
    return m.group(1) if m else url


def extract_category_from_breadcrumb(soup: BeautifulSoup) -> dict | None:
    """Najde kategorii z JSON-LD BreadcrumbList. Vrací poslední breadcrumb,
    který má `item` (URL) — typicky "X: otevřená data" — protože poslední položka
    bez `item` je samotný název článku.

    Vrací dict {id, name, url} nebo None.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        text = (script.string or "").strip()
        if "BreadcrumbList" not in text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        items = data.get("itemListElement", [])
        # Z konce — chceme nejhlubší kategorii (před samotným článkem).
        # Některé položky nemají "item" (poslední breadcrumb = aktuální stránka).
        for it in reversed(items):
            url = it.get("item")
            if url and "/kategorie/" in url:
                m = re.search(r"/kategorie/(\d+)-([^/?#]+)", url)
                if m:
                    return {
                        "id": int(m.group(1)),
                        "slug": m.group(2),
                        "name": it.get("name", "").strip(),
                        "url": url,
                    }
    return None


def extract_h1(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None


def extract_description(soup: BeautifulSoup) -> str | None:
    """Vrací text z `<div class="article__abstract">` jako čistý text bez tagů.
    Fallback: og:description (může být oříznutý)."""
    abstract = soup.find("div", class_="article__abstract")
    if abstract:
        text = abstract.get_text(separator=" ", strip=True)
        # Normalizace whitespace
        text = re.sub(r"\s+", " ", text)
        if text:
            return text
    og = soup.find("meta", attrs={"property": "og:description"})
    if og:
        return og.get("content", "").strip() or None
    return None


def extract_update_date(soup: BeautifulSoup) -> str | None:
    """Najde "Datum poslední aktualizace: DD. MM. YYYY" a vrátí ISO formát
    YYYY-MM-DD. Pokud parsování selže, vrátí raw string."""
    # `<strong>Datum poslední aktualizace:</strong> 1. 4. 2026`
    strong = soup.find("strong", string=re.compile(r"Datum poslední aktualizace"))
    if not strong:
        return None
    # Text po </strong> ve stejném rodičovi
    parent = strong.parent
    if not parent:
        return None
    raw = parent.get_text(" ", strip=True)
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return raw


def extract_csv_url(soup: BeautifulSoup) -> str | None:
    """Najde odkaz "Stáhnout" v sekci Distribuce datové sady — to je CSV URL.
    Hledá `<a class="dataset-download__button--download">`.
    """
    # Bs4 hledání podle class substring
    btn = soup.find("a", class_=lambda c: c and "dataset-download__button--download" in c)
    if btn and btn.get("href"):
        return btn["href"]
    return None


def extract_keywords(soup: BeautifulSoup) -> list[str]:
    """Najde H2 "Klíčová slova" a vrátí čárkami oddělená klíčová slova z následujícího <p>."""
    h2 = soup.find("h2", string=re.compile(r"^\s*Klíčová slova\s*$"))
    if not h2:
        return []
    nxt = h2.find_next("p")
    if not nxt:
        return []
    raw = nxt.get_text(" ", strip=True)
    # Klíčová slova jsou oddělená čárkami
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def fetch_and_parse_dataset(url: str) -> dict | None:
    """Stáhne a vyparsuje detailní stránku datasetu. Vrací dict s extrahovanými
    poli, nebo None při selhání stahování."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  CHYBA stahování {url}: {e}", file=sys.stderr)
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    return {
        "id": extract_slug(url),
        "source_page_url": url,
        "title": extract_h1(soup),
        "description": extract_description(soup),
        "category": extract_category_from_breadcrumb(soup),
        "update_date": extract_update_date(soup),
        "csv_url": extract_csv_url(soup),
        "keywords": extract_keywords(soup),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None,
                    help="Omez počet zpracovaných datasetů (test mode)")
    ap.add_argument("--offset", type=int, default=0,
                    help="Začni od N-tého datasetu v sitemapu (pro chunkování)")
    ap.add_argument("--out", type=Path, default=OUT_PATH,
                    help=f"Cesta pro výstup JSON (default {OUT_PATH})")
    args = ap.parse_args()

    print(f"NZIP discovery — start v {datetime.now().isoformat()}")

    urls = fetch_sitemap_urls()
    total = len(urls)
    if args.offset:
        urls = urls[args.offset:]
    if args.limit:
        urls = urls[:args.limit]
    print(f"Zpracuju {len(urls)} datasetů (offset={args.offset}, "
          f"limit={args.limit or 'vše'}, celkem v sitemap: {total})")

    results = []
    failed = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        rec = fetch_and_parse_dataset(url)
        if rec is None:
            failed.append(url)
            continue
        # Diagnostika pro každý záznam
        cat = rec.get("category")
        cat_label = f"{cat['name']} (id={cat['id']})" if cat else "??? bez kategorie"
        csv_marker = "CSV" if rec.get("csv_url") else "bez CSV"
        print(f"    → {rec.get('title', '???')[:70]}")
        print(f"      kategorie: {cat_label}, {csv_marker}, "
              f"keywords: {len(rec.get('keywords') or [])}")
        results.append(rec)
        time.sleep(SLEEP_BETWEEN_FETCHES)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_sitemap": SITEMAP_URL,
        "total_in_sitemap": total,
        "processed": len(results),
        "failed": failed,
        "datasets": results,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # Souhrn
    print(f"\n=== Discovery hotovo ===")
    print(f"  Zpracováno: {len(results)} / {len(urls)}")
    print(f"  Selhalo:    {len(failed)}")
    cats = {}
    no_csv = 0
    for r in results:
        c = r.get("category")
        key = f"{c['id']}: {c['name']}" if c else "(bez kategorie)"
        cats[key] = cats.get(key, 0) + 1
        if not r.get("csv_url"):
            no_csv += 1
    print(f"  Datasetů bez CSV (datové souhrny / vizualizace): {no_csv}")
    print(f"  Kategorie nalezené ({len(cats)}):")
    for key, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {n:4d}× {key}")
    print(f"\n  Výstup: {args.out}")


if __name__ == "__main__":
    main()
