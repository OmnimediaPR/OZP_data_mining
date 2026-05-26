---
name: reference-ozp-branding
description: Barevná paleta OZP (z jejich CSS) + stav rebrandu frontendu Datového briefu do grafiky OZP
metadata: 
  node_type: memory
  type: reference
  originSessionId: 446449e0-bd12-4472-a573-fcb73eb844ec
---

Frontend Datového briefu byl 2026-05-25 přebarven do grafiky OZP (commit `b0d7e51`).

**Paleta OZP** (vytaženo z `https://www.ozp.cz/web/css/style.css`):
- Primární fialová: `#702082` (hlavička, hlavní tlačítka, nadpisová čísla, výplň checkboxů)
- Akcentní oranžová: `#ed8b00` (klíčová čísla, zvýraznění ČR/peak)
- Tmavší varianty: fialová `#682e7f`/`#61257f`, oranžová `#ba6d00`
- Světle fialové panely: `#f6f4f9`, `#ece6f1`; v našem kódu používám `#F4F1F8` (panely) a `#E0D6EA` (rámečky)
- Text `#333`, pozadí bílé, bezpatkové písmo (Source Sans 3), zaoblené rohy + měkké stíny
- Logo: bílé SVG, uložené v repu jako `frontend/src/assets/ozp-logo.svg` (importované přes Vite). Funguje jen na fialovém pozadí.

**Co bylo změněno:** pole „Klient" + menu smazáno (klient držen napevno `const CLIENT = {id:'ozp', full:'Oborová zdravotní pojišťovna'}`), Téma briefu je prázdný zaoblený chat-box (textarea s placeholderem). Top bar: fialový s logem OZP vlevo, „by Omnimedia PR" vpravo.

**Export do .docx** (`exportToDocx` v `App.jsx`) je taky sjednocený do OZP barev (commit `b51b293`): tmavý box → fialový `702082`, klíčová čísla + nadpis „NEPODPORUJÍ" → oranžová `ED8B00`, světlý panel → `F2ECF7`, rámečky tabulek → `DDD2E5`, odkaz na zdroj → fialový. Proměnné v docx helperech přejmenovány `lightBlue`→`lightPurple`, `dark`→`purpleBox`. V docx se barvy píšou jako holé hex BEZ `#`.

Souvisí s [[project-nova-architektura]].
