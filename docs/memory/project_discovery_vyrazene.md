---
name: project-discovery-vyrazene
description: Co zbývá z dříve vyřazených datasetů po záchraně novorozenecké rodiny (kandidáti na příští kostky)
metadata: 
  node_type: memory
  type: project
  originSessionId: d50d76c4-53ca-47aa-8d82-3a33305e2a50
---

Schvalovací kampaň (11 dávek, 99 schválených datasetů) je KOMPLETNÍ — všechny v katalogu (ověřeno přes source_url/slug, 2026-05-26). Z 22 dříve vyřazených/nedohledaných draftů (drafty v `docs/discovery/catalog_drafts.json` minus 99 schválených) jsme zachránili 7 novorozeneckých jako kostky (viz [[project-rozpadova-kostka]]).

**Zachráněno (commity 136fb02 / 844fd4c / 10fe406, 2026-05-26, katalog 121→123):**
- `umrti_sociodemo` (2517/NR-06-34, gz 3,46 mil. úmrtí 1994–2024) — příčina (kapitola MKN) × věk × pohlaví × rodinný stav × kraj. POZOR vzdělání 97 % prázdné (eviduje až od 2024) → vynecháno. Číselník rodinného stavu z metodiky (1=svobodní…4=ovdovělí, 5–7 partnerství). 5,4 MB — největší kostka. Engine doplněn `map:'KRAJ_OKRES'` (okres CZ0525 → kraj CZ052).
- `preventivni_prohlidky` (1781/PPS-08-01) — POZOR **4,56 GB / 145,9 mil. řádků** (populační mikrodata, 1 pojištěnec/rok). Stáhnout `curl -C - --retry` do /tmp (40 GB volných) pak `CUBESRC_`; bake ~9 min. Wide: praktik/zubař × věk × pohlaví × kraj, 2010–2023. Jen POČTY využití, ne pokrytí (lidé bez prohlídky v datech nejsou). Engine doplněn dekodér věku `age5` (přesný věk 0–95 → 5letá pásma, strop 85+).
- `hospitalizace_dlouhodoba` (2521/NR-05-01, gz 11,3 mil. řádků) — diagnóza (kapitola MKN) × druh přijetí × operace × úmrtí v nemocnici × věk × pohlaví, sum pocet_hosp, 1994–2024. POZOR: kvůli GDPR vyřazeny A50–A64, B15–B19, B20–B24 a **celé F10–F99** (kapitola duševní téměř prázdná); „ostatni" diagnózy (~53 tis. řádků) nemají kapitolu MKN → vypadnou. Nemocniční úmrtnost ~3,4 %, plánovaná přijetí ~42 %.

- `luzkova_pece_migrace` (1922/NR-04-38, gz 12,8 mil. řádků 2010–2024) — kraj bydliště pacienta × kraj poskytovatele × diagnóza (kapitola MKN) × operace, sum pocet_hosp. Migrace za péčí: ~17 % léčeno mimo domovský kraj, Praha přitahuje 45 % mimopražských. Věk/pohlaví vynechány (ať kostka nenabobtná), 1,5 MB. „ostatní" diagnózy (~1,4 %) vypadnou.

- `kolorektum_cekaci_doba` (2328/PPS-02-07, malé 99 KB) — průměrná čekací doba na navazující kolonoskopii po pozitivním screeningu. POZOR je to PRŮMĚR dní (nejde sčítat ani jako count/sum/wide kostka). Řešeno jako **plochý dataset `source_type:'regional_timeseries'`** s předpečenou řadou `series:[{year,kraj_kod,kraj_nazev,value}]` přímo v katalogu (frontend ji čte přes parseDataset, řádek 51 App.jsx, CSV nestahuje) → vykreslí se komponentou `RegionalHeatmap` (kraje × roky, intenzita = hodnota). Hodnota = roční krajský průměr (mean kvartálních dny_prumer_kraj). Národní průměr vzrostl 61→84 dní (2019→2024). **První reálné použití regional_timeseries** (feature byla v kódu, nepoužitá) — ověřeno Playwrightem, 84 buněk, 0 chyb. Pozn.: pro lokální dev test nutno `cp data/catalog.json frontend/public/data/` (public je git-ignored, deploy.yml to dělá při buildu). Tenhle vzor (regional_timeseries heatmapa) je cesta pro JAKÁKOLIV předagregovaná průměrová/krajská data, která nejdou do kostky.

**Zbývá ~8 nezařazených, vesměs problematických:**
- **NRHZS technické léky/výkony** (sum_column, dvojí počítání přes překrývající se kategorie): `hromadne_vyrabene_lecive_pripravky_1/3_uroven_atc`, `zvlast_uctovane_lecive_pripravky_sukl_atc_aktualni`, `vykony_zdravotni_pece_forma_odbornost`.
- **Problematická agregace:** `polymorbidita_obyvatel_kraj_bydliste` (sčítá index DCCI — nesmysl jako suma), `rocni_vykazy_ambulantni_pece` (míchá indikátory v jednom sloupci `hodnota`), `kolorektum_cekaci_doba` (je to PRŮMĚR dnů — nelze sčítat jako kostku).
- **Velké, čisté, ale úzké:** `migrace_luzkova_pece` (12,8M, přesuny mezi lůžkovými zařízeními).
- **Reprodukce zbytky:** `rodicky_robsonova_klasifikace` (jen 2021–2022, tenký — spíš snímek), `rodicky_cesko` (sum prenatálních kontrol), `reprodukcni_zdravotni_udalosti` (míchá potraty/porody/covid — chaotické).

Před stavbou každé ověřit strukturu hlavičky (`docs/discovery/dataset_headers.json`) a zda agregace nezdvojuje (mikrodata → dimenze/wide, viz [[project-per-event-mikrodata]] a [[reference-nrrz-novorozenci-ciselniky]]).
