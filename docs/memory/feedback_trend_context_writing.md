---
name: feedback-trend-context-writing
description: "Při psaní trend_context pro nové datasety nepoužívat konkrétní kvantifikátory ('mírný', 'stabilní') před viděním reálných čísel — buď je napsat obecně, nebo až po runu skriptu."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1d7d5c17-dbc3-4075-96c6-b7cae79c577b
---

Při psaní `trend_context` pro nový dataset (NOR/NKIS/další) **nepoužívat konkrétní kvantifikátory** ("mírný nárůst", "relativně stabilní", "strmý vzestup") před tím, než script vyrobí JSON a uvidím skutečnou deltu.

**Why:** 2026-05-20 jsem při přidání 4 onko dg (slinivka, mozek, leukémie, žaludek) napsal "mírný nárůst" pro slinivku (+171%), "relativně stabilní" pro mozek (+184%) a "mírný nárůst" pro leukémii (+100%). Žádný z těchto textů neseděl na reálná čísla — Dan musel rozhodovat, co s nesedícími texty, a pak jsem je přepsal. Bylo to zbytečné kolečko.

**How to apply:** Když píšu trend_context pro neviděný dataset:
- Buď psát **obecně** ("Vývoj odráží X, Y a Z" / "Roli hraje stárnutí populace a lepší záchyt") — bez tvrzení o směru a strmosti.
- Nebo nechat trend_context zatím prázdný, pustit script, podívat se na deltu a teprve pak text napsat.
- "+170-185 % za 45 let" není "mírný" — odhady směru/strmosti dělat až s číslem před očima.
- Funguje to: u dalších 4 dg (lymfomy, ledvina, močový měchýř, štítná žláza) jsem psal obecně a texty seděly bez opravy.

Související: [[feedback-no-abbreviations]], [[project-nzip-discovery]].
