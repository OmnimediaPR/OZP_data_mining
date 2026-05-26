---
name: reference-nrrz-novorozenci-ciselniky
description: "Oficiální číselníky NRRZ modulu Novorozenci (hmotnost, gestace, výživa, propuštění) z metodik ÚZIS"
metadata: 
  node_type: memory
  type: reference
  originSessionId: d50d76c4-53ca-47aa-8d82-3a33305e2a50
---

Oficiální kódy z metodik ÚZIS pro novorozenecké kostky (zdroj: PDF `beta-nzip.uzis.cz/data/nrrz/nrrz-metodicke-popisy/{nzip-id}-{slug}.pdf`, čte se přes Read na lokálně stažené PDF — WebFetch převod text rozbije). Sdílené napříč datasety 1611–1623, 1705, 2515.

**porodni_hmotnost / propusteni_hmotnost:** 1 = méně než 1500 g · 2 = 1500–2499 g · 3 = 2500–3499 g · 4 = 3500 g a více. (Pásma 1–2 = nízká porodní hmotnost.)
**gestacni_stari:** 1 = do 31+6 týdne · 2 = 32+0–36+6 · 3 = 37+0–38+6 · 4 = 39+0 a více. (Pásma 1–2 = předčasný porod, <37 tt.)
**pohlavi:** 1 = muž (u novorozenců raději „chlapec") · 2 = žena („dívka") · 3 = nespecifikováno.
**cetnost:** 1 = jednočetné · 2 = vícečetné (data až od 2000).
**kraj_bydliste:** standardní NUTS3 (KRAJ mapa v bake_cube.mjs) + CZ088 = bezdomovci · CZ099 = cizinci.
**vitalita:** 1 = živě narozené · 2 = mrtvě narozené.
**vrozena_vada:** 0/1 příznak (ne typ vady).
**propusteni_vyziva:** 0 = neuvedeno · 1 = výlučné kojení · 2 = dokrm formulí · 3 = formule (umělá výživa) · 4 = parenterální · 5 = úmrtí po porodu.
**propusteni_duvod:** 0 = neuvedeno · 1 = propuštění domů · 2 = překlad do léčebného zařízení · 3 = překlad do dětského domova · 4 = úmrtí · 5 = dovršení 3 měsíců věku.
**delka_zivota_prop** (délka hospitalizace): 0–6 = počet dní · 7 = 7–13 dní · 8 = 14 dní a více.
**propusteni_hlava** (obvod hlavy, jen od 2016, ~69 % prázdné): 1 = do 29 cm · 2 = 30–31 · 3 = 32–33 · 4 = 34–35 · 5 = 36–37 · 6 = 38+ cm. (Vynecháno z kostky — příliš řídké.)
**zpusob_porodu:** 1 = vaginální porod · 2 = císařský řez.

POZOR: `vek_matky` v novorozeneckých datasetech (1611–1705) je KRÁTKÝ kód 1–6 (= pětiletá pásma do 19 / 20–24 / … / 40+), NE 5místný NOR kód jako u [[project-rozpadova-kostka]] rodicky_sociodemografie.
