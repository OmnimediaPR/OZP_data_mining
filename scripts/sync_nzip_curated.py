"""
sync_nzip_curated.py — kurátorovaná synchronizace dat z NZIP otevřených dat

Cíleně vybrané datasety z NZIP otevřených dat (mimo NKIS kardio a NOR onko),
parsované s lidsky popsanými metadaty pro Datový brief.

Na rozdíl od sync_nzip.py (který dělá inventory všech 207 NZIP datasetů
s automatickým parsováním struktur), tento skript:
- vybírá konkrétní zajímavé datasety
- pro každý definuje year_col + metric_col + lidský popis bez zkratek
- agreguje metric_col per rok (sum) a ukládá jako brief-ready JSON

Spouští se přes GitHub Actions (viz .github/workflows/sync-nzip-curated.yml)
nebo ručně:    python scripts/sync_nzip_curated.py

Závislosti:    pip install requests
"""

import csv
import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import requests

OUT_DIR = Path(__file__).parent.parent / "data" / "nzip_curated"

# Definice kurátorovaných datasetů. Per dataset:
#   data_url, source_url (NZIP stránka), year_col, metric_col,
#   plus všechna lidsky popsaná pole (human_name, description, ...).
DATASETS = {
    "tuberkuloza_incidence": {
        "label": "Tuberkulóza — incidence",
        "human_name": "Tuberkulóza",
        "description": "Bakteriální infekční nemoc, typicky postihující plíce. V Česku patří k onemocněním, která byla historicky velmi rozšířená, dnes je výskyt nízký, ale neopomíjený — vyžaduje dlouhodobou léčbu a sledování.",
        "code": "A15–A19",
        "source": "Registr tuberkulózy (ÚZIS)",
        "source_type": "national",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově hlášených případů",
        "relevant_for": [
            "infekční nemoci",
            "veřejné zdraví",
            "očkování",
            "migrace",
        ],
        "trend_context": "Dlouhodobý pokles odráží zlepšení životních podmínek, plošné očkování BCG (dnes již necelé) a moderní léčbu. V posledních letech může výskyt mírně kolísat v důsledku migrace a sociálních faktorů.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-30-RTBC/NR-30-01/Otevrena-data-NR-30-01-tuberkuloza-epidemiologie.csv",
        "source_url": "https://www.nzip.cz/data/2671-tuberkuloza-epidemiologie-otevrena-data",
        "year_col": "rok_hlaseni",
        "metric_col": "pripady",
        "agg_func": "sum",
    },
    "sebevrazdy_hospitalizace": {
        "label": "Pokusy o sebevraždu — hospitalizace",
        "human_name": "Hospitalizace pacientů po pokusu o sebevraždu",
        "description": "Roční počet hospitalizací pacientů, kteří byli přijati po pokusu o sebevraždu. Klíčový ukazatel duševního zdraví populace a dostupnosti psychiatrické péče.",
        "code": "X60–X84",
        "source": "Národní informační systém péče o duševní zdraví (ÚZIS)",
        "source_type": "national",
        "metric": "hospitalizace_rocni",
        "metric_label": "Roční počet hospitalizací",
        "relevant_for": [
            "duševní zdraví",
            "veřejné zdraví",
            "krizová intervence",
            "psychiatrická péče",
        ],
        "trend_context": "Vývoj odráží kombinaci sociálních faktorů (ekonomické krize, pandemie, krize bydlení), dostupnosti psychiatrické péče a rozšiřování center duševního zdraví. Sledování pokusů o sebevraždu doplňuje statistiku dokonaných sebevražd v ČSÚ.",
        "data_url": "https://datanzis.uzis.gov.cz/data/OIS-04-NISDZ/OIS-04-18/Otevrena-data-OIS-04-18-hospitalizace-pacientu-pokus-o-sebevrazdu.csv",
        "source_url": "https://www.nzip.cz/data/2664-hospitalizace-pacientu-pokus-o-sebevrazdu-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_hospitalizaci",
        "agg_func": "sum",
    },
    "autismus_deti_incidence": {
        "label": "Děti a mladiství s poruchami autistického spektra — incidence",
        "human_name": "Děti a mladiství s poruchami autistického spektra",
        "description": "Roční počet dětí a mladistvých s diagnostikovanou poruchou autistického spektra. Zahrnuje dětský autismus, atypický autismus, Aspergerův syndrom a další pervazivní vývojové poruchy.",
        "code": "F84",
        "source": "Národní informační systém péče o duševní zdraví (ÚZIS)",
        "source_type": "national",
        "metric": "pacienti_rocni",
        "metric_label": "Roční počet pacientů",
        "relevant_for": [
            "duševní zdraví",
            "dětská psychiatrie",
            "vývojové poruchy",
            "vzdělávání",
        ],
        "trend_context": "Nárůst odráží především lepší záchyt — rozšířené screeningové nástroje, vyšší informovanost rodičů a pediatrů, dostupnost specializované diagnostiky. Reálná prevalence poruch autistického spektra je v populaci stabilní, ale dříve byla velká část případů nediagnostikovaná.",
        "data_url": "https://datanzis.uzis.gov.cz/data/OIS-04-NISDZ/OIS-04-17/Otevrena-data-OIS-04-17-deti-a-mladistvi-poruchy-autistickeho-spektra.csv",
        "source_url": "https://www.nzip.cz/data/2663-deti-a-mladistvi-poruchy-autistickeho-spektra-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_pacientu",
        "agg_func": "sum",
    },
    "pohlavni_nemoci_incidence": {
        "label": "Pohlavní nemoci — incidence",
        "human_name": "Pohlavní nemoci v ČR",
        "description": "Roční počet hlášených případů pohlavně přenosných nemocí (například syfilis, kapavka, chlamydie). Patří k nejdéle sledovaným epidemiologickým ukazatelům v ČR.",
        "code": "A50–A64",
        "source": "Registr pohlavních nemocí (ÚZIS)",
        "source_type": "national",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet hlášených případů",
        "relevant_for": [
            "infekční nemoci",
            "sexuální zdraví",
            "veřejné zdraví",
            "prevence",
        ],
        "trend_context": "Vývoj odráží změny v sexuálním chování, dostupnost testování a osvětu. V posledních letech v Česku narůstá syfilis a kapavka, zejména u mladších věkových skupin a v některých populačních podskupinách.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-29-RPN/NR-29-01/Otevrena-data-NR-29-01-pohlavni-nemoci.csv",
        "source_url": "https://www.nzip.cz/data/2639-pohlavni-nemoci-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_pripadu",
        "agg_func": "sum",
    },
    "preventivni_prohlidky_pokryti": {
        "label": "Preventivní prohlídky — pokrytí populace",
        "human_name": "Pokrytí populace preventivními prohlídkami",
        "description": "Procento pojištěnců v cílové populaci, kteří absolvovali preventivní prohlídku u praktického lékaře. Klíčový ukazatel základní péče o veřejné zdraví.",
        "code": "preventivní prohlídky",
        "source": "Centrální evidence dat populačních preventivních programů (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí populace (%)",
        "relevant_for": ["prevence", "veřejné zdraví", "primární péče", "pojišťovny"],
        "trend_context": "Vývoj odráží osvětu o významu prevence, dostupnost praktických lékařů a motivaci pacientů. V Česku je preventivní prohlídka hrazena pojišťovnou jednou za dva roky.",
        "data_url": "https://datanzis.uzis.gov.cz/data/PPS-08-PREVENCE/PPS-08-03/Otevrena-data-PPS-08-03-preventivni-prohlidky-pokryti.csv",
        "source_url": "https://www.nzip.cz/data/2579-preventivni-prohlidky-pokryti-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_vysetrenych",
        "denominator_col": "populace",
    },
    "kolorektum_screening_pokryti": {
        "label": "Kolorektální screening — pokrytí cílové populace",
        "human_name": "Pokrytí populace kolorektálním screeningem",
        "description": "Procento osob z cílové věkové populace (50 let a více), které absolvovaly preventivní vyšetření na rakovinu tlustého střeva (test na skryté krvácení nebo kolonoskopii) v tříletém intervalu.",
        "code": "screening C18–C20",
        "source": "Informační systém screeningu karcinomu tlustého střeva a konečníku (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí populace (%)",
        "relevant_for": ["prevence", "screening tlustého střeva", "veřejné zdraví", "pojišťovny"],
        "trend_context": "Vývoj odráží osvětu (mediální kampaně) a aktivní zvaní pojišťoven od roku 2014. Cílová populace je ženy i muži 50 a více let.",
        "data_url": "https://datanzis.uzis.gov.cz/data/PPS-02-KRK/PPS-02-08/Otevrena-data-PPS-02-08-kolorektum-screening-pokryti-populace-trilete.csv",
        "source_url": "https://www.nzip.cz/data/2601-kolorektum-screening-pokryti-populace-trilete-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_vysetreni",
        "denominator_col": "populace",
    },
    "prostata_psa_pokryti": {
        "label": "Vyšetření krve na prostatický specifický antigen — pokrytí mužů",
        "human_name": "Pokrytí mužů vyšetřením krve na prostatický specifický antigen",
        "description": "Procento mužů, kteří absolvovali vyšetření krve na prostatický specifický antigen (test pro časný záchyt rakoviny prostaty). V Česku není plošný screening, vyšetření probíhá v rámci preventivní prohlídky nebo na žádost pacienta.",
        "code": "screening C61",
        "source": "Informační systém screeningu karcinomu prostaty (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí mužů (%)",
        "relevant_for": ["prevence", "mužské zdraví", "preventivní prohlídky"],
        "trend_context": "Vývoj odráží osvětu o významu vyšetření u mužů starších 50 let a doporučení odborných společností. Plošný screening v Česku zatím není zaveden, debata o jeho přínosu i rizicích pokračuje.",
        "data_url": "https://datanzis.uzis.gov.cz/data/PPS-05-PROSTATA/PPS-05-01/Otevrena-data-PPS-05-01-prostata-podil-vystrenych-psa.csv",
        "source_url": "https://www.nzip.cz/data/2616-prostata-podil-vysetrenych-psa-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_vysetrenych",
        "denominator_col": "populace",
    },
    "autismus_vcasny_zachyt_pokryti": {
        "label": "Včasný záchyt poruch autistického spektra — pokrytí pojištěnců",
        "human_name": "Pokrytí pojištěnců včasným záchytem poruch autistického spektra (ve věku 2 let)",
        "description": "Procento dětských pojištěnců, kteří absolvovali standardizovaný screening poruch autistického spektra ve věku 2 let (M-CHAT-R nebo podobný test).",
        "code": "screening F84",
        "source": "Další prevence u novorozenců a dětí (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí pojištěnců (%)",
        "relevant_for": ["dětská psychiatrie", "vývojové poruchy", "prevence", "primární péče"],
        "trend_context": "Vývoj odráží zavedení plošného screeningu poruch autistického spektra do preventivních prohlídek u dětského lékaře. Časný záchyt umožňuje včasnou intervenci, která zlepšuje vývoj dítěte.",
        "data_url": "https://datanzis.uzis.gov.cz/data/PPS-09-DETI/PPS-09-02/Otevrena-data-PPS-09-02-vcasny-zachyt-poruchy-autistickeho-spektra.csv",
        "source_url": "https://www.nzip.cz/data/2649-vcasny-zachyt-poruchy-autistickeho-spektra-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_vysetrenych",
        "denominator_col": "pocet_pojistencu",
    },
    "kycle_screening_pokryti": {
        "label": "Screening dysplazie kyčelního kloubu — pokrytí novorozenců",
        "human_name": "Pokrytí novorozenců screeningem dysplazie kyčelního kloubu (ve věku 1 roku)",
        "description": "Procento novorozenců, kteří absolvovali alespoň jedno preventivní ultrazvukové vyšetření kyčelních kloubů. Patří k dlouhodobě nejúspěšnějším českým preventivním programům.",
        "code": "screening Q65",
        "source": "Další prevence u novorozenců a dětí (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí novorozenců (%)",
        "relevant_for": ["dětské zdraví", "prevence", "ortopedie", "primární péče"],
        "trend_context": "Vývoj odráží zavedení tříkolového screeningu (1, 6 a 12 týdnů věku). Včasný záchyt dysplazie umožňuje neoperativní léčbu (Pavlíkovy třmeny) a předchází invalidizujícím změnám v dospělosti.",
        "data_url": "https://datanzis.uzis.gov.cz/data/PPS-09-DETI/PPS-09-03/Otevrena-data-PPS-09-03-screening-kycle.csv",
        "source_url": "https://www.nzip.cz/data/2711-screening-kycle-otevrena-data",
        "year_col": "rok_narozeni",
        "agg_func": "ratio",
        "numerator_col": "pocet_jeden_screening",
        "denominator_col": "populace",
    },
    "ocekavatelna_umrti": {
        "label": "Očekávatelná úmrtí — časový trend",
        "human_name": "Očekávatelná úmrtí v ČR",
        "description": "Roční počet úmrtí, která lze dopředu očekávat — typicky u pacientů s chronickým onemocněním v terminální fázi. Klíčový ukazatel pro plánování paliativní a hospicové péče.",
        "code": "paliativní péče",
        "source": "List o prohlídce zemřelého (ÚZIS)",
        "source_type": "national",
        "metric": "umrti_rocni",
        "metric_label": "Roční počet úmrtí",
        "relevant_for": ["paliativní péče", "stárnutí populace", "veřejné zdraví", "hospice"],
        "trend_context": "Vývoj odráží stárnutí populace a nárůst chronických onemocnění. Předem očekávatelná úmrtí představují cílovou skupinu paliativní péče — důstojné konce života v hospicích, na specializovaných odděleních nebo doma s péčí mobilního hospice.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-06-LPZ/NR-06-39/Otevrena-data-NR-06-39-ocekavatelne-umrti-vek-pohlavi-kraje-casovy-trend.csv",
        "source_url": "https://www.nzip.cz/data/2693-ocekavatelne-umrti-vek-pohlavi-kraje-casovy-trend-otevrena-data",
        "year_col": "rok",
        "metric_col": "ocekavatelne_zemreli_pocet",
        "agg_func": "sum",
    },
    "alergicka_ryma_dispenzarizovani": {
        "label": "Alergická rýma — dispenzarizovaní pacienti",
        "human_name": "Pacienti s alergickou rýmou",
        "description": "Roční počet dispenzarizovaných (dlouhodobě sledovaných) pacientů s alergickou rýmou. Roste jako součást širšího fenoménu nárůstu alergických onemocnění v moderní populaci.",
        "code": "J30",
        "source": "Národní registr hrazených zdravotních služeb (ÚZIS)",
        "source_type": "national",
        "metric": "prevalence_rocni",
        "metric_label": "Roční počet sledovaných pacientů",
        "relevant_for": ["alergologie", "chronická onemocnění", "kvalita ovzduší", "imunita"],
        "trend_context": "Nárůst odráží 'epidemii alergií' v moderních populacích — souvisí s tzv. hygienickou hypotézou (děti vyrůstají ve sterilnějším prostředí, imunitní systém přepíná na alergické reakce), kvalitou ovzduší a vyšším výskytem polenu kvůli změnám klimatu.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-04-NRHZS/NR-04-89/Otevrena-data-NR-04-89-alergicka-ryma.csv",
        "source_url": "https://www.nzip.cz/data/2646-alergicka-ryma-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet",
        "agg_func": "sum",
    },
    "vrozene_vady": {
        "label": "Vrozené vady — incidence",
        "human_name": "Vrozené vady u novorozenců",
        "description": "Roční počet novorozenců s vrozenou vadou. Sleduje se více než 12 hlavních diagnostických kategorií. Klíčový ukazatel pro prenatální péči a genetické poradenství.",
        "code": "Q00–Q99",
        "source": "Národní registr reprodukčního zdraví — modul vrozených vad (ÚZIS)",
        "source_type": "national",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet novorozenců s vrozenou vadou",
        "relevant_for": ["dětské zdraví", "genetika", "prenatální péče", "vzácná onemocnění"],
        "trend_context": "Vývoj odráží kombinaci kvality prenatální péče (časný záchyt, ukončení rizikových těhotenství), genetického poradenství a změn v reprodukčním chování (vyšší věk rodiček). Část kolísání jsou statistické fluktuace u vzácných vad.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-13-NRRZ-VV/NR-13-02/Otevrena-data-NR-13-02-vrozene-vady-cesko.csv",
        "source_url": "https://www.nzip.cz/data/2669-vrozene-vady-cesko-otevrena-data",
        "year_col": "rok_narozeni",
        "agg_func": "count",
    },
    "lazenska_pece_pacienti": {
        "label": "Lázeňská péče — pacienti",
        "human_name": "Pacienti s hrazenou lázeňskou péčí",
        "description": "Roční počet pacientů, kteří absolvovali komplexní nebo příspěvkovou lázeňskou péči hrazenou zdravotními pojišťovnami. Česká specifika — lázeňství má v ČR dlouhou tradici a je nadstandardním benefitem proti většině jiných zemí.",
        "code": "rehabilitace",
        "source": "Národní registr hrazených zdravotních služeb (ÚZIS)",
        "source_type": "national",
        "metric": "pacienti_rocni",
        "metric_label": "Roční počet pacientů",
        "relevant_for": ["rehabilitace", "kvalita života", "chronická onemocnění", "pojišťovny"],
        "trend_context": "Vývoj odráží legislativní změny (úpravy podmínek hrazení), epidemii covidu (přerušení v roce 2020) a stárnutí populace. Lázeňská péče je hrazena u definovaných indikací (po operacích, chronická onemocnění pohybového aparátu, neurologické nemoci a další).",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-04-NRHZS/NR-04-90/Otevrena-data-NR-04-90-lazenska-pece-pacienti.csv",
        "source_url": "https://www.nzip.cz/data/2651-lazenska-pece-pacienti-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet",
        "agg_func": "sum",
    },
    "paliativni_pece_pacienti": {
        "label": "Paliativní péče — unikátní pacienti",
        "human_name": "Unikátní pacienti s vykázanou paliativní péčí",
        "description": "Roční počet unikátních pacientů, u kterých byla vykázána paliativní péče (odbornost 929 nebo DRG markery paliativní péče). Klíčový ukazatel rozšíření paliativní péče v Česku.",
        "code": "paliativní péče",
        "source": "Národní informační systém paliativní péče (ÚZIS)",
        "source_type": "national",
        "metric": "pacienti_rocni",
        "metric_label": "Roční počet unikátních pacientů",
        "relevant_for": ["paliativní péče", "kvalita života", "stárnutí populace", "hospice"],
        "trend_context": "Vývoj odráží postupný rozvoj paliativní péče v Česku — zvyšuje se počet specializovaných zařízení (mobilní hospice, paliativní oddělení v nemocnicích), roste informovanost lékařů i pacientů. Stále existuje výrazná regionální nerovnost dostupnosti.",
        "data_url": "https://datanzis.uzis.gov.cz/data/OIS-05-NISPP/OIS-05-06/Otevrena-data-OIS-05-06-unikatni-pacienti-vykazana-pece-odbornost-929-drg-markery.csv",
        "source_url": "https://www.nzip.cz/data/2657-unikatni-pacienti-vykazana-pece-odbornost-929-drg-markery-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet",
        "agg_func": "sum",
    },
    "mamografie_screening_pokryti": {
        "label": "Mamografický screening — pokrytí cílové populace",
        "human_name": "Pokrytí žen mamografickým screeningem",
        "description": "Procento žen v cílové věkové skupině (45+ let), které absolvovaly mamografické vyšetření v rámci screeningu rakoviny prsu.",
        "code": "screening C50",
        "source": "Informační systém screeningu karcinomu prsu (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí cílové populace (%)",
        "relevant_for": ["prevence", "ženské zdraví", "mamografický screening", "veřejné zdraví"],
        "trend_context": "Vývoj odráží osvětu o významu mamografického vyšetření a aktivní zvaní pojišťovnami od roku 2014. Český screening pokrývá ženy 45 a více let.",
        "data_url": "https://data.mzcr.cz/data/distribuce/263/Otevrena-data-PPS-01-01-mamografie-screening-pokryti-populace.csv",
        "source_url": "https://www.nzip.cz/data/2068-mamografie-screening-pokryti-populace-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_vysetrenych",
        "denominator_col": "populace",
    },
    "cervix_screening_pokryti": {
        "label": "Cervikální screening — pokrytí cílové populace",
        "human_name": "Pokrytí žen screeningem rakoviny hrdla děložního",
        "description": "Procento žen v cílové populaci (15+ let), které absolvovaly cytologické vyšetření hrdla děložního jako součást screeningu rakoviny děložního čípku.",
        "code": "screening C53",
        "source": "Informační systém screeningu karcinomu hrdla děložního (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Pokrytí cílové populace (%)",
        "relevant_for": ["prevence", "ženské zdraví", "gynekologický screening", "lidský papilomavirus"],
        "trend_context": "Vývoj odráží gynekologický screening zavedený v Česku v 60. letech a od roku 2008 i organizovaný program s aktivním zvaním pojišťovnami. Hlavní příčina dlouhodobého poklesu úmrtnosti na rakovinu hrdla děložního.",
        "data_url": "https://data.mzcr.cz/data/distribuce/2/Otevrena-data-PPS-03-01-cervix-screening-pokryti-populace.csv",
        "source_url": "https://www.nzip.cz/data/2070-cervix-screening-pokryti-populace-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_vysetrenych",
        "denominator_col": "populace",
    },
    "umrti_mkn10_celkem": {
        "label": "Úmrtí podle kapitol MKN-10 — celkem",
        "human_name": "Roční počet úmrtí v ČR",
        "description": "Roční počet všech úmrtí v Česku — souhrnný ukazatel sumy úmrtnosti podle kapitol Mezinárodní klasifikace nemocí. Patří k nejdéle sledovaným epidemiologickým údajům v ČR.",
        "code": "úmrtnost celkem",
        "source": "List o prohlídce zemřelého (ÚZIS)",
        "source_type": "national",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["veřejné zdraví", "stárnutí populace", "demografie"],
        "trend_context": "Vývoj odráží stárnutí populace, kvalitu zdravotní péče a epidemiologickou situaci (např. nárůst v letech 2020-2021 souvisí s pandemií). Patří k základním ukazatelům pro plánování zdravotní a sociální péče.",
        "data_url": "https://data.mzcr.cz/data/distribuce/445/Otevrena-data-NR-06-32-umrti-pocet-rok-vek-pohlavi-kapitola-mkn10.csv",
        "source_url": "https://www.nzip.cz/data/2355-umrti-pocet-rok-vek-pohlavi-kapitola-mkn-10-otevrena-data",
        "year_col": "rok_umrti",
        "metric_col": "pocet_zemrelych",
        "agg_func": "sum",
    },
    "atopicka_dermatitida": {
        "label": "Atopická dermatitida — dispenzarizovaní pacienti",
        "human_name": "Pacienti s atopickou dermatitidou",
        "description": "Roční počet dispenzarizovaných (dlouhodobě sledovaných) pacientů s atopickou dermatitidou (atopickým ekzémem). Patří k chronickým alergickým onemocněním kůže, často spojeným s dalšími alergiemi.",
        "code": "L20",
        "source": "Národní registr hrazených zdravotních služeb (ÚZIS)",
        "source_type": "national",
        "metric": "prevalence_rocni",
        "metric_label": "Roční počet sledovaných pacientů",
        "relevant_for": ["alergologie", "kůže", "dětské zdraví", "imunita"],
        "trend_context": "Roste jako součást širšího fenoménu alergických onemocnění v moderních populacích. Moderní léčba (biologika u těžkých forem) zásadně mění kvalitu života pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/459/Otevrena-data-NR-04-83-atopicka-dermatitida.csv",
        "source_url": "https://www.nzip.cz/data/2454-atopicka-dermatitida-otevrena-data",
        "year_col": "rok_pece",
        "metric_col": "pocet",
        "agg_func": "sum",
    },
    "cdz_pacienti": {
        "label": "Centra duševního zdraví — pacienti",
        "human_name": "Pacienti v centrech duševního zdraví",
        "description": "Roční počet pacientů ošetřovaných v centrech duševního zdraví. Klíčový ukazatel rozšíření komunitní psychiatrické péče v Česku.",
        "code": "psychiatrická péče",
        "source": "Národní informační systém péče o duševní zdraví (ÚZIS)",
        "source_type": "national",
        "metric": "pacienti_rocni",
        "metric_label": "Roční počet pacientů",
        "relevant_for": ["duševní zdraví", "komunitní psychiatrie", "veřejné zdraví"],
        "trend_context": "Centra duševního zdraví jsou klíčovým prvkem reformy psychiatrické péče v ČR. Cílem je posunout péči od velkých psychiatrických nemocnic k integrované komunitní péči v běžném prostředí pacienta.",
        "data_url": "https://datanzis.uzis.gov.cz/data/OIS-04-NISDZ/OIS-04-19/Otevrena-data-OIS-04-19-pacienti-centra-dusevniho-zdravi.csv",
        "source_url": "https://www.nzip.cz/data/2665-pacienti-centra-dusevniho-zdravi-otevrena-data",
        "year_col": "rok",
        "metric_col": "pocet_pacientu",
        "agg_func": "sum",
    },
    "umrti_doma_ocekavatelne": {
        "label": "Očekávatelná úmrtí — místo úmrtí",
        "human_name": "Místa očekávatelných úmrtí",
        "description": "Roční počet očekávatelných úmrtí podle okresů — sumární přehled celkového rozšíření paliativní péče v ČR.",
        "code": "paliativní péče",
        "source": "List o prohlídce zemřelého (ÚZIS)",
        "source_type": "national",
        "metric": "umrti_rocni",
        "metric_label": "Roční počet očekávatelných úmrtí",
        "relevant_for": ["paliativní péče", "hospice", "kvalita umírání"],
        "trend_context": "Vývoj odráží stárnutí populace a postupný rozvoj paliativní péče. Místo úmrtí (doma vs. nemocnice vs. hospic) je klíčový ukazatel kvality umírání — většina lidí preferuje umírat doma, realita je často jiná.",
        "data_url": "https://datanzis.uzis.gov.cz/data/NR-06-LPZ/NR-06-37/Otevrena-data-NR-06-37-pacienti-ocekavatelne-umrti-mista-okresy-casovy-trend.csv",
        "source_url": "https://www.nzip.cz/data/2691-pacienti-ocekavatelne-umrti-mista-okresy-casovy-trend-otevrena-data",
        "year_col": "rok",
        "metric_col": "ocekavatelne_zemreli_pocet",
        "agg_func": "sum",
    },
    "dialyza_nefrolog_pokryti": {
        "label": "Chronická dialýza — podíl s předchozím vyšetřením nefrologem",
        "human_name": "Pacienti vstupující na dialýzu — vyšetření nefrologem dopředu",
        "description": "Procento osob, které před nástupem na chronickou dialyzační léčbu absolvovaly preventivní vyšetření u nefrologa. Ideální stav je 100 % — pozdní záchyt znamená horší prognózu pacienta.",
        "code": "nefrologie",
        "source": "Centrální evidence dat populačních preventivních programů (ÚZIS)",
        "source_type": "national",
        "metric": "pokryti_pct",
        "metric_label": "Podíl s předchozím nefrologickým vyšetřením (%)",
        "relevant_for": ["prevence", "močový systém", "chronická onemocnění", "primární péče"],
        "trend_context": "Ideální stav je 100 % — pacienti, kteří přicházejí na dialýzu bez předchozí nefrologické péče, mají typicky horší výchozí stav a prognózu. Vývoj odráží kvalitu primární péče a osvětu lékařů o významu časného odesílání rizikových pacientů.",
        "data_url": "https://datanzis.uzis.gov.cz/data/PPS-08-PREVENCE/PPS-08-08/Otevrena-data-PPS-08-08-chronicka-dialyzacni-lecba-podil-osob-nefrolog.csv",
        "source_url": "https://www.nzip.cz/data/2735-chronicka-dialyzacni-lecba-podil-osob-nefrolog-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_nefro",
        "denominator_col": "pocet_dialyzovanych",
    },
    "toks_pozitivni_podil": {
        "label": "Test na skryté krvácení do stolice — podíl pozitivních",
        "human_name": "Podíl pozitivních testů na skryté krvácení do stolice",
        "description": "Procento osob s pozitivním výsledkem testu na skryté krvácení do stolice (TOKS) — primární screeningový nástroj pro rakovinu tlustého střeva. Pozitivní test vyžaduje navazující kolonoskopii.",
        "code": "screening C18–C20",
        "source": "Informační systém screeningu karcinomu tlustého střeva a konečníku (ÚZIS)",
        "source_type": "national",
        "metric": "pozitivni_pct",
        "metric_label": "Podíl pozitivních (%)",
        "relevant_for": ["screening tlustého střeva", "prevence", "kolonoskopie"],
        "trend_context": "Stabilita podílu pozitivních testů ukazuje na zdravou statistiku — kolísá kolem ~5 %. Vyšší podíl by mohl ukazovat na technické problémy s testem, nižší na nedostatečnou citlivost.",
        "data_url": "https://data.mzcr.cz/data/distribuce/394/Otevrena-data-PPS-02-02-kolorektum-toks-podil-pozitivnich.csv",
        "source_url": "https://www.nzip.cz/data/2090-kolorektum-toks-podil-pozitivnich-otevrena-data",
        "year_col": "rok",
        "agg_func": "ratio",
        "numerator_col": "pocet_pozitivnich",
        "denominator_col": "pocet_vysetrenych",
    },
    "astma_dispenzarizovani": {
        "label": "Bronchiální astma — dispenzarizovaní pacienti",
        "human_name": "Pacienti s bronchiálním astmatem",
        "description": "Roční počet pacientů dispenzarizovaných (dlouhodobě sledovaných) s bronchiálním astmatem. Patří k nejčastějším chronickým onemocněním dýchacího ústrojí.",
        "code": "J45",
        "source": "Národní registr hrazených zdravotních služeb (ÚZIS)",
        "source_type": "national",
        "metric": "prevalence_rocni",
        "metric_label": "Roční počet sledovaných pacientů",
        "relevant_for": [
            "chronická onemocnění",
            "alergologie",
            "kvalita ovzduší",
            "dětské zdraví",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, zhoršující se kvalitu ovzduší ve městech, vyšší prevalenci alergií u dětí a lepší záchyt díky moderní spirometrii. Moderní léčba (inhalační kortikosteroidy, biologická léčba) umožňuje většině pacientů žít plnohodnotný život.",
        "data_url": "https://data.mzcr.cz/data/distribuce/458/Otevrena-data-NR-04-84-asthma-bronchiale.csv",
        "source_url": "https://www.nzip.cz/data/2455-asthma-bronchiale-otevrena-data",
        "year_col": "rok_pece",
        "metric_col": "pocet",
        "agg_func": "sum",
    },
}


def download_csv(url: str) -> Path | None:
    """Stáhne CSV streamovaně do tempfile. Vrací cestu nebo None při chybě."""
    try:
        print(f"  Stahuji {url} ...")
        r = requests.get(
            url,
            timeout=120,
            stream=True,
            headers={"User-Agent": "Omnimedia-NZIP-Curated/1.0 (PR research)"},
        )
        r.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False)
        size = 0
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                tmp.write(chunk)
                size += len(chunk)
        tmp.close()
        print(f"  Staženo {size/1024:.1f} KB do {tmp.name}")
        return Path(tmp.name)
    except Exception as e:
        print(f"  CHYBA při stahování: {e}", file=sys.stderr)
        return None


