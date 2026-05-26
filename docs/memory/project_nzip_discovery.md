---
name: project-nzip-discovery
description: "Datový brief — 4fázový plán rozšíření z 7 NKIS datasetů na celý NZIP katalog. F1+F2 hotové, NOR sync běží (5 dg, commit e06d04a 2026-05-20), F2b curated parser je next."
metadata: 
  node_type: memory
  type: project
  originSessionId: f319a695-bbb3-4c59-a068-29454edffc14
---

**4fázový plán** (od 2026-05-20): Datový brief má dnes 7 NKIS kardio + 5 NOR onko datasetů. Cíl: pokrýt všechny otevřené datasety na NZIP.cz napříč kategoriemi (kardiologie, onkologie, hospitalizace, diabetes, …).

- **Fáze 1 — Discovery (HOTOVO 2026-05-20, commit 92c888d):** `scripts/discover_nzip.py` naskenoval NZIP, uložil meta 768 datasetů do `data/discovered_datasets.json`. Žádné stahování CSV.
- **Fáze 2 — Inventory (HOTOVO 2026-05-20, commit 423b829):** `scripts/sync_nzip.py` stáhne CSV (tempfile, .csv + .csv.gz, **NE .7z** — 5 přeskočeno) a vyextrahuje strukturu do `data/nzip/_inventory.json`. Limit 200k řádků. **Brief-ready JSON negeneruje** — dává smysl až po lidské curation kvůli [[feedback-no-abbreviations]]. Full run 207 datasetů: 202 OK, 5 skipped_7z, 175 s ročním sloupcem (136× `rok`, 39× `rok_*`). `scripts/summarize_inventory.py` produkuje souhrn + návrh F2b kandidátů. Manuální přehled kategorií: `data/dataset_catalog_preview.md` (41 kategorií ve 8 tematických blocích).
- **Fáze 2b — Curated parser (next, čeká Dan):** napsat `sync_nzip_curated.py` (jako sync_nkis.py) — per dataset definice year_col + metric_col + lidský human_name/description/relevant_for/trend_context. Top 20 kandidátů s ≤50k řádků a ≥5 let dat je v summarize_inventory výstupu. Pak GH Actions workflow.
- **NOR sync (HOTOVO 2026-05-20, commity 9d18c42 + e06d04a + 26634ed + 0b05741 + 0dee0fc + 562d41f):** `scripts/sync_nor.py` stahuje NOR mikrodata (NR-07-01 incidence, ~188 MB) streamovaně do tempfile, filtruje řádky podle `diagnoza_kod` prefix (string nebo list pro multi-kód jako kolorektum, leukémie, lymfomy) a počítá je seskupené po `rok_dg`. **~254 datasetů celkem** (7 NKIS kardio + ~200 NOR onko + 33 NZIP curated + 14 mezinárodní). Pět aggregation typů v sync_nor.py: "count" (incidence/mortalita), "survival_5y" (přežití), "stage_share" (stadium TNM), "regional_snapshot" (snapshot per kraj), "regional_timeseries" (multi-year × multi-region). V sync_nzip_curated.py navíc "ratio" pro screening pokrytí. **Frontend podporuje:** regional_snapshot přes RegionalMap (geo grid 4×6 ČR) + RegionalBars; regional_timeseries přes RegionalHeatmap (matrix roky × kraje). 

**NOR incidence (67 dg):** celkové dg (prsa C50, plíce C34, prostata C61, kolorektum C18–C20, melanom C43, žaludek C16, slinivka C25, mozek C71, leukémie C91–C95, lymfomy C81–C86, ledvina C64, močový měchýř C67, štítná C73, jícen C15, varlata C62, vaječník C56, čípek C53, děloha C54, kosti C40–C41, dutina ústní a hltan C00–C14, myelom C90, hrtan C32, kožní mimo melanom C44), souhrn vzácných (C30–C31, C37–C38, C45–C49, C69, C74–C75), dělení lymfomů (Hodgkin/B-buněčné/T-buněčné), věkové splity (slinivka, mozek, jícen, prsa, plíce, melanom × mladí<50/starší50+; varlata <40/40+; leukémie děti 0–19/dospělí 20+; kolorektum třístupňový <40/40–49/50+ + souhrnný <50; štítná žláza dětí 0–14, 0–19, dospělí 20+), pohlavní splity (plíce/kolorektum/žaludek/hrtan/melanom/močový měchýř × muži/ženy), stadia (prsa/kolorektum/plíce/prostata/melanom/žaludek × stadium 1/4).

