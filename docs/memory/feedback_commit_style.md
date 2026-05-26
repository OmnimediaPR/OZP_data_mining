---
name: feedback-commit-style
description: "Commit messages v Datovém briefu jsou terse — 1 řádka česky, max krátký druhý odstavec"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 169ab576-f827-4f8e-98da-6f07d383a113
---

Commit messages držet ve stylu projektu: **jedna česká věta v hlavičce**, případně 1–2 řádky upřesnění v těle. Žádné rozkecané sekce typu "Co odstraňuje / Co dál / Co bych příště / Co je hotovo".

**Why:** Dan amendnul commit `7ed0be8 → fc43386`, kde jsem do těla přidal 8 vymyšlených "Co …" sekcí. Žádný předchozí commit v repu takovou strukturu nemá — vzorek z logu: "přidej krajové časové řady (5 dg × 10 let × 14 krajů) + frontend heatmap", "přidej OECD healthcare expenditure — % HDP + per capita", "mortalita pohlavní splity — Hodgkin, B-NHL, slinivka, mozek, leukémie". Všechny jsou jednořádkové.

**How to apply:** Před psaním commit message kouknout do `git log --oneline -10` a držet se stejné délky/struktury. Pokud potřebuju doplnit kontext, max 1–2 řádky v těle, ne strukturované sekce. Nevymýšlet si formáty, které v repu neexistují.

Souvisí s [[feedback-workflow]] (terse, česky, bez žargonu).
