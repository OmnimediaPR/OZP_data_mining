---
name: feedback-popisna-data
description: "Dan často potřebuje jen prostá data popisující STAV, ne jen trendy/anomálie — nevyřazovat dataset jen proto, že jeho trend není smysluplný"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 446449e0-bd12-4472-a573-fcb73eb844ec
---

Dan: „Nejde mi vždy o trendy, často potřebujeme jen prostá data popisující stav."

**Why:** Nástroj (rozpadová kostka i obecně) má dvojí užití — (1) hledání anomálií/trendů pro PR úhly, (2) prostý popis stavu („kolik dávek HPV u dívek 13–14", „kolik hospitalizací pro X"). Já jsem nejdřív vyřadil očkování celé, protože jeho TRENDY klamou (spouštění programů = falešných +156000 %) — ale tím jsem zabil i jeho popisnou hodnotu, která je v pořádku.

**How to apply:** Když je u datasetu problém jen s trendem/anomáliemi (ne s daty samotnými), nevyřazovat ho — nechat jako popisnou kostku a jen vypnout sken anomálií (`noAnomalies: true` v configu bake_cube.mjs, panel anomálií se pak skryje). Viz [[project-rozpadova-kostka]]. Obecně: u nového datasetu zvážit i čistě popisné využití, ne jen „má to zajímavý trend?".
