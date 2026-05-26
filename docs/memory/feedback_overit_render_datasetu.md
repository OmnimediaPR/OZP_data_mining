---
name: feedback_overit_render_datasetu
description: "Před přidáním datasetu ověřit, že se reálně načte a dá smysluplnou řadu — ne jen že URL platí"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8116bf70-e353-415a-a7c4-301d617d4f32
---

Při přípravě batch dávek do `data/catalog.json` nestačí ověřit, že `csv_url` vrací HTTP 200. Je třeba ověřit, že dataset projde celým řetězcem `parseDataset` (stažení → rozbalení/dekódování → agregace) a vrátí neprázdnou rozumnou časovou řadu.

**Proč:** 2026-05-25 jsem přidal do katalogu ~7 datasetů, u kterých jsem zkontroloval jen platnost URL. Část z nich se v prohlížeči vůbec nevykreslila (gzip se nerozbaloval, `date_to_year` neměl ve frontendu větev, soubory s miliony řádků padaly). Muselo se to zpětně opravovat a 4 datasety vyřadit. Viz [[project_frontend_parse_limity]].

**How to apply:** Použít `scripts/verify_parse.mjs <id...>` — napodobuje frontend parse (gzip, encoding, všechny agregace) a vypíše počet řádků, rozbalenou velikost a prvních/posledních pár bodů série. Spustit na každý nový dataset s gzip/windows-1250/date agregací nebo velkým zdrojem dřív, než dávku označím za hotovou. Zapadá do [[feedback_workflow]] (ukazovat reálné výstupy, ne tvrdit hotovo bez ověření).