def aggregate_by_year(
    csv_path: Path,
    year_col: str,
    metric_col: str,
    agg_func: str,
    numerator_col: str | None = None,
    denominator_col: str | None = None,
) -> list:
    """Agreguje hodnotu per year_col.

    agg_func:
    - "sum"   — součet hodnot v metric_col
    - "count" — počet řádků
    - "ratio" — sum(numerator_col) / sum(denominator_col) × 100 (pokrytí v %)
    """
    sums: dict[int, float] = {}
    numerator: dict[int, float] = {}
    denominator: dict[int, float] = {}

    # Auto-detekce kódování (ÚZIS používá UTF-8 nebo Windows-1250).
    # Zkusíme dekódovat celý soubor jako UTF-8; pokud selže, použijeme cp1250.
    encoding = "utf-8"
    try:
        with csv_path.open("rb") as f:
            f.read().decode("utf-8")
    except UnicodeDecodeError:
        encoding = "cp1250"

    with csv_path.open(encoding=encoding, newline="") as f:
        # Auto-detekce oddělovače.
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        yr_col = cols_lower.get(year_col.lower())

        if not yr_col:
            raise ValueError(f"CSV neobsahuje rok sloupec '{year_col}'")

        if agg_func == "ratio":
            num_col = cols_lower.get((numerator_col or "").lower())
            den_col = cols_lower.get((denominator_col or "").lower())
            if not num_col or not den_col:
                raise ValueError(
                    f"agg_func=ratio vyžaduje numerator_col a denominator_col. "
                    f"Nalezené sloupce: {reader.fieldnames}"
                )
        else:
            mc_col = cols_lower.get((metric_col or "").lower())
            if agg_func != "count" and not mc_col:
                raise ValueError(f"CSV neobsahuje metric_col '{metric_col}'")

        for row in reader:
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if not (1950 <= year <= 2030):
                continue

            if agg_func == "count":
                sums[year] = sums.get(year, 0) + 1
            elif agg_func == "ratio":
                try:
                    n = float(row[num_col])
                    d = float(row[den_col])
                except (ValueError, TypeError):
                    continue
                numerator[year] = numerator.get(year, 0) + n
                denominator[year] = denominator.get(year, 0) + d
            else:  # sum
                try:
                    value = float(row[mc_col])
                except (ValueError, TypeError):
                    continue
                sums[year] = sums.get(year, 0) + value

    if agg_func == "ratio":
        return [
            {
                "year": y,
                "value": round(100 * numerator[y] / denominator[y], 1) if denominator[y] else 0,
            }
            for y in sorted(numerator.keys())
            if denominator.get(y, 0) > 0
        ]

    return [{"year": y, "value": int(sums[y]) if sums[y].is_integer() else round(sums[y], 1)} for y in sorted(sums.keys())]


