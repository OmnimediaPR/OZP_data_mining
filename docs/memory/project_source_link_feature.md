---
name: project-source-link-feature
description: Odkaz na datový zdroj u každé teze v analýze i docx — HOTOVO a nasazeno
metadata: 
  node_type: memory
  type: project
  originSessionId: d50d76c4-53ca-47aa-8d82-3a33305e2a50
---

HOTOVO (commit 37ba146, 2026-05-26, ověřeno na živém webu). Každá klíčová teze v analytické části má ověřitelný odkaz na datový zdroj, aby si ji lidé mohli ověřit. Platí pro **klíčová zjištění (key_findings) i doporučené úhly (angles)**, na obrazovce i v docx.

**Schéma odpovědi AI (kontrakt — neměnit bez úpravy renderu):** `key_findings[].dataset` = id jednoho datasetu, `angles[].datasets` = pole id (úhel může stát na víc zdrojích). Prompt v `frontend/src/App.jsx` má sekci „OVĚŘITELNOST ZDROJŮ" — model musí u každé teze uvést id z `[id: ...]`, jinak tezi neuvádět.

**Render:** `AnalysisView` (angles) zobrazuje řádek „Zdroj:" s klikacími odkazy na `source_url`; key_findings to měly už dřív. V docx helper `srcParas(ids)` přidává „Zdroj: název — URL" pod zjištění i úhly (`findDatasetById` mapuje id→dataset). Defenzivní: chybí-li `datasets`, řádek se prostě nezobrazí (nespadne). URL se v docx vypisuje jako barevný text (ne hyperlink-objekt) — stejně jako globální sekce „Zdroje".

**Why:** Dan (PR) potřebuje, aby každé tvrzení v briefu šlo dohledat ke zdroji. **How to apply:** při úpravách analytického promptu/renderu zachovat pole `dataset`/`datasets` a zobrazení zdroje. Navazuje na [[project-datovy-brief]].
