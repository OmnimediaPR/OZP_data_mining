---
name: feedback-no-abbreviations
description: "V lidsky čitelných polích datasetů (human_name, description, relevant_for, trend_context, metric_label) nikdy nepoužívej zkratky — české ani zahraniční. Zkratky a kódy patří jen do label a code."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c5004dcd-fe92-40cc-90b8-714b5fa7dda7
---

V polích `human_name`, `description`, `relevant_for`, `trend_context` (a pravděpodobně i `metric_label`) v definicích datasetů — jak NKIS v `scripts/sync_nkis.py`, tak mezinárodních v `INTL_DATASETS` v `frontend/src/App.jsx` — **nikdy nepoužívej zkratky**. České zkratky rozepiš doslovně:

- AIM → akutní infarkt myokardu
- KVO → kardiovaskulární onemocnění
- FH → dědičně vysoký cholesterol
- ICHS → ischemická choroba srdeční
- CMP → cévní mozková příhoda

Zahraniční odborné termíny přelož (např. „stroke center" → „centrum pro léčbu cévních mozkových příhod"). Běžně zažitá zkrácení („ČR", „Cca") jsou OK — Dan je v textech sám používá.

Zkratky a klasifikační kódy patří **výhradně** do technických polí `label` a `code`.

**Why:** Datový brief je nástroj pro PR profesionály a netechnické čtenáře. Zkratky jako AIM/KVO/FH jsou bariéra pro porozumění. Systémový design — lidská pole v každém datasetu — má smysl jen tehdy, když ta pole opravdu lidsky čtou. Dan tohle pravidlo explicitně zavedl při finalizaci redesignu karet datasetů a chce, aby platilo i pro budoucí přidávané datasety.

**How to apply:** Vždycky když přidávám nebo upravuji dataset v `DATASETS` (sync_nkis.py) nebo `INTL_DATASETS` (App.jsx), zkontroluj všech pět lidských polí na zkratky. Pokud návrh obsahuje zkratku, rozepiš ji bez vyzvání. Související: [[project_datovy_brief]].