def compute_meta(series: list, cfg: dict | None = None) -> dict:
    """Trend, delta, peak — rolling 3-letý průměr pro stabilitu.

    Pro agg_func="ratio" (procenta) používá absolutní rozdíl v procentních
    bodech místo relativního procenta.
    """
    if not series or len(series) < 2:
        return {"trend": "unknown", "delta": 0, "peakYear": None}

    if len(series) >= 6:
        first_value = sum(p["value"] for p in series[:3]) / 3
        last_value = sum(p["value"] for p in series[-3:]) / 3
    else:
        first_value = series[0]["value"]
        last_value = series[-1]["value"]

    agg_func = cfg.get("agg_func", "sum") if cfg else "sum"
    if agg_func == "ratio":
        delta = round(last_value - first_value, 1)
        if delta > 5:
            trend = "up"
        elif delta < -5:
            trend = "down"
        else:
            trend = "plateau"
    else:
        if first_value == 0:
            delta = 0
        else:
            delta = round(((last_value - first_value) / first_value) * 100)
        if delta > 10:
            trend = "up"
        elif delta < -10:
            trend = "down"
        else:
            trend = "plateau"

    peak = max(series, key=lambda r: r["value"])
    return {"trend": trend, "delta": delta, "peakYear": peak["year"]}


