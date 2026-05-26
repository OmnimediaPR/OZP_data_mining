---
name: project-datovy-brief
description: "Interní nástroj \"Datový brief\" Omnimedia — architektura a stav (k 2026-05-19)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 515778d3-c543-4184-8c41-654cae25cd79
---

**Co to je:** Interní webový nástroj Omnimedia PR pro generování PR podkladů ze zdravotnických dat. Repo: `OZP_data_mining`, větev `main`, uživatel `Jellyman-creator`.

**Architektura:**
- Frontend: React + Vite, hostovaný na **GitHub Pages** (base path `/datovy-brief/`).
- Data: JSON soubory v `data/nkis/` (národní data) a `data/international/` (mezinárodní).
- Sběr dat: GitHub Actions cron 1× měsíčně (`.github/workflows/sync-nkis.yml`) spouští `scripts/sync_nkis.py`, který stahuje xlsx z **ÚZIS / NZIS** (datanzis.uzis.gov.cz) a parsuje je do JSONu.
- Anthropic API se volá **z prohlížeče** (žádný backend), klíč zadává každý uživatel sám.
- **Žádný backend, žádná databáze.**

**Datasety (z `data/catalog.json`):**
- Národní (NKIS, 7 ks): aim (I21-I22), fs (I48), hf (I50), i35 (I35), i71 (I71), cmp (I60-I64), hyp (I10)
- Mezinárodní (hardcoded/JSON, 4 ks): Eurostat (hlth_cd_aro, hlth_cd_asdr2), OECD 2025, MedPed FH detection

**Why:** Dan ho používá pro tvorbu PR briefů pro klienty ze zdravotnictví — čísla z reálných zdrojů místo intuice.
**How to apply:** Když se mě Dan ptá na "data", "dataset", "sync" — myslí tohle. Frontend je vždy GitHub Pages, sběr dat vždy přes Actions cron.