**NOR mortalita (27 dg, NR-07-02):** kompletní pokrytí všech hlavních dg.

**NOR 5leté přežití (23 dg, NR-07-03):** kompletní pokrytí všech hlavních dg. Pozor: `preziti=1` v CSV znamená ZEMŘEL (matoucí pojmenování).

**NOR krajové snapshoty (10 datasetů):** 5 dg × incidence (NR-07-01) + 5 dg × mortalita (NR-07-02) — snapshot pro 2022 per NUTS-3 kraj. Data: `[{kraj_kod, kraj_nazev, value}]`. Frontend rendering hotov.

**NZIP curated (15 dg, F2b, sync_nzip_curated.py):** tuberkulóza, sebevraždy/hospitalizace, autismus u dětí, pohlavní nemoci, astma, alergická rýma, vrozené vady, lázeňská péče, paliativní péče, očekávatelná úmrtí + 5 screening pokrytí (preventivní prohlídky, kolorektum, PSA, autismus včasný záchyt, kyčle). Workflow sync-nzip-curated.yml (3. v měsíci).

Myelom (C90) nelze dělit na subtypy — CSV neobsahuje subkódy C90.0–C90.3. **Věkový filtr:** volitelný `age_col` + `age_codes` v cfg pro filtrování podle ÚZIS kódů věkové kategorie (formát `66XXXYYY`). `.github/workflows/sync-nor.yml` běží 2. v měsíci v 3:00 UTC. **Cache stahování ✓ (562d41f):** datasety se seskupí podle `data_url`, CSV se stáhne 1× a single-pass se počítají všechny. Runtime 6m → 36s při 18 dg. Otevírá cestu k mortalitě (NR-07-02) a přežití (NR-07-03) jako další skupiny. App.jsx + catalog.json napojené.
- **Fáze 3 — ?** (Dan upřesní)
- **Fáze 4 — ?** (Dan upřesní)

**Výsledek F1 (2026-05-20, full run, ~15 min):**
- 768 / 768 zpracováno, 0 selhání. Commit `92c888d`.
- 207 datasetů s `csv_url` (kandidáti pro F2), 561 bez (publikace/souhrny/novinky).
- Top kategorie: 195 "Datové novinky" (= aktuality, ne datasety; všechny bez csv_url), 71 NRHZS otevřená data, 36 dohodovací řízení, 30 syntetická data NZIS, 28 výkazy zdravotní péče.

**Vzorek F2 inventory (2026-05-20, 9 datasetů):**
- Skupina A — `rok` + agregovatelná metrika jako NKIS (7/9): NRHZS ATC, NICDZ pacienti, mortalita LPZ (1987-2024!), NKIS CMP, diabetes, hospitalizace (1994-2020!), mamografie pokrytí.
- Skupina B — `rok_porodu` / `rok_dg` (2/9): rodičky, NOR přežití. **Po opravě detekce `rok_*` patří do A.**
- Žádné selhání po opravě bugu (tempfile místo resp.raw).
- 5 datasetů z 207 je `.7z` (data.mzcr.cz NRHZS recepty/HVLP) — přeskočeno, vyžaduje py7zr.

**Why:** Ruční katalog v `sync_nkis.py` neškáluje. NZIP má strukturovaný sitemap → discovery realisticky proveditelný.
**How to apply:** Když Dan řekne "fáze 2", "bulk sync", "F2" — máme `scripts/sync_nzip.py` se třemi módy: výchozí (vzorek 9 IDs), `--all` (všech 207), `--ids id1,id2`. Output: `data/nzip/_inventory.json`. Související: [[project-datovy-brief]], [[feedback-no-abbreviations]].