def sync_one(ds_id: str, cfg: dict) -> str:
    print(f"\n[{ds_id}] {cfg['label']} ({cfg['code']})")

    csv_path = download_csv(cfg["data_url"])
    if csv_path is None:
        return "failed"

    try:
        series = aggregate_by_year(
            csv_path,
            cfg["year_col"],
            cfg.get("metric_col"),
            cfg.get("agg_func", "sum"),
            numerator_col=cfg.get("numerator_col"),
            denominator_col=cfg.get("denominator_col"),
        )
        if not series:
            print("  CHYBA: žádná data po agregaci", file=sys.stderr)
            return "failed"
    except Exception as e:
        print(f"  CHYBA při parsování: {e}", file=sys.stderr)
        return "failed"
    finally:
        try:
            csv_path.unlink()
        except OSError:
            pass

    meta = compute_meta(series, cfg)

    out = {
        "id": ds_id,
        "label": cfg["label"],
        "human_name": cfg["human_name"],
        "description": cfg["description"],
        "code": cfg["code"],
        "source": cfg["source"],
        "source_type": cfg["source_type"],
        "metric": cfg["metric"],
        "metric_label": cfg["metric_label"],
        "relevant_for": cfg["relevant_for"],
        "trend_context": cfg["trend_context"],
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "coverage": f"{series[0]['year']}–{series[-1]['year']}",
        "trend": meta["trend"],
        "delta": meta["delta"],
        "peakYear": meta["peakYear"],
        "data": series,
        "data_url": cfg["data_url"],
        "source_url": cfg["source_url"],
    }

    out_path = OUT_DIR / f"{ds_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(
        f"  OK: {len(series)} let dat, delta {meta['delta']:+}%, "
        f"uloženo do {out_path.relative_to(OUT_DIR.parent.parent)}"
    )
    return "ok"


def main():
    print(f"NZIP curated sync — start v {datetime.now().isoformat()}")

    results: dict[str, str] = {}
    for ds_id, cfg in DATASETS.items():
        results[ds_id] = sync_one(ds_id, cfg)

    ok = [k for k, v in results.items() if v == "ok"]
    failed = [k for k, v in results.items() if v == "failed"]

    print("\n=== NZIP curated sync — hotovo ===")
    print(f"  OK ({len(ok)}): {', '.join(ok) if ok else '—'}")
    print(f"  Selhalo ({len(failed)}): {', '.join(failed) if failed else '—'}")

    if not ok:
        sys.exit(1)
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
