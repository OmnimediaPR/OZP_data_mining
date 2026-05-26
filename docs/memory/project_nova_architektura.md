---
name: project-nova-architektura
description: "On-demand fetch architektura (2026-05-21) — repo drží jen catalog.json, frontend fetchuje CSV živě ze zdroje. KOMPLETNĚ HOTOVÁ. Možné navazující práce: rozšíření katalogu (refresh_catalog.py už existuje, commit b7f0419)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 169ab576-f827-4f8e-98da-6f07d383a113
---

> **AKTUALIZACE 2026-05-25 (předpočítané řady):** Architektura dotažena — místo živého stahování CSV v prohlížeči se časové řady **předpočítají** skriptem `scripts/bake_series.mjs` a uloží do `catalog.json` jako pole `series` ([{year,value}]). Frontend `parseDataset` vrací `entry.series` rovnou (živý fetch jen jako záloha). Řeší to velké soubory, výpadky připojení i strop prohlížeče (viz [[project_frontend_parse_limity]]). Skript: buffer parse do 500 MB, nad to **streaming po řádcích** (covid 1,4 GB OK), obnovitelný (přeskočí hotové), průběžně ukládá, retry na dočasné chyby, prohlížečový User-Agent kvůli WAF. Schema 2.2. Katalog **104→103** (vyřazeny `sebevrazdy_hospitalizace` — špatný recept; covid opraven na počty podle `DatumPozitivity`). Refresh = pustit `node --max-old-space-size=4096 scripts/bake_series.mjs` znovu. catalog.json ~259 KB. Commit `e81ec71`.

> **AKTUALIZACE 2026-05-25:** Rozšíření katalogu HOTOVO — z 6 ukázkových na **104 datasetů** přes 11 dávek (kardio, onko, hospitalizace, infekce, duševní zdraví, úrazy, mortalita, prevence, screening, reprodukce, ostatní). Workflow: `expand_catalog.py` → `generate_catalog_drafts.py` → ruční revize → `batch_approvals/batch_NN_*.json` → `apply_batch.py`. Frontend `parseDataset` cestou rozšířen o gzip + windows-1250 + agregace `date_to_year`/`last_in_year` + BOM, viz [[project_frontend_parse_limity]]. Před každou dávkou ověřen render přes `scripts/verify_parse.mjs`, viz [[feedback_overit_render_datasetu]]. Per-event mikrodata řešena přes `row_match`, viz [[project_per_event_mikrodata]].

**Architektonický pivot ze dne 2026-05-21.** Nahrazuje předchozí přístup ze [[project-nzip-discovery]] (sync skripty + lokální JSON soubory). Důvod: 95 % datasetů uživatel za rok nepoužije, pre-sync všeho je masivní storage a komplexní pipeline za nulový benefit. CSV jsou na NZIP/ÚZIS veřejné a CORS-otevřené. Pro brief workflow (zadej téma → AI doporučí 5–10 → fetchni jen ty) je latence několik vteřin přijatelná, čekáme stejně na AI analýzu.

## Plán 4 kroků (Danem definovaný)

