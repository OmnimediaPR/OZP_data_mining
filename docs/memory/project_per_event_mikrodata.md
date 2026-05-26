---
name: project_per_event_mikrodata
description: "Jak zacházet s per-event mikrodaty (NZIS registry) v katalogu — count_rows duplikuje, řešení přes row_match"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8116bf70-e353-415a-a7c4-301d617d4f32
---

Hodně NZIS otevřených dat jsou **per-event mikrodata**: jeden řádek = jedna událost (porod, novorozenec, úmrtí, úraz, hospitalizace), hodnota je ve sloupcích-dimenzích/příznacích (0/1). Nástroj umí jen `count_rows` nebo `sum_column` po roce, takže:

- **Riziko duplicity:** `count_rows` na takové tabulce vrátí *celkový* počet událostí za rok. Deset různě nakrájených tabulek rodiček tak vykreslí tutéž čáru „počet porodů". Při zařazování takových sad vybírat jen ty, kde count dává distinktní smysl (potraty, císařské řezy = subset tabulka, vrozené vady), ne všechny.
- **Filtr na podskupinu přes `row_match`:** pole `row_match: {"column":"X","prefix":"1"}` v catalog.json nechá frontend i [[verify_parse]] počítat jen řádky, kde sloupec začíná daným prefixem. Tím jde z příznakové tabulky (0/1) udělat smysluplnou řadu — např. epidurál, diabetes v těhotenství, preeklampsie, epiziotomie (2026-05-25, batch_10). Před použitím ověřit kódování sloupce (`curl ... | csv tally`), že je opravdu 0/1.
- **Velikost:** mikrodatové soubory bývají obří (rodicky_cesko 2,6M, reprodukční události 17,7M řádků) — viz limit v [[project_frontend_parse_limity]]. Menší dimenzní tabulka často dá stejnou řadu jako velký „*_cesko" soubor, takže velký gzip není potřeba.

Vždy ověřit renderem ([[feedback_overit_render_datasetu]]) — count/filtr musí dát neprázdnou rozumnou řadu.
