---
name: project_frontend_parse_limity
description: Co frontend parseDataset umí načíst a kde je limit velikosti CSV pro on-demand fetch v prohlížeči
metadata: 
  node_type: memory
  type: project
  originSessionId: 8116bf70-e353-415a-a7c4-301d617d4f32
---

`frontend/src/App.jsx` → `parseDataset` (on-demand fetch, viz [[project_nova_architektura]]) po opravě z 2026-05-25 podporuje: agregace `sum_column`, `count_rows`, `date_to_year`, `last_in_year`; rozbalování gzip přes `DecompressionStream` (zdroj posílá `.csv.gz` jako `application/x-gzip` BEZ `Content-Encoding`, prohlížeč ho sám nerozbalí); dekódování `windows-1250` přes `TextDecoder`; očištění BOM z názvů sloupců v katalogu.

> **AKTUALIZACE 2026-05-25 (pozdější):** Tento limit je teď z velké části OBEJITÝ — časové řady se předpočítají skriptem `scripts/bake_series.mjs` a uloží do `catalog.json` jako pole `series`. Frontend `parseDataset` vrací `entry.series` rovnou a CSV v prohlížeči už nestahuje (živý fetch zůstal jen jako záloha pro nenapečené datasety). Skript běží v Node (větší paměť) a obří soubory zpracovává **streamováním po řádcích** (covid 1,4 GB napečen za ~235 s). Browserový limit níže tak platí už jen pro hypotetický fallback. Viz [[project_nova_architektura]].

**Tvrdý limit (historicky, pro živý fetch v prohlížeči): velikost souboru, ne formát.** On-demand fetch stahoval a parsoval celé CSV v prohlížeči. Per-event registry s miliony řádků se nenačtou nebo shodí záložku:
- ~800 tis. řádků / ~90 MB rozbaleno = funguje, ale load ~15–20 s (dopravní úrazy, akutní intenzivní péče ~1,4 mil.)
- 3,5 mil.+ řádků / >300 MB = riskantní pád
- 11 mil. řádků / >700 MB = OOM, nenačte se vůbec

Proto byly 2026-05-25 vyřazeny: úrazy (435 MB), dlouhodobá hospitalizace (11,3M), jednotlivá úmrtí (3,46M), covid základní přehled (1 řádek, není časová řada). Při zařazování dalších datasetů kontrolovat počet řádků / rozbalenou velikost — viz [[feedback_overit_render_datasetu]].