- **Krok 0 — CORS check (HOTOVO):** Ověřeno, že `datanzis.uzis.gov.cz`, `data.mzcr.cz`, `www.nzip.cz`, `ec.europa.eu` vracejí `Access-Control-Allow-Origin: *` pro reálný browser fetch z `omnimediapr.github.io`. **Gotcha:** ÚZIS WAF blokuje `HeadlessChrome` v User-Agent — reálné uživatele to neovlivní, ale pro playwright/automation testy musíš přepsat UA na běžný Chrome.
- **Krok 1 — catalog.json (HOTOVO, commit `dfa0d98`):** Schéma 2.0 v `data/catalog.json`, 6 sample datasetů (aim, cmp, prsa_incidence, kolorektum_incidence, prsa_mortalita, sebevrazdy_hospitalizace). Pole: `id, category, human_name, description, relevant_for, trend_context, source_type, source, code, csv_url, source_url, year_column, filter_column, row_match {column, prefix}, aggregation (sum_column | count_rows), value_column, metric_label, last_seen`. Ratio aggregation a Eurostat wide-TSV vědomě odložené (poznámka v `schema_notes.future_extensions`).
- **Krok 3 — frontend on-demand fetch (HOTOVO, commit `c1ab747`):** App.jsx už nemá hardcoded list 230 IDs. Při startu fetch `/data/catalog.json`, lazy fetch CSV po výběru karty přes papaparse. Cache per `csv_url` (NOR 197 MB CSV se stáhne jednou). Naměřené časy: aim 1.3 MB → instant, prsa_incidence 197 MB → 22 s, kolorektum (cache hit fetch, ale parse znovu) → 15 s. INTL_DATASETS odstraněn z `allDatasets` (zůstává v kódu, Krok 2 ho smaže). Default selectedIds `['aim', 'cmp']`. Loading + error UI v DatasetCard.
- **Optimalizace tokenů (HOTOVO, commit `7c67b54`):** Doporučování („Najít data") přehozeno na **Haiku** (`claude-haiku-4-5-20251001`, ~4× levnější vstup než Sonnet — filtrování katalogu Haiku zvládne) + **prompt cache**: katalog (~16k tokenů, 54 KB) je v cachovaném content bloku (`cache_control: ephemeral`), téma je variabilní blok na konci → opakované „Najít data" do 5 min platí katalog ~10 %. Analýza zůstává na Sonnetu (kvalita). Odhad nákladu/brief ~$0,10 → ~$0,06. Pozn.: hlavní žrout byl celý katalog (110 datasetů) posílaný při každém doporučení.

- **Krok 4 — AI doporučení datasetů (HOTOVO, commit `40c233e`, error UI v `d810eb7`):** Tlačítko "Najít relevantní data" pod polem Téma v Section 01. POST na Anthropic API (původně `claude-sonnet-4-6`, nyní Haiku + cache — viz optimalizace výše, max_tokens 2048) s tématem + zkráceným katalogem (jen `id, category, human_name, description, relevant_for`). Robustní JSON parsing přes regex `{...}`, validace že vrácená ID jsou v katalogu (filter přes Set). Po úspěchu `setSelectedIds(valid.map(r => r.id))` — existující useEffect na `selectedIds` automaticky spustí lazy CSV fetch. UI ukáže modrý panel s human_name + důvod pro každý návrh. State: `recommending`, `recommendations`. **Ověřeno E2E 2026-05-21** na tématu "Trendy v české onkologii — prs a tlusté střevo": AI vybrala datasety, auto-select karet → lazy fetch CSV → analýza → docx export, celá smyčka funguje. **Známé omezení**: pokud téma nesedí na žádný ze 6 sample datasetů (např. nádor mozku), AI vrátí prázdné pole — error bar správně vypíše dostupné IDs, ale uživatel narazí na úzký katalog.
- **Krok 2 — cleanup (HOTOVO, commit `7f66d8c`):** Smazáno 233 souborů (~72 700 řádků): `.github/workflows/sync-{nkis,nor,nzip-curated}.yml`, `scripts/sync_*.py`, celé adresáře `data/nor/`, `data/nkis/`, `data/nzip/`, `data/nzip_curated/`, `data/international/`. Discovery vrstva přesunuta do `docs/discovery/` (discover_nzip.py, summarize_inventory.py, discovered_datasets.json 912 KB, dataset_catalog_preview.md) jako reference pro budoucí rozšiřování katalogu. `deploy.yml` zúžen z `cp -r data/* frontend/public/data/` na `cp data/catalog.json frontend/public/data/catalog.json`.
- **scripts/refresh_catalog.py (HOTOVO, commit `b7f0419`):** Stdlib-only script, Range request 8 KB per dataset, idempotentně aktualizuje `last_seen` a `updated` v `catalog.json`. Spouštění ručně: `python3 scripts/refresh_catalog.py`. Při chybě jen warning, JSON beze změny.

## Klíčové soubory

- `data/catalog.json` — jediný datový soubor v repu (6 sample datasetů, schéma 2.0)
- `frontend/src/App.jsx` — fetch + lazy CSV parse logic (řádek ~10–110 je nové: `csvCache`, `fetchCsvCached`, `parseDataset`, `computeMeta`). State `datasetData` (Map<id, {loading, error, series}>) populuje se v useEffect na `selectedIds`.
- `frontend/package.json` — papaparse 5.5.3 přidán

## Pravidla pro pokračování (Danem definovaná)

- Po každém kroku commit + push, počkat na schválení před dalším.
- Žádné spontánní úpravy mimo plán. Žádné nové datasety, vizualizace, fetch.
- Pokud něco zaskočí, popsat situaci a navrhnout řešení — nehadat.
- **Refactor App.jsx do modulů NEDĚLAT** — schováno na později.

## Lokální dev gotcha

`frontend/public/data/` je v `.gitignore`, CI ho zaplní `cp -r data/* frontend/public/data/` před buildem. Pro `npm run dev` lokálně: `cp data/catalog.json frontend/public/data/catalog.json` (sám catalog.json stačí, sample datasetů 6 fetchuje frontend živě ze zdroje).

## Co odložené pro pozdější iterace

- **Ratio aggregation** (mamografie pokrytí = numerator/denominator)
- **Eurostat wide-TSV** (roky v sloupcích, ne dlouhý formát)
- **Mezinárodní data** v catalogu — sample 6 je čistě národní
- **NOR regional snapshots/timeseries** (krajové) — vyžadují další pole v schématu
- **Parse-cache optimalizace** — sníží 15 s → < 1 s pro druhé+ NOR dg

## Související

- [[project-datovy-brief]] — celkový kontext nástroje (zastaralá v některých detailech, ale architektura GH Pages + Anthropic-from-browser stále platí)
- [[project-nzip-discovery]] — předchozí přístup, je v procesu likvidace v Kroku 2
- [[feedback-commit-style]] — krátké commit messages, 1 česká věta v hlavičce
- [[feedback-workflow]] — krok-po-kroku s odsouhlasením
