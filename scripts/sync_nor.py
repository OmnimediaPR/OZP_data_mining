"""
sync_nor.py — synchronizace dat z Národního onkologického registru (NOR)

Stahuje "Otevřená data" Národního onkologického registru z data.mzcr.cz,
parsuje je a ukládá jako JSON soubory do data/nor/.

Na rozdíl od NKIS jsou NOR data **mikrodata** — jeden řádek CSV = jeden
případ rakoviny. Roční počet se počítá jako počet řádků dané diagnózy
(prefix podle MKN-10, např. "C50" pro rakovinu prsu) seskupený podle
roku diagnózy (rok_dg).

Spouští se přes GitHub Actions 1× měsíčně (viz .github/workflows/sync-nor.yml)
nebo ručně:    python scripts/sync_nor.py

Závislosti:    pip install requests
"""

import csv
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime
import requests

OUT_DIR = Path(__file__).parent.parent / "data" / "nor"

# Definice datasetů — každý odpovídá jednomu výstupnímu JSON v data/nor/.
# Jeden NOR CSV (např. NR-07-01 incidence) je sdílen mezi více onkologickými
# datasety — až jich bude víc, přidá se cache. Pro teď stahujeme per dataset.
DATASETS = {
    "prsa_incidence": {
        "label": "Rakovina prsu — incidence",
        "human_name": "Rakovina prsu",
        "description": "Zhoubný nádor prsní žlázy — nejčastější rakovina žen v Česku. Vzácně postihuje i muže (méně než 1 % případů).",
        "code": "C50",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "mamografický screening",
            "prevence rakoviny",
        ],
        "trend_context": "Nárůst odráží především stárnutí populace a lepší záchyt díky mamografickému screeningu zavedenému v Česku od roku 2002. Mortalita přitom dlouhodobě klesá — tedy víc žen rakovinu prsu má, ale méně z ní umírá.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
    },
    "plice_incidence": {
        "label": "Rakovina plic — incidence",
        "human_name": "Rakovina plic",
        "description": "Zhoubný nádor plicní tkáně — onkologický zabiják číslo jedna v Česku z hlediska úmrtnosti. Ve většině případů je spojen s kouřením.",
        "code": "C34",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kouření",
            "kvalita ovzduší",
            "prevence",
        ],
        "trend_context": "Dlouhodobý pokles u mužů odpovídá poklesu kouření. U žen incidence naopak roste, protože ženy začaly kouřit hromadně později. Po roce 2000 narůstá také podíl nekuřáků mezi pacienty.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
    },
    "prostata_incidence": {
        "label": "Rakovina prostaty — incidence",
        "human_name": "Rakovina prostaty",
        "description": "Zhoubný nádor předstojné žlázy — nejčastější rakovina mužů v Česku. Typicky se objevuje po šedesátém roce života.",
        "code": "C61",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "preventivní prohlídky",
            "stárnutí populace",
        ],
        "trend_context": "Strmý nárůst po roce 2000 odráží zavedení vyšetření krve na prostatický specifický antigen — díky němu se zachytí víc časných případů. Úmrtnost přitom roste mnohem pomaleji.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "rok_dg",
    },
    "kolorektum_incidence": {
        "label": "Rakovina tlustého střeva a konečníku — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku",
        "description": "Zhoubný nádor v tlustém střevě nebo konečníku — třetí nejčastější rakovina v Česku. Zahrnuje tračník, přechod mezi tračníkem a konečníkem a samotný konečník.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "životní styl",
            "prevence",
        ],
        "trend_context": "Česko mělo dlouhá léta nejvyšší úmrtnost na rakovinu tlustého střeva na světě. Pokles po roce 2000 souvisí s plošným screeningem (test na skryté krvácení do stolice a kolonoskopie) zavedeným v roce 2000 a rozšířeným v roce 2009.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
    },
    "melanom_incidence": {
        "label": "Zhoubný melanom kůže — incidence",
        "human_name": "Zhoubný melanom kůže",
        "description": "Nejnebezpečnější druh kožní rakoviny — vzniká z pigmentových buněk (melanocytů). Dá se úspěšně léčit, pokud se zachytí včas.",
        "code": "C43",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kůže",
            "ultrafialové záření",
            "prevence",
        ],
        "trend_context": "Strmý nárůst odráží především lepší záchyt — díky osvětě a preventivním prohlídkám u kožního lékaře — a změnu životního stylu (víc slunění, cestování do teplých zemí, solária). Úmrtnost roste mnohem pomaleji.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
    },
    "zaludek_incidence": {
        "label": "Rakovina žaludku — incidence",
        "human_name": "Rakovina žaludku",
        "description": "Zhoubný nádor žaludeční sliznice. Kdysi jedna z nejčastějších rakovin v Česku, dnes dlouhodobě ustupuje.",
        "code": "C16",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "životní styl",
            "prevence",
        ],
        "trend_context": "Dlouhodobý pokles odráží lepší kvalitu stravování (chlazení místo nasolování a uzení), čistou pitnou vodu a léčbu bakterie Helicobacter pylori, která stojí za velkou částí případů. V onkologii patří k tichým úspěchům posledních desetiletí.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "rok_dg",
    },
    "slinivka_incidence": {
        "label": "Rakovina slinivky břišní — incidence",
        "human_name": "Rakovina slinivky břišní",
        "description": "Zhoubný nádor slinivky břišní — jedna z onkologicky nejhůře léčitelných diagnóz. Pětileté přežití zůstává dlouhodobě pod deseti procenty.",
        "code": "C25",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "kouření",
            "obezita",
        ],
        "trend_context": "Počet nových případů se za posledních 45 let zhruba ztrojnásobil — odráží stárnutí populace, vyšší podíl obezity a kouření. Záchyt zůstává obtížný; nemoc se často projeví, až když je v pokročilém stadiu, protože slinivka leží hluboko v dutině břišní a první příznaky jsou nespecifické.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "rok_dg",
    },
    "mozek_incidence": {
        "label": "Zhoubný nádor mozku — incidence",
        "human_name": "Zhoubný nádor mozku",
        "description": "Zhoubný nádor mozkové tkáně. Zahrnuje především gliomy a další primární mozkové nádory dospělých i dětí.",
        "code": "C71",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "neurologie",
            "vzácná onemocnění",
            "kvalita života",
        ],
        "trend_context": "Počet zachycených případů se od konce sedmdesátých let zhruba ztrojnásobil. Velkou část nárůstu vysvětluje dostupnost magnetické rezonance — víc nádorů se popíše, ne víc jich skutečně vzniká. Roli hraje i stárnutí populace.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "rok_dg",
    },
    "leukemie_incidence": {
        "label": "Leukémie — incidence",
        "human_name": "Leukémie",
        "description": "Souhrn zhoubných onemocnění krvetvorné tkáně — zahrnuje lymfoblastickou, lymfocytární, myeloidní a další typy. U dětí jde o nejčastější rakovinu vůbec, u dospělých přibývá s věkem.",
        "code": "C91–C95",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "dětská onkologie",
            "transplantace kostní dřeně",
            "hematologie",
        ],
        "trend_context": "Roční počet nově zachycených leukémií se od konce sedmdesátých let zdvojnásobil — odráží stárnutí populace a lepší záchyt díky krevním testům. Dětské leukémie patří k onkologickým úspěchům — pětileté přežití dnes přesahuje 85 procent.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "rok_dg",
    },
    "lymfomy_incidence": {
        "label": "Lymfomy — incidence (souhrn)",
        "human_name": "Lymfomy (souhrn)",
        "description": "Souhrn zhoubných onemocnění mízní (lymfatické) tkáně. Zahrnuje Hodgkinův lymfom (mladší pacienti, výborně léčitelný) a všechny typy non-Hodgkinových lymfomů (B-buněčné, T-buněčné i NK-buněčné).",
        "code": "C81–C86",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "imunita",
            "mladší pacienti",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, lepší záchyt díky zobrazovacím metodám a změny v klasifikaci. Hodgkinův lymfom přitom patří k onkologicky nejlépe léčitelným nádorům — většinu pacientů se daří úplně vyléčit.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C81", "C82", "C83", "C84", "C85", "C86"],
        "year_col": "rok_dg",
    },
    "ledvina_incidence": {
        "label": "Rakovina ledviny — incidence",
        "human_name": "Rakovina ledviny",
        "description": "Zhoubný nádor ledviny — typicky se objevuje po šedesátém roce života. Často se najde náhodně při zobrazovacím vyšetření z jiného důvodu.",
        "code": "C64",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "močový systém",
            "kouření",
            "obezita",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, vyšší výskyt obezity a vysokého krevního tlaku, ale také lepší záchyt díky širší dostupnosti ultrazvuku a počítačové tomografie. Česko patří dlouhodobě k zemím s nejvyšším výskytem rakoviny ledviny na světě.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C64",
        "year_col": "rok_dg",
    },
    "mocovy_mechyr_incidence": {
        "label": "Rakovina močového měchýře — incidence",
        "human_name": "Rakovina močového měchýře",
        "description": "Zhoubný nádor sliznice močového měchýře. Mezi hlavní rizikové faktory patří kouření a dlouhodobý kontakt s některými chemikáliemi v průmyslu (například barviva).",
        "code": "C67",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "močový systém",
            "kouření",
            "pracovní rizika",
        ],
        "trend_context": "Vývoj odráží především dlouhodobé vzorce kouření a profesionální expozici chemikáliím v lakařských, gumárenských a textilních provozech. U mužů je výskyt několikanásobně vyšší než u žen.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C67",
        "year_col": "rok_dg",
    },
    "stitna_zlaza_incidence": {
        "label": "Rakovina štítné žlázy — incidence",
        "human_name": "Rakovina štítné žlázy",
        "description": "Zhoubný nádor štítné žlázy — výrazně častější u žen. Většina případů jsou pomalu rostoucí nádory s velmi dobrou prognózou.",
        "code": "C73",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "hormonální systém",
            "ženské zdraví",
            "ultrazvukový záchyt",
        ],
        "trend_context": "Strmý nárůst záchytu je z velké části vysvětlen širším používáním ultrazvuku — nacházíme drobné nádory, které by se za života člověka možná neprojevily. Část onkologů proto varuje před nadbytečnou léčbou v takových případech.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "rok_dg",
    },
    "jicen_incidence": {
        "label": "Rakovina jícnu — incidence",
        "human_name": "Rakovina jícnu",
        "description": "Zhoubný nádor jícnu — trubice spojující ústní dutinu se žaludkem. Mezi hlavní rizikové faktory patří dlouhodobé pálení žáhy, kouření a vyšší konzumace alkoholu.",
        "code": "C15",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "alkohol",
            "kouření",
        ],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření, konzumace alkoholu a nárůstu obezity (ta vede k chronickému pálení žáhy a dráždění sliznice jícnu). U mužů je výskyt několikanásobně vyšší než u žen.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C15",
        "year_col": "rok_dg",
    },
    "varlata_incidence": {
        "label": "Rakovina varlat — incidence",
        "human_name": "Rakovina varlat",
        "description": "Zhoubný nádor varlat — nejčastější rakovina mladších mužů (typicky 20 až 40 let). Při včasném záchytu patří k onkologicky nejlépe léčitelným nádorům.",
        "code": "C62",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "mladší pacienti",
            "samovyšetření",
        ],
        "trend_context": "Roli hraje lepší záchyt díky osvětě o samovyšetření a změny v hormonálním prostředí v dospívání (vyšší věk matek při porodu, životní styl). Kombinace operace, ozařování a chemoterapie patří k tichým úspěchům moderní onkologie — většinu pacientů se daří úplně vyléčit.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C62",
        "year_col": "rok_dg",
    },
    "vajecnik_incidence": {
        "label": "Rakovina vaječníku — incidence",
        "human_name": "Rakovina vaječníku",
        "description": "Zhoubný nádor vaječníku — jeden z onkologicky nejhůře léčitelných ženských nádorů. Záchyt v časném stadiu je obtížný, protože nemoc se dlouho neprojevuje výraznými příznaky.",
        "code": "C56",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "genetika",
            "rodinná anamnéza",
        ],
        "trend_context": "Část případů má dědičný základ — souvisí s mutacemi v genech, které zvyšují i riziko rakoviny prsu. Genetické testování příbuzných žen s prokázanou mutací umožňuje preventivní opatření a častější sledování.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C56",
        "year_col": "rok_dg",
    },
    "cipek_incidence": {
        "label": "Rakovina hrdla děložního — incidence",
        "human_name": "Rakovina hrdla děložního",
        "description": "Zhoubný nádor hrdla dělohy (čípku) — v převážné většině způsobený dlouhodobou infekcí lidským papilomavirem. Při pravidelných gynekologických prohlídkách se dá zachytit ještě ve stadiu přednádorových změn.",
        "code": "C53",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "očkování",
            "gynekologický screening",
        ],
        "trend_context": "Vývoj odráží především zavedení gynekologického screeningu (cytologické vyšetření čípku) a od roku 2012 také očkování proti lidskému papilomaviru, které riziko podstatně snižuje. Po zavedení očkování klesá výskyt zejména u mladších ročníků.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C53",
        "year_col": "rok_dg",
    },
    "deloha_incidence": {
        "label": "Rakovina těla děložního — incidence",
        "human_name": "Rakovina těla děložního",
        "description": "Zhoubný nádor sliznice dělohy. Typicky se objevuje u žen po menopauze. Mezi hlavní rizikové faktory patří obezita, vysoký krevní tlak a cukrovka druhého typu.",
        "code": "C54",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "obezita",
            "menopauza",
        ],
        "trend_context": "Vývoj odráží stárnutí populace a vyšší výskyt obezity a cukrovky druhého typu — všechny tyto faktory zvyšují riziko. Brzký záchyt díky výraznému příznaku (krvácení po menopauze) dává obvykle dobrou prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C54",
        "year_col": "rok_dg",
    },
    "kosti_incidence": {
        "label": "Zhoubné nádory kostí — incidence",
        "human_name": "Zhoubné nádory kostí",
        "description": "Vzácná skupina onkologických diagnóz, která zahrnuje především sarkomy kostí. Patří mezi onkologické nemoci typické pro dětský věk a dospívání — osteosarkom je například charakteristický pro období dospívání.",
        "code": "C40–C41",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "dětská onkologie",
            "sarkomy",
            "mladší pacienti",
        ],
        "trend_context": "Vývoj odráží jak změny v záchytu (zobrazovací metody, dostupnost magnetické rezonance), tak v klasifikaci nádorů. Léčba kombinující chirurgický zákrok, chemoterapii a ozařování dramaticky zlepšila prognózu zejména u dětských pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C40", "C41"],
        "year_col": "rok_dg",
    },
    "ustni_dutina_incidence": {
        "label": "Rakovina dutiny ústní a hltanu — incidence",
        "human_name": "Rakovina dutiny ústní a hltanu",
        "description": "Zhoubné nádory v oblasti rtu, jazyka, sliznice úst, dásní, patra, mandlí a hltanu. Mezi hlavní rizikové faktory patří kouření, vyšší konzumace alkoholu a infekce lidským papilomavirem.",
        "code": "C00–C14",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kouření",
            "alkohol",
            "očkování",
        ],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření a konzumace alkoholu — kombinace obou faktorů zvyšuje riziko mnohonásobně. U nádorů mandlí a kořene jazyka přitom v posledních dvou desetiletích roste podíl případů spojených s lidským papilomavirem, často u nekuřáků.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C00", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "C13", "C14"],
        "year_col": "rok_dg",
    },
    "vzacne_nadory_incidence": {
        "label": "Vzácné onkologické diagnózy — incidence",
        "human_name": "Vzácné onkologické diagnózy",
        "description": "Souhrn vzácných zhoubných nádorů, které individuálně postihují jen desítky až nižší stovky pacientů ročně. Patří sem sarkomy měkkých tkání, mezoteliom, nádory oka, nadledvin, dutiny nosní, brzlíku, mediastina a periferních nervů.",
        "code": "C30–C31, C37–C38, C45–C49, C69, C74–C75",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "vzácná onemocnění",
            "specializovaná péče",
            "dětská onkologie",
        ],
        "trend_context": "Souhrnný pohled na onkologické diagnózy, které jednotlivě mají v Česku jen několik desítek až nižší stovky případů ročně. Péče se proto soustřeďuje do specializovaných center, která dokáží udržet zkušenost s malým objemem pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C30", "C31", "C37", "C38", "C45", "C46", "C47", "C48", "C49", "C69", "C74", "C75"],
        "year_col": "rok_dg",
    },
    "stitna_zlaza_deti_incidence": {
        "label": "Rakovina štítné žlázy u dětí a dospívajících — incidence",
        "human_name": "Rakovina štítné žlázy u dětí a dospívajících",
        "description": "Zhoubný nádor štítné žlázy u dětí a dospívajících do 19 let. V mezinárodní onkologii (Mezinárodní agentura pro výzkum rakoviny) se pediatrická onkologie obvykle definuje jako 0–19 let. Většina případů má velmi dobrou prognózu.",
        "code": "C73",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (0–19 let)",
        "relevant_for": [
            "onkologie",
            "dětská onkologie",
            "hormonální systém",
            "vzácná onemocnění",
        ],
        "trend_context": "U dětí a dospívajících je rakovina štítné žlázy vzácná. Případná kolísání v ročních počtech proto odpovídají statistickému šumu vzácných onemocnění, ne skutečným změnám rizika. Léčba má v této věkové skupině vysokou úspěšnost.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66000004", "66005009", "66010014", "66015019"],
    },
    "stitna_zlaza_dospeli_incidence": {
        "label": "Rakovina štítné žlázy u dospělých — incidence",
        "human_name": "Rakovina štítné žlázy u dospělých",
        "description": "Zhoubný nádor štítné žlázy u dospělých od 20 let. Doplněk k pediatrickému datasetu (0–19 let) — umožňuje sledovat oba věkové segmenty samostatně.",
        "code": "C73",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (20+ let)",
        "relevant_for": [
            "onkologie",
            "hormonální systém",
            "ženské zdraví",
            "ultrazvukový záchyt",
        ],
        "trend_context": "Vývoj u dospělých je z velké části vysvětlen širším používáním ultrazvuku — nacházíme drobné nádory, které by se za života člověka možná neprojevily. Část onkologů proto varuje před nadbytečnou léčbou v takových případech.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66020024", "66025029", "66030034", "66035039", "66040044",
            "66045049", "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "myelom_incidence": {
        "label": "Mnohočetný myelom — incidence",
        "human_name": "Mnohočetný myelom",
        "description": "Zhoubné onemocnění plazmatických buněk v kostní dřeni. Typicky se objevuje u starších pacientů (medián diagnózy kolem 70 let). Patří k nejčastějším hematologickým nádorům u dospělých.",
        "code": "C90",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "stárnutí populace",
            "kostní dřeň",
        ],
        "trend_context": "Vývoj odráží stárnutí populace a lepší záchyt díky krevním testům. Léčba se v posledních desetiletích výrazně posunula — nová cílená léčba a transplantace kostní dřeně prodloužily průměrné přežití několikanásobně, byť trvalé vyléčení zůstává vzácné.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C90",
        "year_col": "rok_dg",
    },
    "hrtan_incidence": {
        "label": "Rakovina hrtanu — incidence",
        "human_name": "Rakovina hrtanu",
        "description": "Zhoubný nádor hrtanu — orgánu, kde sedí hlasivky. Drtivou většinu případů způsobuje kouření, riziko dál zvyšuje konzumace alkoholu.",
        "code": "C32",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kouření",
            "alkohol",
            "hlasivky",
        ],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření a konzumace alkoholu. Drtivou většinu pacientů tvoří muži — u žen je výskyt řádově nižší.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C32",
        "year_col": "rok_dg",
    },
    "kuze_nemelanomove_incidence": {
        "label": "Kožní rakoviny mimo melanom — incidence",
        "human_name": "Kožní rakoviny mimo melanom",
        "description": "Souhrn nejčastějších kožních zhoubných nádorů — bazaliomu (bazocelulárního karcinomu) a spinocelulárního karcinomu. Z pohledu počtu případů jde o nejčastější zhoubný nádor v Česku vůbec. Prognosticky jsou ale tyto nádory naprosto odlišné od melanomu — naprostá většina případů je dobře léčitelná drobným chirurgickým zákrokem.",
        "code": "C44",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "kůže",
            "ultrafialové záření",
            "stárnutí populace",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, kumulativní expozici ultrafialovému záření (slunění, solária, práce venku) a lepší záchyt díky preventivním kožním prohlídkám. Spolu s melanomem představují tyto nádory hlavní agendu kožních lékařů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C44",
        "year_col": "rok_dg",
    },
    "hodgkin_lymfom_incidence": {
        "label": "Hodgkinův lymfom — incidence",
        "human_name": "Hodgkinův lymfom",
        "description": "Zhoubné onemocnění mízní (lymfatické) tkáně se specifickými nádorovými buňkami. Postihuje typicky mladší dospělé (s druhým vrcholem v pokročilejším věku) a patří k onkologicky nejlépe léčitelným nádorům — většinu pacientů se daří úplně vyléčit.",
        "code": "C81",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "mladší pacienti",
            "imunita",
        ],
        "trend_context": "Vývoj odráží stárnutí populace a změny v klasifikaci nádorů. Hodgkinův lymfom je doslova příběhem moderní onkologie — kombinací chemoterapie a ozařování zvládáme úplně vyléčit drtivou většinu pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C81",
        "year_col": "rok_dg",
    },
    "lymfomy_b_bunecne_incidence": {
        "label": "B-buněčné non-Hodgkinovy lymfomy — incidence",
        "human_name": "B-buněčné non-Hodgkinovy lymfomy",
        "description": "Skupina non-Hodgkinových lymfomů, které vznikají z B-lymfocytů (jeden z hlavních typů bílých krvinek). Zahrnují folikulární lymfom, difúzní velkobuněčný lymfom a další podtypy. Tvoří drtivou většinu non-Hodgkinových lymfomů.",
        "code": "C82, C83, C85",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "imunita",
            "starší pacienti",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, lepší záchyt díky zobrazovacím metodám a změny v klasifikaci. Léčba kombinuje chemoterapii s cílenými léky (například monoklonálními protilátkami) — u řady podtypů se daří dosáhnout dlouhodobé remise.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C82", "C83", "C85"],
        "year_col": "rok_dg",
    },
    "kolorektum_mladi_incidence": {
        "label": "Rakovina tlustého střeva a konečníku u mladších dospělých — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku u mladších dospělých (do 49 let)",
        "description": "Zhoubný nádor tlustého střeva a konečníku u pacientů mladších 50 let. V posledních dvou desetiletích se rakovina tlustého střeva u mladších stává významným onkologickým tématem — počet mladších pacientů v mnoha vyspělých zemích roste, zatímco u starších díky screeningu klesá.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": [
            "onkologie",
            "early-onset",
            "mladší pacienti",
            "životní styl",
        ],
        "trend_context": "Tradičně postihovala rakovina tlustého střeva především starší. V Česku ale, podobně jako v dalších vyspělých zemích, narůstá počet mladších případů — předpokládá se kombinace životního stylu (vyšší obezita, méně pohybu, ultra-zpracované potraviny), složení střevního mikrobiomu a dalších dosud ne plně objasněných faktorů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "kolorektum_starsi_incidence": {
        "label": "Rakovina tlustého střeva a konečníku u starších dospělých — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku u starších dospělých (50+ let)",
        "description": "Zhoubný nádor tlustého střeva a konečníku u pacientů ve věku 50 a více let. Hlavní cílová skupina českého screeningu — testu na skryté krvácení do stolice a kolonoskopie.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "starší pacienti",
            "prevence",
        ],
        "trend_context": "Hlavní cílová skupina českého screeningu rakoviny tlustého střeva. Zavedení screeningu v roce 2000 a jeho rozšíření v roce 2009 přispělo k tomu, že se víc nádorů zachytí ve stadiu odstranitelných polypů ještě před přechodem v rakovinu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "prsa_mladi_incidence": {
        "label": "Rakovina prsu u mladších žen — incidence",
        "human_name": "Rakovina prsu u mladších žen (do 49 let)",
        "description": "Zhoubný nádor prsu u žen (a vzácně mužů) mladších 50 let. U mladších pacientek se častěji vyskytují agresivnější podtypy rakoviny prsu s horší prognózou. Mamografický screening je v Česku určen ženám od 45 let, mladší pacientky se obvykle dostávají k diagnóze přes samovyšetření nebo příznaky.",
        "code": "C50",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "early-onset",
            "samovyšetření",
        ],
        "trend_context": "Mladší ženy nezachytí standardní mamografický screening, ten začíná v 45 letech. U pacientek s rodinnou anamnézou rakoviny prsu nebo nositelek mutace v genech, které zvyšují riziko, se doporučuje zvýšené sledování od mladšího věku.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "prsa_starsi_incidence": {
        "label": "Rakovina prsu u starších žen — incidence",
        "human_name": "Rakovina prsu u starších žen (50+ let)",
        "description": "Zhoubný nádor prsu u žen (a vzácně mužů) ve věku 50 a více let. Hlavní cílová skupina českého mamografického screeningu (od 45 do 69 let, případně i déle).",
        "code": "C50",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "mamografický screening",
            "stárnutí populace",
        ],
        "trend_context": "Hlavní cílová skupina mamografického screeningu zavedeného v Česku od roku 2002. Vývoj odráží stárnutí populace a lepší záchyt — víc žen s rakovinou prsu, ale díky včasné diagnóze a moderní léčbě dlouhodobě klesající úmrtnost.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "plice_mladi_incidence": {
        "label": "Rakovina plic u mladších dospělých — incidence",
        "human_name": "Rakovina plic u mladších dospělých (do 49 let)",
        "description": "Zhoubný nádor plicní tkáně u pacientů mladších 50 let. U mladších pacientů je vyšší podíl nekuřáků a častější jsou jiné histologické typy než u starších dlouhodobých kuřáků — zejména adenokarcinom.",
        "code": "C34",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": [
            "onkologie",
            "kouření",
            "životní prostředí",
            "early-onset",
        ],
        "trend_context": "U mladších pacientů narůstá podíl případů u nekuřáků — souvisí s expozicí radonu (v Česku vysoké přírodní pozadí v některých regionech), pasivním kouřením a kvalitou ovzduší ve městech. Histologicky převažuje adenokarcinom.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "plice_starsi_incidence": {
        "label": "Rakovina plic u starších dospělých — incidence",
        "human_name": "Rakovina plic u starších dospělých (50+ let)",
        "description": "Zhoubný nádor plicní tkáně u pacientů ve věku 50 a více let. Drtivá většina případů odpovídá klasickému profilu dlouhodobých kuřáků a bývalých kuřáků.",
        "code": "C34",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": [
            "onkologie",
            "kouření",
            "stárnutí populace",
            "screening",
        ],
        "trend_context": "Dlouhodobý pokles u mužů odpovídá poklesu kouření v populaci. U žen incidence naopak roste — ženy začaly kouřit hromadně později a do diagnostické věkové skupiny teprve vstupují silnější ročníky kuřaček. Od roku 2022 byl v Česku zaveden plicní screening u dlouhodobých kuřáků.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "melanom_mladi_incidence": {
        "label": "Zhoubný melanom kůže u mladších dospělých — incidence",
        "human_name": "Zhoubný melanom kůže u mladších dospělých (do 49 let)",
        "description": "Zhoubný nádor pigmentových buněk kůže u pacientů mladších 50 let. Mezi nejmladší pacienty patří lidé, kteří v dětství a dospívání byli vystaveni intenzivnímu slunění nebo pravidelně používali solária.",
        "code": "C43",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": [
            "onkologie",
            "kůže",
            "ultrafialové záření",
            "solária",
        ],
        "trend_context": "U mladších pacientů odráží především expozici ultrafialovému záření v období dětství a dospívání — opakované sluneční úžehy v mládí násobí riziko v dospělosti. Užívání solárií je v této věkové skupině silným samostatným rizikem.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "varlata_mladi_incidence": {
        "label": "Rakovina varlat u mladších mužů — incidence",
        "human_name": "Rakovina varlat u mladších mužů (do 39 let)",
        "description": "Zhoubný nádor varlat u mužů mladších 40 let. Typický věk první diagnózy je mezi 20 a 40 lety — v této věkové skupině jde o jednu z nejčastějších onkologických diagnóz u mužů.",
        "code": "C62",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 39 let)",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "mladší pacienti",
            "samovyšetření",
        ],
        "trend_context": "Hlavní věková skupina pro rakovinu varlat — postihuje typicky muže ve dvaceti až čtyřiceti letech. Vývoj odráží lepší záchyt díky osvětě o samovyšetření a změny v hormonálním prostředí v dospívání. Léčba kombinací operace, chemoterapie a ozařování patří k tichým úspěchům moderní onkologie.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C62",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
        ],
    },
    "varlata_starsi_incidence": {
        "label": "Rakovina varlat u starších mužů — incidence",
        "human_name": "Rakovina varlat u starších mužů (40+ let)",
        "description": "Zhoubný nádor varlat u mužů 40 a více let. Po čtyřicítce výskyt klesá, ale i v této věkové skupině zůstává jedním z prognosticky nejlépe léčitelných nádorů. U starších pacientů se častěji vyskytují vzácnější histologické subtypy.",
        "code": "C62",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (40+ let)",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "starší pacienti",
        ],
        "trend_context": "Po čtyřicítce výskyt rakoviny varlat klesá — typický věk diagnózy leží v mladších dospělých letech. Vývoj odráží lepší záchyt a změny v klasifikaci.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C62",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66040044", "66045049", "66050054", "66055059",
            "66060064", "66065069", "66070074", "66075079",
            "66080084", "66085999",
        ],
    },
    "leukemie_deti_incidence": {
        "label": "Leukémie u dětí a dospívajících — incidence",
        "human_name": "Leukémie u dětí a dospívajících (0–19 let)",
        "description": "Souhrn leukémií u dětí a dospívajících do 19 let. U dětí je leukémie nejčastější rakovinou vůbec — dominuje akutní lymfoblastická leukémie. Pětileté přežití u dětských leukémií dnes přesahuje 85 procent, oproti zhruba 10 procentům v 70. letech.",
        "code": "C91–C95",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (0–19 let)",
        "relevant_for": [
            "onkologie",
            "dětská onkologie",
            "akutní lymfoblastická leukémie",
            "transplantace kostní dřeně",
        ],
        "trend_context": "U dětí dominuje akutní lymfoblastická leukémie. Vývoj odráží lepší záchyt a změny v klasifikaci. Léčba dětských leukémií patří k největším úspěchům moderní onkologie — díky kombinaci chemoterapie, ozařování a v některých případech transplantace kostní dřeně.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
        ],
    },
    "leukemie_dospeli_incidence": {
        "label": "Leukémie u dospělých — incidence",
        "human_name": "Leukémie u dospělých (20+ let)",
        "description": "Souhrn leukémií u dospělých od 20 let. U dospělých převažují jiné typy než u dětí — nejčastější je chronická lymfocytární leukémie a akutní myeloidní leukémie. Po šedesátce výskyt strmě roste.",
        "code": "C91–C95",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (20+ let)",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "stárnutí populace",
            "transplantace kostní dřeně",
        ],
        "trend_context": "U dospělých převažují chronická lymfocytární leukémie a akutní myeloidní leukémie. Vývoj odráží stárnutí populace a lepší záchyt díky krevním testům. Léčba se v posledních dvou desetiletích výrazně rozšířila o cílené léky.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66020024", "66025029", "66030034", "66035039", "66040044",
            "66045049", "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "kolorektum_velmi_mladi_incidence": {
        "label": "Rakovina tlustého střeva a konečníku u velmi mladých dospělých — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku u velmi mladých dospělých (do 39 let)",
        "description": "Zhoubný nádor tlustého střeva a konečníku u pacientů mladších 40 let. Tato věková skupina je předmětem velkého klinického zájmu — rakovina tlustého střeva u velmi mladých se v posledních dvou desetiletích stala významným tématem v zemích s vyspělou medicínou.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 39 let)",
        "relevant_for": [
            "onkologie",
            "early-onset",
            "mladší pacienti",
            "životní styl",
        ],
        "trend_context": "V Česku se počet velmi mladých případů rakoviny tlustého střeva sleduje obzvlášť pozorně — celosvětově patří k překvapivě rostoucím onkologickým nálezům. Mezi předpokládané faktory patří strava, obezita, méně pohybu a změny ve složení střevního mikrobiomu. Žádný z nich však zatím nárůst nedokáže plně vysvětlit.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
        ],
    },
    "kolorektum_stredni_incidence": {
        "label": "Rakovina tlustého střeva a konečníku ve středním věku — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku ve středním věku (40–49 let)",
        "description": "Zhoubný nádor tlustého střeva a konečníku u pacientů ve věku 40 až 49 let. Tato kohorta leží těsně pod hranicí klasické cílové skupiny screeningu (50+) — pacienti se obvykle dostávají k diagnóze přes příznaky, ne přes preventivní vyšetření.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (40–49 let)",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "early-onset",
            "životní styl",
        ],
        "trend_context": "Věková kohorta těsně pod hranicí klasického českého screeningu (50+). V řadě západních zemí byla v posledních letech věková hranice screeningu posunuta níže právě kvůli nárůstu výskytu v této věkové skupině.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66040044", "66045049",
        ],
    },
    "melanom_starsi_incidence": {
        "label": "Zhoubný melanom kůže u starších dospělých — incidence",
        "human_name": "Zhoubný melanom kůže u starších dospělých (50+ let)",
        "description": "Zhoubný nádor pigmentových buněk kůže u pacientů ve věku 50 a více let. U starších převažuje kumulativní expozice ultrafialovému záření za celý život.",
        "code": "C43",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": [
            "onkologie",
            "kůže",
            "ultrafialové záření",
            "stárnutí populace",
        ],
        "trend_context": "Vývoj odráží stárnutí populace a kumulativní expozici ultrafialovému záření za desetiletí — slunění, práce venku, dovolené v teplých zemích. Současně se uplatňuje lepší záchyt díky preventivním kožním prohlídkám.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "lymfomy_t_bunecne_incidence": {
        "label": "T-buněčné a NK-buněčné lymfomy — incidence",
        "human_name": "T-buněčné a NK-buněčné lymfomy",
        "description": "Vzácnější skupina non-Hodgkinových lymfomů, které vznikají z T-lymfocytů nebo NK-buněk (jiný typ bílých krvinek než B-lymfocyty). Zahrnuje periferní T-buněčné lymfomy a kožní T-buněčné lymfomy.",
        "code": "C84, C86",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "imunita",
            "vzácná onemocnění",
        ],
        "trend_context": "Patří mezi vzácnější hematologické nádory — počty se v Česku počítají v desítkách případů ročně. Léčba je oproti B-buněčným lymfomům obtížnější a obvykle vyžaduje specializovanou hematoonkologickou péči.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C84", "C86"],
        "year_col": "rok_dg",
    },
    # === NOR 1770 — Krajový snapshot incidence pro 2022 ===
    "prsa_kraje_2022": {
        "label": "Rakovina prsu — krajový pohled 2022",
        "human_name": "Rakovina prsu — krajový pohled",
        "description": "Počet nově diagnostikovaných případů rakoviny prsu v roce 2022 podle krajů. Umožňuje srovnat regionální rozdíly v záchytu, screeningu a struktuře populace.",
        "code": "C50",
        "metric": "incidence_2022",
        "metric_label": "Roční počet nově diagnostikovaných případů (2022)",
        "relevant_for": ["onkologie", "ženské zdraví", "regionální nerovnosti", "mamografický screening"],
        "trend_context": "Krajové rozdíly v absolutních počtech odrážejí především velikost populace kraje. Pro skutečné porovnání rizika by bylo potřeba přepočítat na 100 tisíc obyvatel — Praha a Středočeský kraj mají největší populaci, takže absolutní počty jsou nejvyšší.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "plice_kraje_2022": {
        "label": "Rakovina plic — krajový pohled 2022",
        "human_name": "Rakovina plic — krajový pohled",
        "description": "Počet nově diagnostikovaných případů rakoviny plic v roce 2022 podle krajů. Regionální rozdíly odrážejí jak velikost populace, tak historické vzorce kouření a kvalitu ovzduší.",
        "code": "C34",
        "metric": "incidence_2022",
        "metric_label": "Roční počet nově diagnostikovaných případů (2022)",
        "relevant_for": ["onkologie", "kouření", "regionální nerovnosti", "kvalita ovzduší"],
        "trend_context": "Krajové rozdíly odrážejí velikost populace, historické vzorce kouření, kvalitu ovzduší a profesionální expozici (hornictví, průmysl). Severozápadní Čechy a Moravskoslezský kraj patří k nejvíce zatíženým regionům kvůli historii těžby a průmyslu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "prostata_kraje_2022": {
        "label": "Rakovina prostaty — krajový pohled 2022",
        "human_name": "Rakovina prostaty — krajový pohled",
        "description": "Počet nově diagnostikovaných případů rakoviny prostaty v roce 2022 podle krajů. Umožňuje srovnat regionální dostupnost vyšetření krve na prostatický specifický antigen a strukturu populace.",
        "code": "C61",
        "metric": "incidence_2022",
        "metric_label": "Roční počet nově diagnostikovaných případů (2022)",
        "relevant_for": ["onkologie", "mužské zdraví", "regionální nerovnosti", "preventivní prohlídky"],
        "trend_context": "Krajové rozdíly v absolutních počtech odrážejí především velikost populace a věkovou strukturu kraje. Vyšší účast mužů na preventivních prohlídkách znamená víc zachycených nádorů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "rok_dg",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "kolorektum_kraje_2022": {
        "label": "Rakovina tlustého střeva a konečníku — krajový pohled 2022",
        "human_name": "Rakovina tlustého střeva a konečníku — krajový pohled",
        "description": "Počet nově diagnostikovaných případů rakoviny tlustého střeva a konečníku v roce 2022 podle krajů. Regionální rozdíly odrážejí velikost populace, životní styl a dostupnost screeningu.",
        "code": "C18–C20",
        "metric": "incidence_2022",
        "metric_label": "Roční počet nově diagnostikovaných případů (2022)",
        "relevant_for": ["onkologie", "screening tlustého střeva", "regionální nerovnosti", "životní styl"],
        "trend_context": "Krajové rozdíly v absolutních počtech odrážejí velikost populace a věkovou strukturu kraje. Dostupnost kolonoskopických center a účast na screeningu se mezi kraji liší.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "melanom_kraje_2022": {
        "label": "Zhoubný melanom kůže — krajový pohled 2022",
        "human_name": "Zhoubný melanom kůže — krajový pohled",
        "description": "Počet nově diagnostikovaných případů zhoubného melanomu kůže v roce 2022 podle krajů. Regionální rozdíly odrážejí jak velikost populace, tak dostupnost kožních lékařů a osvětu.",
        "code": "C43",
        "metric": "incidence_2022",
        "metric_label": "Roční počet nově diagnostikovaných případů (2022)",
        "relevant_for": ["onkologie", "kůže", "regionální nerovnosti", "preventivní prohlídky"],
        "trend_context": "Krajové rozdíly odrážejí velikost populace, dostupnost preventivních prohlídek u kožního lékaře a osvětu o nebezpečí ultrafialového záření.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    # === NOR 1771 — Mortalita (úmrtnost) ===
    # Jiný CSV než incidence (1770), kratší časová řada (od 1994).
    # year_col = umrti_rok, age_col = umrti_vek_kategorie_kod (POZOR — jiný sloupec než u incidence).
    "prsa_mortalita": {
        "label": "Rakovina prsu — úmrtnost",
        "human_name": "Úmrtnost na rakovinu prsu",
        "description": "Roční počet úmrtí na rakovinu prsu v Česku. Spolu s incidencí (záchytem) ukazuje, jak se daří rakovinu úspěšně léčit — pokud incidence roste, ale úmrtnost klesá, je to dobrá zpráva.",
        "code": "C50",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "mamografický screening",
            "kvalita léčby",
        ],
        "trend_context": "Vývoj odráží kombinaci stárnutí populace, vyššího záchytu díky mamografickému screeningu a zlepšení léčby. V Česku se daří dlouhodobě snižovat úmrtnost — víc žen rakovinu prsu má, ale méně z ní umírá.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "umrti_rok",
    },
    "plice_mortalita": {
        "label": "Rakovina plic — úmrtnost",
        "human_name": "Úmrtnost na rakovinu plic",
        "description": "Roční počet úmrtí na rakovinu plic v Česku. Onkologický zabiják číslo jedna z hlediska úmrtnosti — víc lidí umírá na rakovinu plic než na jakoukoli jinou rakovinu.",
        "code": "C34",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "kouření",
            "kvalita ovzduší",
            "screening",
        ],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření — pokles u mužů, růst u žen. Záchyt v pokročilém stadiu zůstává hlavním důvodem vysoké úmrtnosti. Od roku 2022 je v Česku k dispozici screening rakoviny plic pro dlouhodobé kuřáky.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "umrti_rok",
    },
    "prostata_mortalita": {
        "label": "Rakovina prostaty — úmrtnost",
        "human_name": "Úmrtnost na rakovinu prostaty",
        "description": "Roční počet úmrtí na rakovinu prostaty v Česku. Velký rozdíl mezi incidencí a úmrtností je u rakoviny prostaty typický — díky pomalému růstu nádoru a vyšetření krve na prostatický specifický antigen se daří většinu případů zachytit dříve, než ohrozí život.",
        "code": "C61",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "preventivní prohlídky",
            "kvalita léčby",
        ],
        "trend_context": "Úmrtnost roste pomaleji než incidence — odraz toho, že vyšetření krve na prostatický specifický antigen zachytí mnoho pomalu rostoucích nádorů, na které pacient ani nezemře. Modernizace léčby (operativa, ozařování, hormonální a cílená léčba) dál zlepšuje prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "umrti_rok",
    },
    "kolorektum_mortalita": {
        "label": "Rakovina tlustého střeva a konečníku — úmrtnost",
        "human_name": "Úmrtnost na rakovinu tlustého střeva a konečníku",
        "description": "Roční počet úmrtí na rakovinu tlustého střeva a konečníku v Česku. Historicky patřila česká populace k nejhůře postiženým na světě — díky plošnému screeningu se úmrtnost daří snižovat.",
        "code": "C18–C20",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "prevence",
            "kvalita léčby",
        ],
        "trend_context": "Vývoj odráží zavedení plošného screeningu (testu na skryté krvácení do stolice v roce 2000 a kolonoskopie v roce 2009) a zlepšení léčby. Česko se z nejhůře postižené země světa postupně dostává k evropskému průměru.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "umrti_rok",
    },
    "melanom_mortalita": {
        "label": "Zhoubný melanom kůže — úmrtnost",
        "human_name": "Úmrtnost na zhoubný melanom kůže",
        "description": "Roční počet úmrtí na zhoubný melanom kůže v Česku. Včas zachycený melanom je vysoce léčitelný — úmrtnost je proto výrazně nižší než incidence.",
        "code": "C43",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "kůže",
            "prevence",
            "kvalita léčby",
        ],
        "trend_context": "Vývoj odráží lepší záchyt v časném stadiu (osvěta, preventivní prohlídky u kožního lékaře) a posun v léčbě — cílená a imunoterapie zlepšily prognózu i u pokročilých melanomů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "umrti_rok",
    },
    "zaludek_mortalita": {
        "label": "Rakovina žaludku — úmrtnost",
        "human_name": "Úmrtnost na rakovinu žaludku",
        "description": "Roční počet úmrtí na rakovinu žaludku v Česku. Spolu s klesající incidencí patří dlouhodobý pokles úmrtnosti k tichým úspěchům onkologie.",
        "code": "C16",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "životní styl",
            "kvalita léčby",
        ],
        "trend_context": "Pokles odráží jak ústupek incidence (lepší strava, čistá voda, léčba Helicobacter pylori), tak modernizaci chirurgie a chemoterapie. Záchyt zůstává obtížný — nemoc se často projeví, až když je pokročilá.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "umrti_rok",
    },
    "slinivka_mortalita": {
        "label": "Rakovina slinivky břišní — úmrtnost",
        "human_name": "Úmrtnost na rakovinu slinivky břišní",
        "description": "Roční počet úmrtí na rakovinu slinivky břišní v Česku. Patří k nejhůře léčitelným onkologickým diagnózám — úmrtnost je téměř totožná s incidencí, protože pětileté přežití zůstává dlouhodobě pod deseti procenty.",
        "code": "C25",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "kvalita léčby",
            "výzkum",
        ],
        "trend_context": "Vývoj kopíruje růst incidence — léčba se sice mírně zlepšuje, ale prognóza zůstává jednou z nejhorších v onkologii. Velký prostor pro budoucí výzkum časné diagnostiky a cílené léčby.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "umrti_rok",
    },
    "jicen_mortalita": {
        "label": "Rakovina jícnu — úmrtnost",
        "human_name": "Úmrtnost na rakovinu jícnu",
        "description": "Roční počet úmrtí na rakovinu jícnu v Česku. Patří k onkologicky obtížně léčitelným diagnózám — pětileté přežití zůstává nízké.",
        "code": "C15",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "alkohol",
            "kouření",
        ],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření, konzumace alkoholu a obezity. Záchyt je obtížný, protože první příznaky (potíže s polykáním) se objevují, až když je nádor pokročilý.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C15",
        "year_col": "umrti_rok",
    },
    "cipek_mortalita": {
        "label": "Rakovina hrdla děložního — úmrtnost",
        "human_name": "Úmrtnost na rakovinu hrdla děložního",
        "description": "Roční počet úmrtí na rakovinu hrdla děložního v Česku. Díky gynekologickému screeningu a od roku 2012 také očkování proti lidskému papilomaviru se úmrtnost dlouhodobě daří snižovat.",
        "code": "C53",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "očkování",
            "gynekologický screening",
        ],
        "trend_context": "Pokles odráží zavedení gynekologického screeningu (cytologického vyšetření) a očkování proti lidskému papilomaviru, který způsobuje drtivou většinu těchto nádorů. Patří k jedné z mála rakovin, které se daří významně snižovat plošnou prevencí.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C53",
        "year_col": "umrti_rok",
    },
    "leukemie_mortalita": {
        "label": "Leukémie — úmrtnost",
        "human_name": "Úmrtnost na leukémie",
        "description": "Roční počet úmrtí na leukémie v Česku. Úmrtnost u dospělých výrazně závisí na typu leukémie a věku pacienta — u dětí naopak léčba dosahuje vysoké úspěšnosti.",
        "code": "C91–C95",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "kvalita léčby",
            "stárnutí populace",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, lepší klasifikaci a zásadní pokrok v léčbě (cílené léky, transplantace kostní dřeně). U dětských leukémií patří úmrtnost k onkologickým úspěchům — drtivá většina dětí se daří úplně vyléčit.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "umrti_rok",
    },
    "lymfomy_mortalita": {
        "label": "Lymfomy — úmrtnost (souhrn)",
        "human_name": "Úmrtnost na lymfomy (souhrn)",
        "description": "Roční počet úmrtí na všechny typy lymfomů v Česku (Hodgkinův i non-Hodgkinovy). Souhrnný pohled — úmrtnost se v posledních dvou desetiletích dařilo snižovat zejména u Hodgkinova lymfomu a B-buněčných non-Hodgkinových.",
        "code": "C81–C86",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "kvalita léčby",
            "cílená léčba",
        ],
        "trend_context": "Vývoj odráží stárnutí populace, ale především dramatický pokrok v léčbě — od cílených léků (například monoklonálních protilátek) po kombinované režimy. U Hodgkinova lymfomu patří úspěch léčby k nejvyšším v onkologii.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C81", "C82", "C83", "C84", "C85", "C86"],
        "year_col": "umrti_rok",
    },
    "ledvina_mortalita": {
        "label": "Rakovina ledviny — úmrtnost",
        "human_name": "Úmrtnost na rakovinu ledviny",
        "description": "Roční počet úmrtí na rakovinu ledviny v Česku. Česko patří k zemím s nejvyšším výskytem na světě — odraz vyšší obezity, kouření a možná i genetických faktorů v populaci.",
        "code": "C64",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "močový systém", "obezita", "kouření"],
        "trend_context": "Vývoj odráží stárnutí populace, vyšší výskyt obezity a vysokého krevního tlaku. Modernizace léčby (cílená terapie, imunoterapie) zlepšuje prognózu i u pokročilých případů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C64",
        "year_col": "umrti_rok",
    },
    "mocovy_mechyr_mortalita": {
        "label": "Rakovina močového měchýře — úmrtnost",
        "human_name": "Úmrtnost na rakovinu močového měchýře",
        "description": "Roční počet úmrtí na rakovinu močového měchýře v Česku. Onemocnění s historicky vysokým podílem mužů z důvodu profesionální expozice barvivům.",
        "code": "C67",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "močový systém", "kouření", "pracovní rizika"],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření a pracovních expozic v lakařských a chemických provozech. Časný záchyt přes hematurii (krev v moči) je klíčový pro prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C67",
        "year_col": "umrti_rok",
    },
    "stitna_zlaza_mortalita": {
        "label": "Rakovina štítné žlázy — úmrtnost",
        "human_name": "Úmrtnost na rakovinu štítné žlázy",
        "description": "Roční počet úmrtí na rakovinu štítné žlázy v Česku. Velký rozdíl mezi incidencí a úmrtností — drtivá většina pacientů má díky pomalému růstu nádoru velmi dobrou prognózu.",
        "code": "C73",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "hormonální systém", "kvalita léčby"],
        "trend_context": "Vývoj zůstává nízký a relativně stabilní navzdory rostoucí incidenci. Velké procento zachycených nádorů jsou pomalé papilární karcinomy s vynikající prognózou.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "umrti_rok",
    },
    "hrtan_mortalita": {
        "label": "Rakovina hrtanu — úmrtnost",
        "human_name": "Úmrtnost na rakovinu hrtanu",
        "description": "Roční počet úmrtí na rakovinu hrtanu v Česku. Onemocnění silně vázané na kouření a alkohol — pokles odráží dlouhodobý pokles kouření.",
        "code": "C32",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "kouření", "alkohol", "kvalita léčby"],
        "trend_context": "Vývoj kopíruje pokles kouření v ČR. Modernizace chirurgie (záchovné výkony, robotická chirurgie) navíc zlepšuje kvalitu života přeživších.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C32",
        "year_col": "umrti_rok",
    },
    "varlata_mortalita": {
        "label": "Rakovina varlat — úmrtnost",
        "human_name": "Úmrtnost na rakovinu varlat",
        "description": "Roční počet úmrtí na rakovinu varlat v Česku. Patří k onkologicky nejúspěšnějším diagnózám — drtivou většinu pacientů se daří úplně vyléčit.",
        "code": "C62",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "mužské zdraví", "kvalita léčby"],
        "trend_context": "Úmrtnost klesá díky kombinaci operativy, ozařování a moderní chemoterapie. Důležitá je včasná diagnóza, kterou pomáhá osvěta o samovyšetření.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C62",
        "year_col": "umrti_rok",
    },
    "vajecnik_mortalita": {
        "label": "Rakovina vaječníku — úmrtnost",
        "human_name": "Úmrtnost na rakovinu vaječníku",
        "description": "Roční počet úmrtí na rakovinu vaječníku v Česku. Patří k nejhůře prognosticky ženským nádorům — záchyt je obtížný, protože nemoc se dlouho neprojevuje příznaky.",
        "code": "C56",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "ženské zdraví", "genetika", "kvalita léčby"],
        "trend_context": "Vývoj odráží stárnutí populace a posun v léčbě (cílená léčba u nositelek mutace v genu BRCA). Časný záchyt zůstává obtížný — nemoc se obvykle projeví, až když je rozšířená.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C56",
        "year_col": "umrti_rok",
    },
    "deloha_mortalita": {
        "label": "Rakovina těla děložního — úmrtnost",
        "human_name": "Úmrtnost na rakovinu těla děložního",
        "description": "Roční počet úmrtí na rakovinu těla děložního v Česku. Brzký záchyt přes výrazný příznak (krvácení po menopauze) dává obvykle dobrou prognózu.",
        "code": "C54",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "ženské zdraví", "obezita", "kvalita léčby"],
        "trend_context": "Vývoj odráží stárnutí populace a vyšší výskyt obezity a cukrovky druhého typu (oba faktory zvyšují riziko). Včasný záchyt přes krvácení po menopauze umožňuje úspěšnou léčbu chirurgicky.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C54",
        "year_col": "umrti_rok",
    },
    "kosti_mortalita": {
        "label": "Zhoubné nádory kostí — úmrtnost",
        "human_name": "Úmrtnost na zhoubné nádory kostí",
        "description": "Roční počet úmrtí na zhoubné nádory kostí v Česku. Zahrnuje sarkomy kostí — vzácnou skupinu onkologických diagnóz typických pro dětský věk a dospívání.",
        "code": "C40–C41",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "dětská onkologie", "sarkomy", "kvalita léčby"],
        "trend_context": "Vývoj odráží zlepšení léčby kostních sarkomů — kombinace chirurgie, chemoterapie a ozařování dramaticky zlepšila prognózu zejména u dětských pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C40", "C41"],
        "year_col": "umrti_rok",
    },
    "ustni_dutina_mortalita": {
        "label": "Rakovina dutiny ústní a hltanu — úmrtnost",
        "human_name": "Úmrtnost na rakovinu dutiny ústní a hltanu",
        "description": "Roční počet úmrtí na rakovinu dutiny ústní a hltanu v Česku. Onemocnění silně vázané na kouření a alkohol, v posledních dvou desetiletích roste i podíl případů spojených s lidským papilomavirem.",
        "code": "C00–C14",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "kouření", "alkohol", "očkování"],
        "trend_context": "Vývoj odráží dlouhodobé vzorce kouření a konzumace alkoholu. U případů spojených s lidským papilomavirem je prognóza lepší, ale celková úmrtnost zůstává významná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C00", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "C13", "C14"],
        "year_col": "umrti_rok",
    },
    "myelom_mortalita": {
        "label": "Mnohočetný myelom — úmrtnost",
        "human_name": "Úmrtnost na mnohočetný myelom",
        "description": "Roční počet úmrtí na mnohočetný myelom v Česku. Hematologické onkologické onemocnění, kde moderní léčba (cílené léky, transplantace kostní dřeně) zásadně prodloužila přežití.",
        "code": "C90",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "hematologie", "stárnutí populace", "kvalita léčby"],
        "trend_context": "Vývoj odráží stárnutí populace, ale také zásadní pokrok v léčbě — nové cílené léky a transplantace kostní dřeně prodloužily průměrné přežití několikanásobně, byť trvalé vyléčení zůstává vzácné.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C90",
        "year_col": "umrti_rok",
    },
    "kuze_nemelanomove_mortalita": {
        "label": "Kožní rakoviny mimo melanom — úmrtnost",
        "human_name": "Úmrtnost na kožní rakoviny mimo melanom",
        "description": "Roční počet úmrtí na nemelanomové kožní rakoviny (bazaliom, spinocelulární karcinom) v Česku. I když je incidence extrémně vysoká, úmrtnost zůstává nízká — naprostá většina případů je dobře léčitelná chirurgicky.",
        "code": "C44",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "kůže", "stárnutí populace", "kvalita léčby"],
        "trend_context": "Vývoj odráží stárnutí populace a vyšší kumulativní expozici ultrafialovému záření. Úmrtnost zůstává nízká, protože většina nádorů se dá vyléčit drobným chirurgickým zákrokem.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C44",
        "year_col": "umrti_rok",
    },
    "hodgkin_lymfom_mortalita": {
        "label": "Hodgkinův lymfom — úmrtnost",
        "human_name": "Úmrtnost na Hodgkinův lymfom",
        "description": "Roční počet úmrtí na Hodgkinův lymfom v Česku. Patří k onkologicky nejúspěšnějším diagnózám — drtivou většinu pacientů se daří úplně vyléčit.",
        "code": "C81",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "hematologie", "kvalita léčby"],
        "trend_context": "Hodgkinův lymfom byl jednou z prvních rakovin, u kterých medicína dosáhla vysoké léčebné úspěšnosti. Úmrtnost klesá a u většiny pacientů jde dnes o plně vyléčitelné onemocnění.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C81",
        "year_col": "umrti_rok",
    },
    "lymfomy_b_bunecne_mortalita": {
        "label": "B-buněčné non-Hodgkinovy lymfomy — úmrtnost",
        "human_name": "Úmrtnost na B-buněčné non-Hodgkinovy lymfomy",
        "description": "Roční počet úmrtí na B-buněčné non-Hodgkinovy lymfomy v Česku. Drtivá většina non-Hodgkinových lymfomů spadá do této skupiny.",
        "code": "C82, C83, C85",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "hematologie", "kvalita léčby", "cílená léčba"],
        "trend_context": "Vývoj odráží pokrok v cílené léčbě (monoklonální protilátky, BTK inhibitory) a kombinovaných režimech. U řady podtypů se daří dosáhnout dlouhodobé remise.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C82", "C83", "C85"],
        "year_col": "umrti_rok",
    },
    "lymfomy_t_bunecne_mortalita": {
        "label": "T-buněčné a NK-buněčné lymfomy — úmrtnost",
        "human_name": "Úmrtnost na T-buněčné a NK-buněčné lymfomy",
        "description": "Roční počet úmrtí na T-buněčné a NK-buněčné lymfomy v Česku. Vzácnější skupina non-Hodgkinových lymfomů s obtížnější léčbou než u B-buněčných.",
        "code": "C84, C86",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "hematologie", "vzácná onemocnění", "kvalita léčby"],
        "trend_context": "Léčba T-buněčných lymfomů je oproti B-buněčným obtížnější a obvykle vyžaduje specializovanou hematoonkologickou péči. Modernizace léčebných postupů postupně zlepšuje prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C84", "C86"],
        "year_col": "umrti_rok",
    },
    # === NOR 1771 — Mortalita splity (pohlaví + věk) ===
    "plice_muzi_mortalita": {
        "label": "Rakovina plic u mužů — úmrtnost",
        "human_name": "Úmrtnost na rakovinu plic u mužů",
        "description": "Roční počet úmrtí na rakovinu plic u mužů. Mužská populace má dlouhodobě vyšší úmrtnost kvůli historicky vyšší míře kouření, ale úmrtnost dlouhodobě klesá s poklesem kouření.",
        "code": "C34",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "kouření", "mužské zdraví", "mortalita"],
        "trend_context": "Mužská úmrtnost na rakovinu plic v Česku dlouhodobě klesá — odraz poklesu kouření, který začal v 80. letech. Jeden z nejvýraznějších úspěchů veřejného zdraví u mužů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "plice_zeny_mortalita": {
        "label": "Rakovina plic u žen — úmrtnost",
        "human_name": "Úmrtnost na rakovinu plic u žen",
        "description": "Roční počet úmrtí na rakovinu plic u žen. U žen úmrtnost dlouhodobě roste — odraz zpožděné expanze kouření v ženské populaci a vstupu silnějších ročníků kuřaček do diagnostické věkové skupiny.",
        "code": "C34",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "kouření", "ženské zdraví", "mortalita"],
        "trend_context": "Ženská úmrtnost na rakovinu plic v Česku stále roste — opačný směr než u mužů. Důsledek toho, že ženy začaly kouřit hromadně později (až ve druhé polovině 20. století) a důsledky se v úmrtnosti projevují s typickým zpožděním 30-40 let.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "kolorektum_muzi_mortalita": {
        "label": "Rakovina tlustého střeva a konečníku u mužů — úmrtnost",
        "human_name": "Úmrtnost na rakovinu tlustého střeva a konečníku u mužů",
        "description": "Roční počet úmrtí na rakovinu tlustého střeva a konečníku u mužů. Česká mužská populace patří dlouhodobě k nejhůře postiženým v Evropě.",
        "code": "C18–C20",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "mužské zdraví", "screening tlustého střeva", "mortalita"],
        "trend_context": "Vývoj odráží zavedení plošného screeningu (od 2000) a zlepšení léčby. Účast mužů na screeningu je v Česku nižší než u žen — to brzdí pokles.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "kolorektum_zeny_mortalita": {
        "label": "Rakovina tlustého střeva a konečníku u žen — úmrtnost",
        "human_name": "Úmrtnost na rakovinu tlustého střeva a konečníku u žen",
        "description": "Roční počet úmrtí na rakovinu tlustého střeva a konečníku u žen. Ženy účastní screeningu více než muži, což přispívá ke snižování úmrtnosti.",
        "code": "C18–C20",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "ženské zdraví", "screening tlustého střeva", "mortalita"],
        "trend_context": "Vývoj odráží zavedení plošného screeningu a vyšší účast žen na preventivních vyšetřeních. Mortalita u žen v Česku klesá rychleji než u mužů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "prsa_mladi_mortalita": {
        "label": "Rakovina prsu u mladších žen — úmrtnost",
        "human_name": "Úmrtnost na rakovinu prsu u mladších žen (do 49 let)",
        "description": "Roční počet úmrtí na rakovinu prsu u žen mladších 50 let. U mladších žen jsou nádory často agresivnější, navíc nezachytí standardní mamografický screening.",
        "code": "C50",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy do 49 let)",
        "relevant_for": ["onkologie", "ženské zdraví", "early-onset", "mortalita"],
        "trend_context": "U mladších žen je úmrtnost dlouhodobě méně příznivá než u starších — agresivnější histologické subtypy a častý pozdější záchyt mimo screening.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "umrti_rok",
        "age_col": "umrti_vek_kategorie_kod",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "prsa_starsi_mortalita": {
        "label": "Rakovina prsu u starších žen — úmrtnost",
        "human_name": "Úmrtnost na rakovinu prsu u starších žen (50+ let)",
        "description": "Roční počet úmrtí na rakovinu prsu u žen 50 a více let. Hlavní cílová skupina mamografického screeningu.",
        "code": "C50",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy 50+ let)",
        "relevant_for": ["onkologie", "ženské zdraví", "mamografický screening", "mortalita"],
        "trend_context": "Hlavní cílová skupina mamografického screeningu. Vývoj odráží stárnutí populace (nominálně více pacientek), ale i pokrok v léčbě, který kompenzuje nárůst.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "umrti_rok",
        "age_col": "umrti_vek_kategorie_kod",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "kolorektum_mladi_mortalita": {
        "label": "Rakovina tlustého střeva a konečníku u mladších dospělých — úmrtnost",
        "human_name": "Úmrtnost na rakovinu tlustého střeva a konečníku u mladších dospělých (do 49 let)",
        "description": "Roční počet úmrtí na rakovinu tlustého střeva a konečníku u pacientů mladších 50 let. U mladších pacientů je pozdější diagnóza obvyklá — screening začíná až v 50 letech.",
        "code": "C18–C20",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (do 49 let)",
        "relevant_for": ["onkologie", "early-onset", "screening tlustého střeva", "mortalita"],
        "trend_context": "Mladší pacienti často přicházejí k diagnóze v pozdějším stadiu, protože screening na ně neaplikuje a jejich potíže bývají mylně přičítány banálním příčinám (hemoroidy, dráždivé střevo).",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "umrti_rok",
        "age_col": "umrti_vek_kategorie_kod",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "kolorektum_starsi_mortalita": {
        "label": "Rakovina tlustého střeva a konečníku u starších dospělých — úmrtnost",
        "human_name": "Úmrtnost na rakovinu tlustého střeva a konečníku u starších dospělých (50+ let)",
        "description": "Roční počet úmrtí na rakovinu tlustého střeva a konečníku u pacientů 50 a více let. Hlavní cílová skupina českého screeningu.",
        "code": "C18–C20",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (50+ let)",
        "relevant_for": ["onkologie", "screening tlustého střeva", "starší pacienti", "mortalita"],
        "trend_context": "Cílová skupina českého screeningu rakoviny tlustého střeva. Vývoj odráží zavedení plošného screeningu (2000, 2009) a moderní léčbu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "umrti_rok",
        "age_col": "umrti_vek_kategorie_kod",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "zaludek_muzi_mortalita": {
        "label": "Rakovina žaludku u mužů — úmrtnost",
        "human_name": "Úmrtnost na rakovinu žaludku u mužů",
        "description": "Roční počet úmrtí na rakovinu žaludku u mužů. U mužů je výskyt přibližně dvojnásobný oproti ženám, ale obě skupiny dlouhodobě klesají.",
        "code": "C16",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "trávicí systém", "mužské zdraví", "mortalita"],
        "trend_context": "Mužská úmrtnost na rakovinu žaludku v Česku dlouhodobě klesá díky lepší kvalitě stravy a léčbě bakterie Helicobacter pylori.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "zaludek_zeny_mortalita": {
        "label": "Rakovina žaludku u žen — úmrtnost",
        "human_name": "Úmrtnost na rakovinu žaludku u žen",
        "description": "Roční počet úmrtí na rakovinu žaludku u žen. Ženská úmrtnost je nižší než mužská a dlouhodobě klesá.",
        "code": "C16",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "trávicí systém", "ženské zdraví", "mortalita"],
        "trend_context": "Ženská úmrtnost na rakovinu žaludku klesá ze stejných důvodů jako mužská — lepší strava, čistá voda, léčba Helicobacter pylori.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "plice_mladi_mortalita": {
        "label": "Rakovina plic u mladších dospělých — úmrtnost",
        "human_name": "Úmrtnost na rakovinu plic u mladších dospělých (do 49 let)",
        "description": "Roční počet úmrtí na rakovinu plic u pacientů mladších 50 let. U mladších pacientů je vyšší podíl nekuřáků a často odlišný profil rizikových faktorů.",
        "code": "C34",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (do 49 let)",
        "relevant_for": ["onkologie", "kouření", "early-onset", "mortalita"],
        "trend_context": "U mladších pacientů úmrtnost klesá s poklesem kouření v jejich generaci. Roli hraje i kvalita ovzduší a expozice radonu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "umrti_rok",
        "age_col": "umrti_vek_kategorie_kod",
        "age_codes": ["66000004","66005009","66010014","66015019","66020024","66025029","66030034","66035039","66040044","66045049"],
    },
    "plice_starsi_mortalita": {
        "label": "Rakovina plic u starších dospělých — úmrtnost",
        "human_name": "Úmrtnost na rakovinu plic u starších dospělých (50+ let)",
        "description": "Roční počet úmrtí na rakovinu plic u pacientů 50 a více let. Drtivá většina úmrtí spadá do této věkové skupiny.",
        "code": "C34",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (50+ let)",
        "relevant_for": ["onkologie", "kouření", "stárnutí populace", "mortalita"],
        "trend_context": "U starších pacientů úmrtnost na rakovinu plic odráží kumulativní efekt kouření — různý u mužů (klesá) a žen (roste).",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "umrti_rok",
        "age_col": "umrti_vek_kategorie_kod",
        "age_codes": ["66050054","66055059","66060064","66065069","66070074","66075079","66080084","66085999"],
    },
    "melanom_muzi_mortalita": {
        "label": "Zhoubný melanom kůže u mužů — úmrtnost",
        "human_name": "Úmrtnost na zhoubný melanom kůže u mužů",
        "description": "Roční počet úmrtí na zhoubný melanom kůže u mužů. Muži chodí na preventivní kožní prohlídky méně často než ženy, což přispívá k pozdějšímu záchytu.",
        "code": "C43",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "kůže", "mužské zdraví", "mortalita"],
        "trend_context": "Mužská úmrtnost na melanom roste s rostoucí incidencí, ale modernizace léčby (imunoterapie, cílené léky) zpomaluje růst.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "melanom_zeny_mortalita": {
        "label": "Zhoubný melanom kůže u žen — úmrtnost",
        "human_name": "Úmrtnost na zhoubný melanom kůže u žen",
        "description": "Roční počet úmrtí na zhoubný melanom kůže u žen. Ženy chodí na preventivní kožní prohlídky častěji než muži, což přispívá k časnějšímu záchytu a lepší prognóze.",
        "code": "C43",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "kůže", "ženské zdraví", "mortalita"],
        "trend_context": "Ženská úmrtnost na melanom roste pomaleji než mužská — dík vyšší účasti na preventivních prohlídkách u kožního lékaře.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "hodgkin_muzi_mortalita": {
        "label": "Hodgkinův lymfom u mužů — úmrtnost",
        "human_name": "Úmrtnost na Hodgkinův lymfom u mužů",
        "description": "Roční počet úmrtí na Hodgkinův lymfom u mužů. U mužů je výskyt mírně vyšší, ale prognóza je stejně dobrá jako u žen.",
        "code": "C81 (muži)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "hematologie", "mužské zdraví", "mortalita"],
        "trend_context": "Úmrtnost dlouhodobě klesá díky kombinaci chemoterapie a ozařování. Hodgkinův lymfom u mužů je dnes plně léčitelný v drtivé většině případů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C81",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "hodgkin_zeny_mortalita": {
        "label": "Hodgkinův lymfom u žen — úmrtnost",
        "human_name": "Úmrtnost na Hodgkinův lymfom u žen",
        "description": "Roční počet úmrtí na Hodgkinův lymfom u žen. Stejně jako u mužů jde o onkologickou diagnózu s vynikající prognózou.",
        "code": "C81 (ženy)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "hematologie", "ženské zdraví", "mortalita"],
        "trend_context": "Úmrtnost u žen dlouhodobě klesá — Hodgkinův lymfom je dnes plně léčitelný u drtivé většiny pacientek.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C81",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "lymfomy_b_bunecne_muzi_mortalita": {
        "label": "B-buněčné non-Hodgkinovy lymfomy u mužů — úmrtnost",
        "human_name": "Úmrtnost na B-buněčné non-Hodgkinovy lymfomy u mužů",
        "description": "Roční počet úmrtí na B-buněčné non-Hodgkinovy lymfomy u mužů.",
        "code": "C82, C83, C85 (muži)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "hematologie", "mužské zdraví", "cílená léčba"],
        "trend_context": "Vývoj odráží pokrok v cílené léčbě (monoklonální protilátky) a kombinovaných režimech.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C82", "C83", "C85"],
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "lymfomy_b_bunecne_zeny_mortalita": {
        "label": "B-buněčné non-Hodgkinovy lymfomy u žen — úmrtnost",
        "human_name": "Úmrtnost na B-buněčné non-Hodgkinovy lymfomy u žen",
        "description": "Roční počet úmrtí na B-buněčné non-Hodgkinovy lymfomy u žen.",
        "code": "C82, C83, C85 (ženy)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "hematologie", "ženské zdraví", "cílená léčba"],
        "trend_context": "Vývoj odráží pokrok v cílené léčbě (monoklonální protilátky) — dlouhodobá remise je dnes u řady podtypů reálná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C82", "C83", "C85"],
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "slinivka_muzi_mortalita": {
        "label": "Rakovina slinivky břišní u mužů — úmrtnost",
        "human_name": "Úmrtnost na rakovinu slinivky břišní u mužů",
        "description": "Roční počet úmrtí na rakovinu slinivky břišní u mužů. U mužů je výskyt mírně vyšší kvůli vyšší míře kouření a obezity.",
        "code": "C25 (muži)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "trávicí systém", "mužské zdraví", "mortalita"],
        "trend_context": "Vývoj úmrtnosti kopíruje růst incidence — léčba zůstává obtížná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "slinivka_zeny_mortalita": {
        "label": "Rakovina slinivky břišní u žen — úmrtnost",
        "human_name": "Úmrtnost na rakovinu slinivky břišní u žen",
        "description": "Roční počet úmrtí na rakovinu slinivky břišní u žen.",
        "code": "C25 (ženy)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "trávicí systém", "ženské zdraví", "mortalita"],
        "trend_context": "Vývoj kopíruje růst incidence — slinivka zůstává jednou z prognosticky nejhorších onkologických diagnóz.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "mozek_muzi_mortalita": {
        "label": "Zhoubný nádor mozku u mužů — úmrtnost",
        "human_name": "Úmrtnost na zhoubný nádor mozku u mužů",
        "description": "Roční počet úmrtí na zhoubný nádor mozku u mužů.",
        "code": "C71 (muži)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "neurologie", "mužské zdraví", "mortalita"],
        "trend_context": "Vývoj kopíruje růst incidence. Glioblastom (nejagresivnější typ) zůstává léčebně obtížný i s moderní chirurgií a ozařováním.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "mozek_zeny_mortalita": {
        "label": "Zhoubný nádor mozku u žen — úmrtnost",
        "human_name": "Úmrtnost na zhoubný nádor mozku u žen",
        "description": "Roční počet úmrtí na zhoubný nádor mozku u žen.",
        "code": "C71 (ženy)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "neurologie", "ženské zdraví", "mortalita"],
        "trend_context": "Vývoj kopíruje růst incidence. U žen je o něco vyšší podíl benignějších typů (meningiomy nezahrnuté v C71), ale léčba zhoubných nádorů zůstává obtížná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "leukemie_muzi_mortalita": {
        "label": "Leukémie u mužů — úmrtnost",
        "human_name": "Úmrtnost na leukémie u mužů",
        "description": "Roční počet úmrtí na leukémie (všech typů) u mužů.",
        "code": "C91–C95 (muži)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (muži)",
        "relevant_for": ["onkologie", "hematologie", "mužské zdraví", "mortalita"],
        "trend_context": "Vývoj odráží stárnutí populace a moderní cílenou léčbu. U dětských leukémií klesá úmrtnost díky kombinaci chemoterapie a transplantace kostní dřeně.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "leukemie_zeny_mortalita": {
        "label": "Leukémie u žen — úmrtnost",
        "human_name": "Úmrtnost na leukémie u žen",
        "description": "Roční počet úmrtí na leukémie (všech typů) u žen.",
        "code": "C91–C95 (ženy)",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí (ženy)",
        "relevant_for": ["onkologie", "hematologie", "ženské zdraví", "mortalita"],
        "trend_context": "Vývoj odráží stárnutí populace a moderní cílenou léčbu. Dětské leukémie patří k onkologickým úspěchům — pětileté přežití přesahuje 85 %.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C91", "C92", "C93", "C94", "C95"],
        "year_col": "umrti_rok",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    # === NOR 1771 — Krajové snapshoty mortality 2022 ===
    "prsa_mortalita_kraje_2022": {
        "label": "Rakovina prsu — úmrtnost podle krajů 2022",
        "human_name": "Úmrtnost na rakovinu prsu — krajový pohled",
        "description": "Počet úmrtí na rakovinu prsu v roce 2022 podle krajů. Regionální rozdíly odrážejí velikost populace, věkovou strukturu a dostupnost specializované onkologické péče.",
        "code": "C50",
        "metric": "mortalita_2022",
        "metric_label": "Roční počet úmrtí (2022)",
        "relevant_for": ["onkologie", "ženské zdraví", "regionální nerovnosti", "kvalita léčby"],
        "trend_context": "Krajové rozdíly v absolutních úmrtích odrážejí velikost populace. Pro skutečné srovnání kvality péče by bylo potřeba přepočítat na 100 tisíc obyvatel a věkově standardizovat.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "umrti_rok",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "plice_mortalita_kraje_2022": {
        "label": "Rakovina plic — úmrtnost podle krajů 2022",
        "human_name": "Úmrtnost na rakovinu plic — krajový pohled",
        "description": "Počet úmrtí na rakovinu plic v roce 2022 podle krajů. Regionální rozdíly silně odrážejí historické vzorce kouření, profesionální expozici a kvalitu ovzduší.",
        "code": "C34",
        "metric": "mortalita_2022",
        "metric_label": "Roční počet úmrtí (2022)",
        "relevant_for": ["onkologie", "kouření", "regionální nerovnosti", "kvalita ovzduší"],
        "trend_context": "U rakoviny plic jsou krajové rozdíly výraznější než u jiných onkologických diagnóz — odrážejí těžební a průmyslovou historii některých regionů (severní Morava, severozápadní Čechy) a místní kvalitu ovzduší.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "umrti_rok",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "prostata_mortalita_kraje_2022": {
        "label": "Rakovina prostaty — úmrtnost podle krajů 2022",
        "human_name": "Úmrtnost na rakovinu prostaty — krajový pohled",
        "description": "Počet úmrtí na rakovinu prostaty v roce 2022 podle krajů. Krajové rozdíly odrážejí věkovou strukturu populace a dostupnost specializované onkologické péče.",
        "code": "C61",
        "metric": "mortalita_2022",
        "metric_label": "Roční počet úmrtí (2022)",
        "relevant_for": ["onkologie", "mužské zdraví", "regionální nerovnosti", "preventivní prohlídky"],
        "trend_context": "Krajové rozdíly v úmrtnosti odrážejí velikost mužské populace 50+ let v kraji, účast na preventivních prohlídkách a dostupnost moderní léčby (centra specializované onkologické péče).",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "umrti_rok",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "kolorektum_mortalita_kraje_2022": {
        "label": "Rakovina tlustého střeva a konečníku — úmrtnost podle krajů 2022",
        "human_name": "Úmrtnost na rakovinu tlustého střeva a konečníku — krajový pohled",
        "description": "Počet úmrtí na rakovinu tlustého střeva a konečníku v roce 2022 podle krajů. Krajové rozdíly odrážejí velikost populace, životní styl, účast na screeningu a dostupnost koloproktologické péče.",
        "code": "C18–C20",
        "metric": "mortalita_2022",
        "metric_label": "Roční počet úmrtí (2022)",
        "relevant_for": ["onkologie", "screening tlustého střeva", "regionální nerovnosti", "životní styl"],
        "trend_context": "Krajové rozdíly v úmrtnosti odrážejí účast na screeningu (test na skryté krvácení do stolice, kolonoskopie), životní styl (strava, obezita) a dostupnost moderní léčby.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "umrti_rok",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "melanom_mortalita_kraje_2022": {
        "label": "Zhoubný melanom kůže — úmrtnost podle krajů 2022",
        "human_name": "Úmrtnost na zhoubný melanom kůže — krajový pohled",
        "description": "Počet úmrtí na zhoubný melanom kůže v roce 2022 podle krajů. Regionální rozdíly odrážejí velikost populace a dostupnost preventivních kožních prohlídek.",
        "code": "C43",
        "metric": "mortalita_2022",
        "metric_label": "Roční počet úmrtí (2022)",
        "relevant_for": ["onkologie", "kůže", "regionální nerovnosti", "imunoterapie"],
        "trend_context": "Krajové rozdíly v úmrtnosti odrážejí dostupnost kožních lékařů, osvětu o nebezpečí ultrafialového záření a dostupnost moderní léčby (imunoterapie, cílené léky).",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "aggregation": "regional_snapshot",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "umrti_rok",
        "region_col": "kraj_kod",
        "target_year": 2022,
    },
    "vzacne_nadory_mortalita": {
        "label": "Vzácné onkologické diagnózy — úmrtnost",
        "human_name": "Úmrtnost na vzácné onkologické diagnózy",
        "description": "Roční počet úmrtí na souhrn vzácných onkologických diagnóz — sarkomy měkkých tkání, mezoteliom, nádory oka, nadledvin, dutiny nosní, brzlíku a dalších.",
        "code": "C30–C31, C37–C38, C45–C49, C69, C74–C75",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": ["onkologie", "vzácná onemocnění", "specializovaná péče"],
        "trend_context": "Souhrnný pohled na úmrtnost u vzácných nádorů. Péče se soustřeďuje do specializovaných center, která mají dostatečnou zkušenost s konkrétními diagnózami.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C30", "C31", "C37", "C38", "C45", "C46", "C47", "C48", "C49", "C69", "C74", "C75"],
        "year_col": "umrti_rok",
    },
    "mozek_mortalita": {
        "label": "Zhoubný nádor mozku — úmrtnost",
        "human_name": "Úmrtnost na zhoubný nádor mozku",
        "description": "Roční počet úmrtí na zhoubné nádory mozku v Česku. Patří k onkologicky nejhůře léčitelným diagnózám — léčba je komplikovaná polohou nádoru a citlivostí mozkové tkáně.",
        "code": "C71",
        "metric": "mortalita_rocni",
        "metric_label": "Roční počet úmrtí v ČR",
        "relevant_for": [
            "onkologie",
            "neurologie",
            "kvalita léčby",
            "výzkum",
        ],
        "trend_context": "Vývoj kopíruje růst incidence — moderní zobrazovací metody zachycují víc nádorů, ale prognóza u nejagresivnějších typů (například glioblastom) zůstává navzdory pokroku v chirurgii, ozařování i chemoterapii velmi vážná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1771-novotvary-mortalita-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "umrti_rok",
    },
    # === NOR 1772 — Přežití pacientů ===
    # Třetí NOR CSV (~131 MB). Klíčové sloupce: rok_dg, doba_sledovani (dny),
    # preziti (0/1). 5-leté přežití = % pacientů s doba_sledovani >= 5*365
    # AND preziti=1, filtrováno na pacienty diagnostikované do 2017.
    # Filtr je na diagnoza_skupina (číselný kód), ne na diagnoza_kod.
    # Mapování: 1=C00-C14, 2=C15, 3=C16, 4=C18-C20, 7=C25, 8=C32, 9=C33-C34,
    # 10=C43, 11=C44, 13=C50, 14=C53, 15=C54-C55, 16=C56, 17=C61, 18=C62,
    # 19=C64, 20=C67, 21=C71-C72, 22=C73, 23=C81, 24=C82,C83,C85, 25=C90,
    # 26=C91-C95.
    "prsa_preziti_5y": {
        "label": "Rakovina prsu — 5leté přežití",
        "human_name": "5leté přežití u rakoviny prsu",
        "description": "Procento pacientek (a pacientů), které žijí 5 a více let po diagnóze rakoviny prsu. Klíčový ukazatel úspěšnosti časného záchytu a léčby — víc znamená lepší prognózu pro nové pacienty.",
        "code": "C50",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "kvalita léčby",
            "mamografický screening",
        ],
        "trend_context": "Hlavní ukazatel pokroku v péči o rakovinu prsu. Vývoj odráží zlepšení časného záchytu (mamografický screening od 2002) a moderní léčby (cílená a hormonální terapie). Česko se postupně dostává k úrovni zemí s nejlepší péčí.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 13,
        "year_col": "rok_dg",
    },
    "plice_preziti_5y": {
        "label": "Rakovina plic — 5leté přežití",
        "human_name": "5leté přežití u rakoviny plic",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny plic. Patří k onkologicky nejhůře léčitelným diagnózám — rakovina plic se obvykle zachytí v pokročilém stadiu.",
        "code": "C33–C34",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "kouření",
            "screening",
            "kvalita léčby",
        ],
        "trend_context": "Patří k onkologickým diagnózám s nejnižším přežitím — nemoc se obvykle zachytí pozdě, kdy je rozšířená. Od roku 2022 zavedený plicní screening pro dlouhodobé kuřáky má potenciál posunout záchyt k časnějším stadiím a tím i zlepšit prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 9,
        "year_col": "rok_dg",
    },
    "prostata_preziti_5y": {
        "label": "Rakovina prostaty — 5leté přežití",
        "human_name": "5leté přežití u rakoviny prostaty",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny prostaty. Patří k onkologicky nejlépe prognosticky diagnózám — rakovina prostaty roste obvykle pomalu a moderní léčba pokročila zásadně.",
        "code": "C61",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "preventivní prohlídky",
            "kvalita léčby",
        ],
        "trend_context": "Vývoj odráží zavedení vyšetření krve na prostatický specifický antigen, díky kterému se zachytí mnoho pomalu rostoucích nádorů v časném stadiu. Moderní léčba (operace, ozařování, hormonální terapie) dál zlepšuje prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 17,
        "year_col": "rok_dg",
    },
    "kolorektum_preziti_5y": {
        "label": "Rakovina tlustého střeva a konečníku — 5leté přežití",
        "human_name": "5leté přežití u rakoviny tlustého střeva a konečníku",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny tlustého střeva a konečníku. Klíčový ukazatel úspěchu českého screeningu — čím dříve se nádor zachytí, tím lepší je prognóza.",
        "code": "C18–C20",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "kvalita léčby",
            "prevence",
        ],
        "trend_context": "Vývoj odráží zavedení plošného screeningu (od 2000 testem na skryté krvácení do stolice, od 2009 také kolonoskopií) a zlepšení chirurgické i medikamentózní léčby.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 4,
        "year_col": "rok_dg",
    },
    "melanom_preziti_5y": {
        "label": "Zhoubný melanom kůže — 5leté přežití",
        "human_name": "5leté přežití u zhoubného melanomu kůže",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze zhoubného melanomu kůže. Včas zachycený melanom má vynikající prognózu, u pokročilých forem zase v posledních letech zásadně zlepšila imunoterapie.",
        "code": "C43",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "kůže",
            "kvalita léčby",
            "imunoterapie",
        ],
        "trend_context": "Vývoj odráží osvětu o preventivních kožních prohlídkách (lepší časný záchyt) a revoluci v léčbě pokročilých melanomů — cílené léky a imunoterapie změnily prognózu u dříve neléčitelných stavů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 10,
        "year_col": "rok_dg",
    },
    "zaludek_preziti_5y": {
        "label": "Rakovina žaludku — 5leté přežití",
        "human_name": "5leté přežití u rakoviny žaludku",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny žaludku. Záchyt zůstává obtížný, ale moderní chirurgie a chemoterapie postupně zlepšují prognózu.",
        "code": "C16",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "kvalita léčby",
        ],
        "trend_context": "Vývoj odráží modernizaci chirurgické léčby (minimálně invazivní operace), zlepšení chemoterapie a v posledních letech i cílenou léčbu u některých podtypů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 3,
        "year_col": "rok_dg",
    },
    "slinivka_preziti_5y": {
        "label": "Rakovina slinivky břišní — 5leté přežití",
        "human_name": "5leté přežití u rakoviny slinivky břišní",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny slinivky břišní. Patří k onkologicky nejhorším prognózám — pětileté přežití zůstává dlouhodobě nízké, navzdory pokroku v jiných onkologických oborech.",
        "code": "C25",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "kvalita léčby",
            "výzkum",
        ],
        "trend_context": "Vývoj odráží mírné zlepšení chirurgické a chemoterapeutické léčby, ale rakovina slinivky zůstává jednou z nejhůře léčitelných onkologických diagnóz. Velký prostor pro budoucí výzkum časné diagnostiky a cílené léčby.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 7,
        "year_col": "rok_dg",
    },
    "cipek_preziti_5y": {
        "label": "Rakovina hrdla děložního — 5leté přežití",
        "human_name": "5leté přežití u rakoviny hrdla děložního",
        "description": "Procento pacientek, které žijí 5 a více let po diagnóze rakoviny hrdla děložního. Díky gynekologickému screeningu se daří zachytit nádor v časném stadiu, kdy je prognóza výrazně lepší.",
        "code": "C53",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientek)",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "gynekologický screening",
            "očkování",
        ],
        "trend_context": "Vývoj odráží zavedení gynekologického screeningu (cytologie čípku) a v posledních letech očkování proti lidskému papilomaviru. Časný záchyt v stadiu přednádorových změn umožňuje vyléčit pacientku dříve, než vůbec vznikne rakovina.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 14,
        "year_col": "rok_dg",
    },
    "hodgkin_preziti_5y": {
        "label": "Hodgkinův lymfom — 5leté přežití",
        "human_name": "5leté přežití u Hodgkinova lymfomu",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze Hodgkinova lymfomu. Patří k onkologicky nejúspěšnějším diagnózám — naprostou většinu pacientů se daří úplně vyléčit.",
        "code": "C81",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "kvalita léčby",
            "mladší pacienti",
        ],
        "trend_context": "Hodgkinův lymfom byl jednou z prvních rakovin, u které medicína dokázala dosáhnout vysokých úspěchů léčby. Kombinace chemoterapie a ozařování vyléčí drtivou většinu pacientů a moderní režimy se snaží minimalizovat dlouhodobé následky.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 23,
        "year_col": "rok_dg",
    },
    "lymfomy_b_bunecne_preziti_5y": {
        "label": "B-buněčné non-Hodgkinovy lymfomy — 5leté přežití",
        "human_name": "5leté přežití u B-buněčných non-Hodgkinových lymfomů",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze B-buněčných non-Hodgkinových lymfomů. Drtivá většina non-Hodgkinových lymfomů spadá do této skupiny.",
        "code": "C82, C83, C85",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "kvalita léčby",
            "cílená léčba",
        ],
        "trend_context": "Vývoj odráží zásadní pokrok v léčbě B-buněčných lymfomů — od cílených léků (monoklonálních protilátek) po kombinované režimy s chemoterapií. U řady podtypů se daří dosáhnout dlouhodobé remise nebo úplného vyléčení.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 24,
        "year_col": "rok_dg",
    },
    "leukemie_preziti_5y": {
        "label": "Leukémie — 5leté přežití",
        "human_name": "5leté přežití u leukémií",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze leukémií (souhrn všech typů). U dětských leukémií dosahuje přežití velmi vysokých hodnot, u dospělých velmi závisí na typu.",
        "code": "C91–C95",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "hematologie",
            "kvalita léčby",
            "transplantace kostní dřeně",
        ],
        "trend_context": "Vývoj odráží pokrok v cílené léčbě (například léky proti chronické lymfocytární leukémii nebo akutní lymfoblastické leukémii) a v transplantaci kostní dřeně. U dětských leukémií patří přežití k onkologickým úspěchům.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 26,
        "year_col": "rok_dg",
    },
    "ustni_dutina_preziti_5y": {
        "label": "Rakovina dutiny ústní a hltanu — 5leté přežití",
        "human_name": "5leté přežití u rakoviny dutiny ústní a hltanu",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny dutiny ústní a hltanu. Prognóza silně závisí na stadiu záchytu a na příčině (klasické kuřácké/alkoholické vs. související s lidským papilomavirem).",
        "code": "C00–C14",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "kouření", "alkohol", "kvalita léčby"],
        "trend_context": "U nádorů spojených s lidským papilomavirem je prognóza obvykle lepší než u klasických kuřáckých nádorů. Modernizace chirurgické léčby a ozařování zlepšuje šance pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 1,
        "year_col": "rok_dg",
    },
    "jicen_preziti_5y": {
        "label": "Rakovina jícnu — 5leté přežití",
        "human_name": "5leté přežití u rakoviny jícnu",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny jícnu. Patří k onkologicky nejhůře léčitelným diagnózám — pětileté přežití zůstává dlouhodobě nízké.",
        "code": "C15",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "trávicí systém", "kvalita léčby"],
        "trend_context": "Vývoj odráží zlepšení chirurgické léčby a chemoterapie. Záchyt je obtížný — první příznaky (potíže s polykáním) se objevují, až když je nádor pokročilý.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 2,
        "year_col": "rok_dg",
    },
    "hrtan_preziti_5y": {
        "label": "Rakovina hrtanu — 5leté přežití",
        "human_name": "5leté přežití u rakoviny hrtanu",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny hrtanu. Při včasném záchytu je prognóza dobrá, u pokročilých stadií se mortalita zvyšuje.",
        "code": "C32",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "kouření", "alkohol", "kvalita léčby"],
        "trend_context": "Vývoj odráží modernizaci chirurgické léčby (záchovné výkony, robotická chirurgie) a ozařování. Důležitá je včasná diagnóza, kterou pomáhají ORL preventivní prohlídky u rizikových pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 8,
        "year_col": "rok_dg",
    },
    "kuze_nemelanomove_preziti_5y": {
        "label": "Kožní rakoviny mimo melanom — 5leté přežití",
        "human_name": "5leté přežití u kožních rakovin mimo melanom",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze nemelanomových kožních rakovin (bazaliom, spinocelulární karcinom). Patří k onkologicky nejlépe prognosticky diagnózám — naprostá většina pacientů se daří úplně vyléčit.",
        "code": "C44",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "kůže", "kvalita léčby"],
        "trend_context": "Vývoj se drží na vysokých hodnotách. Bazaliom téměř nemetastázuje, spinaliom má dobrou prognózu při včasném záchytu. Pouze ve výjimečných pokročilých případech je léčba obtížnější.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 11,
        "year_col": "rok_dg",
    },
    "deloha_preziti_5y": {
        "label": "Rakovina těla děložního — 5leté přežití",
        "human_name": "5leté přežití u rakoviny těla děložního",
        "description": "Procento pacientek, které žijí 5 a více let po diagnóze rakoviny těla děložního. Brzký záchyt přes výrazný příznak (krvácení po menopauze) obvykle umožňuje úspěšnou léčbu chirurgicky.",
        "code": "C54–C55",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientek)",
        "relevant_for": ["onkologie", "ženské zdraví", "kvalita léčby"],
        "trend_context": "Vývoj odráží modernizaci chirurgické léčby (minimálně invazivní operace) a kombinaci s ozařováním a chemoterapií. Časný záchyt zůstává klíčový pro prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 15,
        "year_col": "rok_dg",
    },
    "vajecnik_preziti_5y": {
        "label": "Rakovina vaječníku — 5leté přežití",
        "human_name": "5leté přežití u rakoviny vaječníku",
        "description": "Procento pacientek, které žijí 5 a více let po diagnóze rakoviny vaječníku. Patří k onkologicky nejhůře prognosticky ženským nádorům — záchyt je obtížný, většina pacientek se diagnostikuje ve stadiu pokročilého onemocnění.",
        "code": "C56",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientek)",
        "relevant_for": ["onkologie", "ženské zdraví", "kvalita léčby", "genetika"],
        "trend_context": "Vývoj odráží modernizaci chirurgické léčby a chemoterapie. U nositelek mutace v genech BRCA1 a BRCA2 přináší přínos i preventivní operace a cílená léčba (PARP inhibitory).",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 16,
        "year_col": "rok_dg",
    },
    "varlata_preziti_5y": {
        "label": "Rakovina varlat — 5leté přežití",
        "human_name": "5leté přežití u rakoviny varlat",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny varlat. Patří k onkologicky nejúspěšnějším diagnózám — drtivou většinu pacientů se daří úplně vyléčit.",
        "code": "C62",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "mužské zdraví", "kvalita léčby"],
        "trend_context": "Rakovina varlat je modelovým příkladem onkologického úspěchu. Kombinace operace, ozařování a chemoterapie umožňuje vyléčit drtivou většinu pacientů včetně řady případů s metastázami.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 18,
        "year_col": "rok_dg",
    },
    "ledvina_preziti_5y": {
        "label": "Rakovina ledviny — 5leté přežití",
        "human_name": "5leté přežití u rakoviny ledviny",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny ledviny. Časný náhodný záchyt přes zobrazovací vyšetření zlepšuje prognózu.",
        "code": "C64",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "močový systém", "kvalita léčby", "cílená léčba"],
        "trend_context": "Vývoj odráží lepší časný záchyt díky ultrazvuku a počítačové tomografii (nádor se často najde náhodou při vyšetření z jiného důvodu) a zásadní pokrok v léčbě pokročilých případů (cílená terapie, imunoterapie).",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 19,
        "year_col": "rok_dg",
    },
    "mocovy_mechyr_preziti_5y": {
        "label": "Rakovina močového měchýře — 5leté přežití",
        "human_name": "5leté přežití u rakoviny močového měchýře",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny močového měchýře. Při včasném záchytu (povrchové formy) je prognóza dobrá, u invazivních forem se výrazně zhoršuje.",
        "code": "C67",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "močový systém", "kvalita léčby"],
        "trend_context": "Vývoj odráží lepší časný záchyt (přes hematurii — krev v moči) a modernizaci léčby. Klíčové je dlouhodobé sledování — povrchové nádory se rády recidivují.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 20,
        "year_col": "rok_dg",
    },
    "stitna_zlaza_preziti_5y": {
        "label": "Rakovina štítné žlázy — 5leté přežití",
        "human_name": "5leté přežití u rakoviny štítné žlázy",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny štítné žlázy. Patří k onkologicky nejlépe prognosticky diagnózám — papilární karcinom (drtivá většina případů) má vynikající prognózu.",
        "code": "C73",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "hormonální systém", "kvalita léčby"],
        "trend_context": "Vývoj se drží na vysokých hodnotách díky pomalému růstu papilárního karcinomu a moderní léčbě (chirurgie + radiojód). Vyšší podíl drobných nádorů zachycených ultrazvukem dál zvyšuje průměrné přežití.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 22,
        "year_col": "rok_dg",
    },
    "myelom_preziti_5y": {
        "label": "Mnohočetný myelom — 5leté přežití",
        "human_name": "5leté přežití u mnohočetného myelomu",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze mnohočetného myelomu. Moderní léčba zásadně posunula prognózu — nová cílená léčba a transplantace kostní dřeně prodloužily přežití několikanásobně.",
        "code": "C90",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": ["onkologie", "hematologie", "kvalita léčby", "cílená léčba"],
        "trend_context": "Vývoj odráží zásadní pokrok v léčbě — od proteasomových inhibitorů po monoklonální protilátky a CAR-T buněčnou terapii. Mnohočetný myelom přešel z téměř fatální nemoci na chronické onemocnění s dlouhým přežitím.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 25,
        "year_col": "rok_dg",
    },
    "plice_muzi_preziti_5y": {
        "label": "Rakovina plic u mužů — 5leté přežití",
        "human_name": "5leté přežití u rakoviny plic u mužů",
        "description": "Procento mužů, kteří žijí 5 a více let po diagnóze rakoviny plic. U mužů je výskyt vyšší kvůli historicky vyšší míře kouření, ale přežití je srovnatelné se ženami.",
        "code": "C34 (muži)",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% mužů)",
        "relevant_for": ["onkologie", "kouření", "mužské zdraví", "kvalita léčby"],
        "trend_context": "U mužů s rakovinou plic je drtivá většina pacientů kuřáků. Vývoj přežití odráží zlepšení léčby (cílené léky, imunoterapie) a snahu o časnější záchyt.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 9,
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "plice_zeny_preziti_5y": {
        "label": "Rakovina plic u žen — 5leté přežití",
        "human_name": "5leté přežití u rakoviny plic u žen",
        "description": "Procento žen, které žijí 5 a více let po diagnóze rakoviny plic. U žen je vyšší podíl nekuřaček a častější jsou jiné histologické typy (adenokarcinom).",
        "code": "C34 (ženy)",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% žen)",
        "relevant_for": ["onkologie", "kouření", "ženské zdraví", "kvalita léčby"],
        "trend_context": "U žen s rakovinou plic je vyšší podíl nekuřaček. Adenokarcinom, který u žen převažuje, často dobře reaguje na cílenou léčbu — to vytváří potenciál pro lepší prognózu než u klasického kuřáckého malobuněčného karcinomu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 9,
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "kolorektum_muzi_preziti_5y": {
        "label": "Rakovina tlustého střeva a konečníku u mužů — 5leté přežití",
        "human_name": "5leté přežití u rakoviny tlustého střeva a konečníku u mužů",
        "description": "Procento mužů, kteří žijí 5 a více let po diagnóze rakoviny tlustého střeva a konečníku.",
        "code": "C18–C20 (muži)",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% mužů)",
        "relevant_for": ["onkologie", "mužské zdraví", "screening tlustého střeva", "kvalita léčby"],
        "trend_context": "U mužů s rakovinou tlustého střeva je obvykle prognóza horší kvůli nižší účasti na screeningu a pozdějšímu záchytu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 4,
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "kolorektum_zeny_preziti_5y": {
        "label": "Rakovina tlustého střeva a konečníku u žen — 5leté přežití",
        "human_name": "5leté přežití u rakoviny tlustého střeva a konečníku u žen",
        "description": "Procento žen, které žijí 5 a více let po diagnóze rakoviny tlustého střeva a konečníku.",
        "code": "C18–C20 (ženy)",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% žen)",
        "relevant_for": ["onkologie", "ženské zdraví", "screening tlustého střeva", "kvalita léčby"],
        "trend_context": "U žen s rakovinou tlustého střeva je vyšší účast na screeningu a obvykle časnější záchyt — to přispívá k lepší prognóze než u mužů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 4,
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "prsa_mladi_preziti_5y": {
        "label": "Rakovina prsu u mladších žen — 5leté přežití",
        "human_name": "5leté přežití u rakoviny prsu u mladších žen (do 49 let)",
        "description": "Procento žen mladších 50 let, které žijí 5 a více let po diagnóze rakoviny prsu. U mladších pacientek jsou nádory často agresivnější, ale moderní léčba (cílená terapie podle subtypu) pomáhá vyrovnat prognózu.",
        "code": "C50",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientek do 49 let)",
        "relevant_for": ["onkologie", "ženské zdraví", "early-onset", "kvalita léčby"],
        "trend_context": "U mladších žen je prognóza historicky méně příznivá než u starších. Pokrok v moderní léčbě (cílená terapie, hormonální léčba podle subtypu) postupně vyrovnává rozdíly.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 13,
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "prsa_starsi_preziti_5y": {
        "label": "Rakovina prsu u starších žen — 5leté přežití",
        "human_name": "5leté přežití u rakoviny prsu u starších žen (50+ let)",
        "description": "Procento žen 50 a více let, které žijí 5 a více let po diagnóze rakoviny prsu. Hlavní cílová skupina mamografického screeningu — časný záchyt zlepšuje prognózu.",
        "code": "C50",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientek 50+ let)",
        "relevant_for": ["onkologie", "ženské zdraví", "mamografický screening", "kvalita léčby"],
        "trend_context": "Hlavní cílová skupina mamografického screeningu. Vývoj odráží zlepšení časného záchytu a moderní léčbu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 13,
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "kolorektum_mladi_preziti_5y": {
        "label": "Rakovina tlustého střeva a konečníku u mladších dospělých — 5leté přežití",
        "human_name": "5leté přežití u rakoviny tlustého střeva a konečníku u mladších dospělých (do 49 let)",
        "description": "Procento pacientů mladších 50 let, kteří žijí 5 a více let po diagnóze rakoviny tlustého střeva a konečníku. U mladších pacientů je prognóza dlouhodobě horší kvůli častému pozdějšímu záchytu mimo screening.",
        "code": "C18–C20",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů do 49 let)",
        "relevant_for": ["onkologie", "early-onset", "screening tlustého střeva", "kvalita léčby"],
        "trend_context": "Mladší pacienti často přicházejí k diagnóze v pozdějším stadiu. Diskuse o snížení věkové hranice screeningu (v některých zemích už na 45 let) je založena právě na potřebě zlepšit prognózu u mladších pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 4,
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66000004", "66005009", "66010014", "66015019",
            "66020024", "66025029", "66030034", "66035039",
            "66040044", "66045049",
        ],
    },
    "kolorektum_starsi_preziti_5y": {
        "label": "Rakovina tlustého střeva a konečníku u starších dospělých — 5leté přežití",
        "human_name": "5leté přežití u rakoviny tlustého střeva a konečníku u starších dospělých (50+ let)",
        "description": "Procento pacientů 50 a více let, kteří žijí 5 a více let po diagnóze rakoviny tlustého střeva a konečníku. Hlavní cílová skupina českého screeningu.",
        "code": "C18–C20",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů 50+ let)",
        "relevant_for": ["onkologie", "screening tlustého střeva", "starší pacienti", "kvalita léčby"],
        "trend_context": "Hlavní cílová skupina českého screeningu rakoviny tlustého střeva. Časný záchyt přes test na skryté krvácení nebo kolonoskopii umožňuje šetrnější léčbu a lepší prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 4,
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": [
            "66050054", "66055059", "66060064", "66065069",
            "66070074", "66075079", "66080084", "66085999",
        ],
    },
    "mozek_preziti_5y": {
        "label": "Zhoubný nádor mozku — 5leté přežití",
        "human_name": "5leté přežití u zhoubného nádoru mozku",
        "description": "Procento pacientů, kteří žijí 5 a více let po diagnóze zhoubného nádoru mozku. Patří k diagnostikám s nejhorší prognózou v onkologii — léčbu komplikuje poloha nádoru a citlivost mozkové tkáně.",
        "code": "C71",
        "metric": "preziti_5_let",
        "metric_label": "5leté přežití (% pacientů)",
        "relevant_for": [
            "onkologie",
            "neurologie",
            "kvalita léčby",
            "výzkum",
        ],
        "trend_context": "Vývoj odráží mírné zlepšení chirurgie, ozařování a chemoterapie. U nejagresivnějších typů (například glioblastom) zůstává prognóza navzdory pokroku velmi vážná — patří k onkologickým výzvám, kde výzkum nabízí výhled na zásadní změnu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/378/Otevrena-data-NR-07-03-preziti-novotvary-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1772-novotvary-preziti-otevrena-data",
        "aggregation": "survival_5y",
        "group_col": "diagnoza_skupina",
        "diagnosis_group": 21,
        "year_col": "rok_dg",
    },
    # === NOR 1770 — Záchyt v stadiu (% pacientů zachycených v daném stadiu) ===
    # Stadium TNM 1-4 v CSV NOR 1770. Hodnoty 'X' (neznámé) a 'Y' (neaplikovatelné)
    # se vyřazují, aby čísla byla srovnatelná v čase.
    "prsa_stadium_1_share": {
        "label": "Rakovina prsu — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny prsu v 1. stadiu",
        "description": "Procento nově diagnostikovaných pacientek (a pacientů) zachycených v 1. stadiu rakoviny prsu — nejranější, lokalizovaný nádor s nejlepší prognózou. Ukazatel úspěšnosti časného záchytu (mamografický screening, samovyšetření).",
        "code": "C50",
        "metric": "stadium_1_share",
        "metric_label": "Pacientky zachycené v 1. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "mamografický screening",
            "prevence",
        ],
        "trend_context": "Klíčový ukazatel úspěšnosti mamografického screeningu zavedeného v Česku od roku 2002. Časný záchyt zásadně zvyšuje šanci na úplné vyléčení a umožňuje šetrnější léčbu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "prsa_stadium_4_share": {
        "label": "Rakovina prsu — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny prsu ve 4. stadiu",
        "description": "Procento nově diagnostikovaných pacientek zachycených až ve 4. stadiu rakoviny prsu — pokročilá fáze s metastázami. Nízké hodnoty znamenají úspěch časného záchytu.",
        "code": "C50",
        "metric": "stadium_4_share",
        "metric_label": "Pacientky zachycené ve 4. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "ženské zdraví",
            "pozdní záchyt",
            "metastázy",
        ],
        "trend_context": "Doplněk k záchytu v 1. stadiu — ukazuje, kolika pacientkám se nedaří nádor zachytit včas. Čím nižší hodnota, tím lépe pracují screening a osvěta.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C50",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "kolorektum_stadium_1_share": {
        "label": "Rakovina tlustého střeva a konečníku — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny tlustého střeva a konečníku v 1. stadiu",
        "description": "Procento nově diagnostikovaných pacientů zachycených v 1. stadiu — nejranější, lokalizovaný nádor. Klíčový ukazatel úspěchu screeningu kolonoskopií a testem na skryté krvácení.",
        "code": "C18–C20",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "prevence",
            "kolonoskopie",
        ],
        "trend_context": "Klíčový ukazatel úspěšnosti českého screeningu — testu na skryté krvácení do stolice (od 2000) a kolonoskopie (od 2009). Záchyt v časném stadiu umožňuje šetrnější chirurgickou léčbu a výrazně lepší prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "kolorektum_stadium_4_share": {
        "label": "Rakovina tlustého střeva a konečníku — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny tlustého střeva a konečníku ve 4. stadiu",
        "description": "Procento nově diagnostikovaných pacientů zachycených až ve 4. stadiu — pokročilý nádor s metastázami. Nízké hodnoty znamenají úspěch screeningu a osvěty.",
        "code": "C18–C20",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "screening tlustého střeva",
            "pozdní záchyt",
            "metastázy",
        ],
        "trend_context": "Doplněk k záchytu v 1. stadiu — ukazuje, kolika pacientům se nedaří zachytit nádor včas. Vývoj klesá s rozšiřováním screeningu, ale stále řada pacientů přichází pozdě, často protože screening nevyužili.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "plice_stadium_1_share": {
        "label": "Rakovina plic — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny plic v 1. stadiu",
        "description": "Procento nově diagnostikovaných pacientů s rakovinou plic zachycených v 1. stadiu. U rakoviny plic je časný záchyt mimořádně obtížný — nemoc se obvykle projeví, až když je rozšířená.",
        "code": "C34",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "kouření",
            "screening",
            "kvalita léčby",
        ],
        "trend_context": "Od roku 2022 je v Česku zavedený plicní screening pro dlouhodobé kuřáky pomocí nízkodávkové počítačové tomografie. Cílem je posunout záchyt do časnějších stadií a tím zvýšit šanci na vyléčení.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "plice_stadium_4_share": {
        "label": "Rakovina plic — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny plic ve 4. stadiu",
        "description": "Procento nově diagnostikovaných pacientů s rakovinou plic zachycených až ve 4. stadiu — pokročilá fáze s metastázami. U rakoviny plic je pozdní záchyt dlouhodobě hlavním důvodem vysoké úmrtnosti.",
        "code": "C34",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "kouření",
            "pozdní záchyt",
            "metastázy",
        ],
        "trend_context": "Hlavní důvod vysoké úmrtnosti na rakovinu plic — drtivá většina pacientů přichází k diagnóze, až když jsou tumor a metastázy rozsáhlé. Zavedený plicní screening (2022+) má potenciál tento podíl postupně snižovat.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "prostata_stadium_1_share": {
        "label": "Rakovina prostaty — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny prostaty v 1. stadiu",
        "description": "Procento nově diagnostikovaných pacientů s rakovinou prostaty zachycených v 1. stadiu — lokalizovaný nádor s nejlepší prognózou. Vysoký podíl odráží úspěch vyšetření krve na prostatický specifický antigen.",
        "code": "C61",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "preventivní prohlídky",
            "prevence",
        ],
        "trend_context": "Vývoj odráží zavedení vyšetření krve na prostatický specifický antigen. Časný záchyt umožňuje šetrnější léčbu (operace, ozařování bez systémové terapie) a u řady pacientů i 'aktivní sledování' místo okamžité léčby.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "prostata_stadium_4_share": {
        "label": "Rakovina prostaty — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny prostaty ve 4. stadiu",
        "description": "Procento nově diagnostikovaných pacientů s rakovinou prostaty zachycených až ve 4. stadiu — pokročilý nádor s metastázami. Nízké hodnoty znamenají úspěch časného záchytu.",
        "code": "C61",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "mužské zdraví",
            "pozdní záchyt",
            "metastázy",
        ],
        "trend_context": "Doplněk k záchytu v 1. stadiu — i přes široké využití vyšetření krve na prostatický specifický antigen část pacientů přichází k diagnóze pozdě, často protože preventivní prohlídky vynechali nebo byli rezistentní vůči vyšetření.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C61",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "melanom_stadium_1_share": {
        "label": "Zhoubný melanom kůže — záchyt v 1. stadiu",
        "human_name": "Záchyt zhoubného melanomu kůže v 1. stadiu",
        "description": "Procento nově diagnostikovaných pacientů s melanomem zachyceným v 1. stadiu — tenký, lokalizovaný nádor s vynikající prognózou. Melanom má díky viditelnosti na kůži jeden z nejvyšších podílů časného záchytu mezi rakovinami.",
        "code": "C43",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "kůže",
            "preventivní prohlídky",
            "prevence",
        ],
        "trend_context": "Vývoj odráží osvětu o samovyšetření a preventivních prohlídkách u kožního lékaře. Časný záchyt umožňuje vyléčit pacienta drobným chirurgickým zákrokem s vynikající prognózou.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "melanom_stadium_4_share": {
        "label": "Zhoubný melanom kůže — záchyt ve 4. stadiu",
        "human_name": "Záchyt zhoubného melanomu kůže ve 4. stadiu",
        "description": "Procento pacientů s melanomem zachyceným až ve 4. stadiu — pokročilý nádor s metastázami. U melanomu je tento podíl nízký, protože nádor je viditelný na kůži a daří se ho zachytit dříve.",
        "code": "C43",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "kůže",
            "pozdní záchyt",
            "imunoterapie",
        ],
        "trend_context": "Část pacientů přichází k diagnóze pozdě — typicky proto, že melanom byl skrytý (například na pokožce hlavy nebo na zádech). U pokročilých melanomů přitom imunoterapie a cílená léčba zásadně zlepšily prognózu.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "zaludek_stadium_1_share": {
        "label": "Rakovina žaludku — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny žaludku v 1. stadiu",
        "description": "Procento pacientů s rakovinou žaludku zachycenou v 1. stadiu. U rakoviny žaludku je časný záchyt obtížný — bez screeningu se nemoc obvykle projeví, až když je pokročilá.",
        "code": "C16",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "časný záchyt",
            "kvalita léčby",
        ],
        "trend_context": "V Česku není plošný screening rakoviny žaludku, časný záchyt obvykle závisí na vyšetření kvůli zažívacím potížím. Pacientům se zvýšeným rizikem (rodinná anamnéza, infekce Helicobacter pylori) lze doporučit gastroskopické sledování.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    # Věkové splity pro slinivku, mozek, jícen (mladší/starší 50)
    "slinivka_mladi_incidence": {
        "label": "Rakovina slinivky břišní u mladších dospělých — incidence",
        "human_name": "Rakovina slinivky břišní u mladších dospělých (do 49 let)",
        "description": "Zhoubný nádor slinivky břišní u pacientů mladších 50 let. U mladších pacientů je rakovina slinivky vzácnější, ale prognóza zůstává stejně obtížná jako u starších.",
        "code": "C25",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": ["onkologie", "trávicí systém", "early-onset", "genetika"],
        "trend_context": "U mladších pacientů hraje silnější roli dědičná složka (rodinná anamnéza, mutace v genech BRCA2 a dalších). Vývoj odráží i lepší záchyt díky zobrazovacím metodám u rizikových pacientů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66000004","66005009","66010014","66015019","66020024","66025029","66030034","66035039","66040044","66045049"],
    },
    "slinivka_starsi_incidence": {
        "label": "Rakovina slinivky břišní u starších dospělých — incidence",
        "human_name": "Rakovina slinivky břišní u starších dospělých (50+ let)",
        "description": "Zhoubný nádor slinivky břišní u pacientů ve věku 50 a více let. Drtivá většina případů spadá do této věkové skupiny.",
        "code": "C25",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": ["onkologie", "trávicí systém", "stárnutí populace", "obezita"],
        "trend_context": "Vývoj odráží stárnutí populace a vyšší výskyt obezity a cukrovky druhého typu. Záchyt zůstává obtížný kvůli skryté poloze slinivky a nespecifickým prvním příznakům.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66050054","66055059","66060064","66065069","66070074","66075079","66080084","66085999"],
    },
    "mozek_mladi_incidence": {
        "label": "Zhoubný nádor mozku u mladších dospělých — incidence",
        "human_name": "Zhoubný nádor mozku u mladších dospělých (do 49 let)",
        "description": "Zhoubný nádor mozku u pacientů mladších 50 let. Mladší pacienti s mozkovým nádorem mívají jiné histologické subtypy než starší — častější jsou například gliomy nízkého stupně malignity.",
        "code": "C71",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": ["onkologie", "neurologie", "early-onset", "kvalita života"],
        "trend_context": "Vývoj u mladších pacientů odráží lepší zobrazovací metody (magnetická rezonance) — víc nádorů se najde a popíše. Mladí pacienti mívají často gliomy nízkého stupně, kde moderní chirurgie a sledování umožňují dlouhodobou kontrolu nad nemocí.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66000004","66005009","66010014","66015019","66020024","66025029","66030034","66035039","66040044","66045049"],
    },
    "mozek_starsi_incidence": {
        "label": "Zhoubný nádor mozku u starších dospělých — incidence",
        "human_name": "Zhoubný nádor mozku u starších dospělých (50+ let)",
        "description": "Zhoubný nádor mozku u pacientů ve věku 50 a více let. U starších pacientů dominují agresivnější subtypy, zejména glioblastom — onkologicky jeden z nejhůře léčitelných nádorů.",
        "code": "C71",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": ["onkologie", "neurologie", "glioblastom", "stárnutí populace"],
        "trend_context": "Vývoj odráží stárnutí populace a lepší záchyt magnetickou rezonancí. U starších pacientů dominují gliomy vysokého stupně (glioblastom), kde prognóza zůstává navzdory pokroku v léčbě vážná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C71",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66050054","66055059","66060064","66065069","66070074","66075079","66080084","66085999"],
    },
    "jicen_mladi_incidence": {
        "label": "Rakovina jícnu u mladších dospělých — incidence",
        "human_name": "Rakovina jícnu u mladších dospělých (do 49 let)",
        "description": "Zhoubný nádor jícnu u pacientů mladších 50 let. U mladších pacientů je rakovina jícnu vzácnější — souvisí spíše s genetickou predispozicí nebo dlouhodobým refluxem (pálení žáhy).",
        "code": "C15",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (do 49 let)",
        "relevant_for": ["onkologie", "trávicí systém", "early-onset", "reflux"],
        "trend_context": "U mladších pacientů narůstá podíl adenokarcinomu jícnu — souvisí s nárůstem obezity, refluxu žaludečních šťáv a Barrettova jícnu jako přednádorové změny.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C15",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66000004","66005009","66010014","66015019","66020024","66025029","66030034","66035039","66040044","66045049"],
    },
    "jicen_starsi_incidence": {
        "label": "Rakovina jícnu u starších dospělých — incidence",
        "human_name": "Rakovina jícnu u starších dospělých (50+ let)",
        "description": "Zhoubný nádor jícnu u pacientů ve věku 50 a více let. Drtivá většina případů spadá do této věkové skupiny a klasicky souvisí s kouřením a konzumací alkoholu.",
        "code": "C15",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (50+ let)",
        "relevant_for": ["onkologie", "trávicí systém", "kouření", "alkohol"],
        "trend_context": "U starších pacientů převažuje klasický spinocelulární karcinom jícnu — silně vázaný na kouření a alkohol. Vývoj odráží stárnutí populace a dlouhodobé vzorce těchto rizikových faktorů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C15",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66050054","66055059","66060064","66065069","66070074","66075079","66080084","66085999"],
    },
    "stitna_zlaza_male_deti_incidence": {
        "label": "Rakovina štítné žlázy u malých dětí — incidence",
        "human_name": "Rakovina štítné žlázy u malých dětí (do 14 let)",
        "description": "Zhoubný nádor štítné žlázy u dětí mladších 15 let. Doplněk k pediatrickému datasetu 0-19 — užší věkový rozsah zachycuje skutečně dětské pacienty bez dospívajících.",
        "code": "C73",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (0-14 let)",
        "relevant_for": ["onkologie", "dětská onkologie", "vzácná onemocnění", "hormonální systém"],
        "trend_context": "U malých dětí je rakovina štítné žlázy mimořádně vzácná — počty se počítají v jednotkách případů ročně. Případná kolísání odpovídají statistickému šumu vzácných onemocnění, ne skutečným změnám rizika.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "rok_dg",
        "age_col": "vek_kategorie_kod_dg",
        "age_codes": ["66000004","66005009","66010014"],
    },
    # === NOR 1770 — Pohlavní splity ===
    # ÚZIS kód: pohlavi=1 muž, pohlavi=2 žena.
    "plice_muzi_incidence": {
        "label": "Rakovina plic u mužů — incidence",
        "human_name": "Rakovina plic u mužů",
        "description": "Zhoubný nádor plicní tkáně u mužů. Mužská populace má dlouhodobě vyšší výskyt rakoviny plic kvůli historicky vyšší míře kouření.",
        "code": "C34",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (muži)",
        "relevant_for": ["onkologie", "kouření", "mužské zdraví", "kvalita ovzduší"],
        "trend_context": "Vývoj u mužů odráží dlouhodobý pokles kouření, který začal v 80. letech minulého století. Mužská rakovina plic je v Česku dlouhodobě klesající příběh — patří mezi tiché úspěchy boje proti kouření.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "plice_zeny_incidence": {
        "label": "Rakovina plic u žen — incidence",
        "human_name": "Rakovina plic u žen",
        "description": "Zhoubný nádor plicní tkáně u žen. U žen výskyt dlouhodobě roste — ženy začaly kouřit hromadně později než muži a nyní do diagnostické věkové skupiny vstupují silnější ročníky kuřaček.",
        "code": "C34",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (ženy)",
        "relevant_for": ["onkologie", "kouření", "ženské zdraví", "životní prostředí"],
        "trend_context": "Vývoj u žen jde opačným směrem než u mužů. Ženy začaly kouřit hromadně až ve druhé polovině 20. století a důsledky se v incidenci rakoviny plic projevují s typickým zpožděním 20-30 let. U mladších žen narůstá podíl nekuřáček.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C34",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "kolorektum_muzi_incidence": {
        "label": "Rakovina tlustého střeva a konečníku u mužů — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku u mužů",
        "description": "Zhoubný nádor tlustého střeva a konečníku u mužů. Česká mužská populace patří dlouhodobě k nejvíce zatíženým na světě — kombinace stravy bohaté na červené maso, méně pohybu a vyšší konzumace alkoholu.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (muži)",
        "relevant_for": ["onkologie", "screening tlustého střeva", "mužské zdraví", "životní styl"],
        "trend_context": "U mužů byl historicky výskyt podstatně vyšší než u žen. Plošný screening zavedený od roku 2000 přispěl k poklesu, ale česká mužská populace zůstává globálně nadprůměrně postižená.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "kolorektum_zeny_incidence": {
        "label": "Rakovina tlustého střeva a konečníku u žen — incidence",
        "human_name": "Rakovina tlustého střeva a konečníku u žen",
        "description": "Zhoubný nádor tlustého střeva a konečníku u žen. U žen je výskyt nižší než u mužů, ale rovněž česká ženská populace patří mezi nejvíce postižené v Evropě.",
        "code": "C18–C20",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (ženy)",
        "relevant_for": ["onkologie", "screening tlustého střeva", "ženské zdraví", "životní styl"],
        "trend_context": "Plošný screening (od 2000 testem na skryté krvácení do stolice, od 2009 kolonoskopií) přispívá k poklesu výskytu. Účast žen na screeningu je v Česku obecně vyšší než účast mužů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": ["C18", "C19", "C20"],
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "zaludek_muzi_incidence": {
        "label": "Rakovina žaludku u mužů — incidence",
        "human_name": "Rakovina žaludku u mužů",
        "description": "Zhoubný nádor žaludeční sliznice u mužů. U mužů je výskyt přibližně dvojnásobný oproti ženám — souvisí s vyšší konzumací alkoholu, kouřením a častější infekcí Helicobacter pylori.",
        "code": "C16",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (muži)",
        "relevant_for": ["onkologie", "trávicí systém", "mužské zdraví", "životní styl"],
        "trend_context": "Vývoj u mužů kopíruje celkový pokles rakoviny žaludku — lepší kvalita stravy, čistá pitná voda a léčba bakterie Helicobacter pylori.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "zaludek_zeny_incidence": {
        "label": "Rakovina žaludku u žen — incidence",
        "human_name": "Rakovina žaludku u žen",
        "description": "Zhoubný nádor žaludeční sliznice u žen. U žen je výskyt nižší než u mužů, dlouhodobě dál klesá s lepší kvalitou stravy a vodě.",
        "code": "C16",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (ženy)",
        "relevant_for": ["onkologie", "trávicí systém", "ženské zdraví", "životní styl"],
        "trend_context": "Vývoj u žen kopíruje celkový pokles rakoviny žaludku.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "hrtan_muzi_incidence": {
        "label": "Rakovina hrtanu u mužů — incidence",
        "human_name": "Rakovina hrtanu u mužů",
        "description": "Zhoubný nádor hrtanu u mužů. Drtivou většinu pacientů s rakovinou hrtanu tvoří muži — souvisí s historicky vyšší mírou kouření a konzumace alkoholu.",
        "code": "C32",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (muži)",
        "relevant_for": ["onkologie", "kouření", "alkohol", "mužské zdraví"],
        "trend_context": "Vývoj u mužů odráží dlouhodobý pokles kouření a konzumace alkoholu — patří k tichým úspěchům prevence.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C32",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "hrtan_zeny_incidence": {
        "label": "Rakovina hrtanu u žen — incidence",
        "human_name": "Rakovina hrtanu u žen",
        "description": "Zhoubný nádor hrtanu u žen. U žen je výskyt řádově nižší než u mužů, dlouhodobě se ale s rozšířením kouření mezi ženami pomalu zvyšuje.",
        "code": "C32",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (ženy)",
        "relevant_for": ["onkologie", "kouření", "alkohol", "ženské zdraví"],
        "trend_context": "Vývoj u žen odráží zpožděnou expanzi kouření v ženské populaci — podobně jako u rakoviny plic.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C32",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "melanom_muzi_incidence": {
        "label": "Zhoubný melanom kůže u mužů — incidence",
        "human_name": "Zhoubný melanom kůže u mužů",
        "description": "Zhoubný nádor pigmentových buněk kůže u mužů. U mužů se melanom typicky objevuje na trupu (zádech, hrudníku) — místech, která hůře vidí sami při samovyšetření.",
        "code": "C43",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (muži)",
        "relevant_for": ["onkologie", "kůže", "ultrafialové záření", "mužské zdraví"],
        "trend_context": "Vývoj u mužů odráží kumulativní expozici ultrafialovému záření a změny v chování (slunění, dovolené v teplých zemích). Muži obvykle chodí k preventivnímu vyšetření kůže méně často než ženy.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "melanom_zeny_incidence": {
        "label": "Zhoubný melanom kůže u žen — incidence",
        "human_name": "Zhoubný melanom kůže u žen",
        "description": "Zhoubný nádor pigmentových buněk kůže u žen. U žen se melanom typicky objevuje na dolních končetinách. Ženy chodí na preventivní kožní vyšetření častěji než muži.",
        "code": "C43",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (ženy)",
        "relevant_for": ["onkologie", "kůže", "ultrafialové záření", "ženské zdraví"],
        "trend_context": "U žen výskyt roste — souvisí s expozicí ultrafialovému záření, používáním solárií zejména v mladších věkových skupinách a životním stylem. Ženy se ke kožnímu lékaři dostávají častěji než muži.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C43",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "mocovy_mechyr_muzi_incidence": {
        "label": "Rakovina močového měchýře u mužů — incidence",
        "human_name": "Rakovina močového měchýře u mužů",
        "description": "Zhoubný nádor sliznice močového měchýře u mužů. U mužů je výskyt přibližně třikrát vyšší než u žen — odraz historicky vyšší míry kouření a častější profesionální expozice barvivům v průmyslu.",
        "code": "C67",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (muži)",
        "relevant_for": ["onkologie", "močový systém", "kouření", "mužské zdraví"],
        "trend_context": "Vývoj u mužů odráží dlouhodobé vzorce kouření a profesionální expozici v lakařských, gumárenských a textilních provozech.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C67",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "1",
    },
    "mocovy_mechyr_zeny_incidence": {
        "label": "Rakovina močového měchýře u žen — incidence",
        "human_name": "Rakovina močového měchýře u žen",
        "description": "Zhoubný nádor sliznice močového měchýře u žen. U žen je výskyt řádově nižší než u mužů, ale dlouhodobě se zvyšuje s rozšířením kouření v ženské populaci.",
        "code": "C67",
        "metric": "incidence_rocni",
        "metric_label": "Roční počet nově diagnostikovaných případů (ženy)",
        "relevant_for": ["onkologie", "močový systém", "kouření", "ženské zdraví"],
        "trend_context": "Vývoj u žen odráží zpožděnou expanzi kouření v ženské populaci — podobně jako u rakoviny plic. U žen je nemoc často diagnostikována později kvůli záměně příznaků s močovou infekcí.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C67",
        "year_col": "rok_dg",
        "sex_col": "pohlavi",
        "sex_value": "2",
    },
    "slinivka_stadium_1_share": {
        "label": "Rakovina slinivky břišní — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny slinivky břišní v 1. stadiu",
        "description": "Procento pacientů s rakovinou slinivky břišní zachycenou v 1. stadiu. U slinivky je časný záchyt mimořádně obtížný — nemoc se obvykle projeví, až když je rozšířená.",
        "code": "C25",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": ["onkologie", "trávicí systém", "časný záchyt", "výzkum"],
        "trend_context": "Plošný screening rakoviny slinivky neexistuje. Časný záchyt obvykle závisí na náhodném nálezu (počítačová tomografie kvůli jinému důvodu) nebo na sledování rizikových pacientů s rodinnou anamnézou.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "slinivka_stadium_4_share": {
        "label": "Rakovina slinivky břišní — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny slinivky břišní ve 4. stadiu",
        "description": "Procento pacientů s rakovinou slinivky břišní zachycenou až ve 4. stadiu — pokročilá fáze s metastázami. Vysoký podíl pozdního záchytu je u slinivky dlouhodobě tragickou realitou.",
        "code": "C25",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": ["onkologie", "trávicí systém", "pozdní záchyt", "kvalita léčby"],
        "trend_context": "Většina pacientů přichází k diagnóze, až když je rakovina slinivky pokročilá. Modernizace léčby pomáhá zlepšovat prognózu, ale pětileté přežití zůstává tragicky nízké.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C25",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "jicen_stadium_1_share": {
        "label": "Rakovina jícnu — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny jícnu v 1. stadiu",
        "description": "Procento pacientů s rakovinou jícnu zachycenou v 1. stadiu. Časný záchyt je obtížný, protože první příznaky se objeví, až když je nádor pokročilý.",
        "code": "C15",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": ["onkologie", "trávicí systém", "kouření", "časný záchyt"],
        "trend_context": "U rizikových pacientů (chronický reflux, Barrettův jícen, dlouhodobí kuřáci) může pravidelné gastroskopické sledování zachytit přednádorové změny.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C15",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "jicen_stadium_4_share": {
        "label": "Rakovina jícnu — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny jícnu ve 4. stadiu",
        "description": "Procento pacientů s rakovinou jícnu zachycenou až ve 4. stadiu — pokročilá fáze s metastázami. Pozdní záchyt je u jícnu dlouhodobě obvyklý.",
        "code": "C15",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": ["onkologie", "trávicí systém", "pozdní záchyt", "kouření"],
        "trend_context": "Hlavní důvod vysoké úmrtnosti — drtivá většina pacientů přichází k diagnóze, až když je nádor neoperabilní.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C15",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "ledvina_stadium_1_share": {
        "label": "Rakovina ledviny — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny ledviny v 1. stadiu",
        "description": "Procento pacientů s rakovinou ledviny zachycenou v 1. stadiu — lokalizovaný nádor s vynikající prognózou. Pravidelná zobrazovací vyšetření (ultrazvuk, počítačová tomografie) zvyšují podíl náhodně objevených časných nádorů.",
        "code": "C64",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": ["onkologie", "močový systém", "časný záchyt", "kvalita léčby"],
        "trend_context": "Rakovina ledviny se často nachází náhodně při ultrazvukovém vyšetření z jiného důvodu. Časný záchyt umožňuje šetrnou chirurgickou léčbu (záchovná resekce) místo odstranění celé ledviny.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C64",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "ledvina_stadium_4_share": {
        "label": "Rakovina ledviny — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny ledviny ve 4. stadiu",
        "description": "Procento pacientů s rakovinou ledviny zachycenou až ve 4. stadiu — pokročilý nádor s metastázami. Nízké hodnoty jsou cílem.",
        "code": "C64",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": ["onkologie", "močový systém", "pozdní záchyt", "imunoterapie"],
        "trend_context": "U pokročilých nádorů ledviny dramaticky zlepšila prognózu cílená a imunoterapie. Dříve byla léčba metastatické rakoviny ledviny málo účinná.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C64",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "mocovy_mechyr_stadium_1_share": {
        "label": "Rakovina močového měchýře — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny močového měchýře v 1. stadiu",
        "description": "Procento pacientů s rakovinou močového měchýře zachycenou v 1. stadiu (povrchový nádor). Při včasném záchytu je prognóza dobrá, klíčové je sledování kvůli recidivám.",
        "code": "C67",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": ["onkologie", "močový systém", "časný záchyt", "kvalita léčby"],
        "trend_context": "Časný záchyt přes hematurii (krev v moči) je u rakoviny močového měchýře klíčový. Povrchové formy lze léčit transuretrálně (bez velké operace), invazivní formy vyžadují odstranění měchýře.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C67",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "mocovy_mechyr_stadium_4_share": {
        "label": "Rakovina močového měchýře — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny močového měchýře ve 4. stadiu",
        "description": "Procento pacientů s rakovinou močového měchýře zachycenou až ve 4. stadiu — pokročilý nádor s metastázami.",
        "code": "C67",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": ["onkologie", "močový systém", "pozdní záchyt", "kvalita léčby"],
        "trend_context": "U žen je často diagnóza opožděna kvůli záměně příznaků s močovou infekcí. Modernizace léčby (imunoterapie) zlepšuje prognózu i u pokročilých případů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C67",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "stitna_zlaza_stadium_1_share": {
        "label": "Rakovina štítné žlázy — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny štítné žlázy v 1. stadiu",
        "description": "Procento pacientů s rakovinou štítné žlázy zachycenou v 1. stadiu. U štítné žlázy je drtivá většina nádorů zachycena v časném stadiu díky ultrazvuku.",
        "code": "C73",
        "metric": "stadium_1_share",
        "metric_label": "Pacienti zachycení v 1. stadiu (%)",
        "relevant_for": ["onkologie", "hormonální systém", "časný záchyt", "ultrazvukový záchyt"],
        "trend_context": "Široké využití ultrazvuku posouvá záchyt do velmi časných stadií. U papilárního karcinomu (drtivá většina) je prognóza i u větších nádorů vynikající.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "stitna_zlaza_stadium_4_share": {
        "label": "Rakovina štítné žlázy — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny štítné žlázy ve 4. stadiu",
        "description": "Procento pacientů s rakovinou štítné žlázy zachycenou až ve 4. stadiu. U štítné žlázy je pozdní záchyt vzácný díky pomalému růstu a dostupnosti ultrazvuku.",
        "code": "C73",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": ["onkologie", "hormonální systém", "pozdní záchyt"],
        "trend_context": "U štítné žlázy je 4. stadium vzácné. Týká se převážně agresivnějších typů (anaplastický karcinom) nebo pacientů, kteří se k diagnóze dostali pozdě.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C73",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "vajecnik_stadium_1_share": {
        "label": "Rakovina vaječníku — záchyt v 1. stadiu",
        "human_name": "Záchyt rakoviny vaječníku v 1. stadiu",
        "description": "Procento pacientek s rakovinou vaječníku zachycenou v 1. stadiu. U vaječníku patří časný záchyt k nejobtížnějším onkologickým výzvám — nemoc se dlouho neprojevuje příznaky.",
        "code": "C56",
        "metric": "stadium_1_share",
        "metric_label": "Pacientky zachycené v 1. stadiu (%)",
        "relevant_for": ["onkologie", "ženské zdraví", "časný záchyt", "genetika"],
        "trend_context": "Časný záchyt rakoviny vaječníku zůstává obtížný — neexistuje plošný screening a první příznaky se objeví, až když je nemoc rozšířená. U nositelek mutace v genech BRCA1/BRCA2 se doporučuje preventivní operace.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C56",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["1"],
    },
    "vajecnik_stadium_4_share": {
        "label": "Rakovina vaječníku — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny vaječníku ve 4. stadiu",
        "description": "Procento pacientek s rakovinou vaječníku zachycenou až ve 4. stadiu — pokročilá fáze s metastázami. Vysoký podíl pozdního záchytu je u vaječníku dlouhodobou výzvou.",
        "code": "C56",
        "metric": "stadium_4_share",
        "metric_label": "Pacientky zachycené ve 4. stadiu (%)",
        "relevant_for": ["onkologie", "ženské zdraví", "pozdní záchyt", "kvalita léčby"],
        "trend_context": "Vysoký podíl pacientek s rakovinou vaječníku diagnostikovaných až ve 4. stadiu odráží absenci účinného screeningu a nespecifické první příznaky (nadýmání, zažívací potíže).",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C56",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
    "zaludek_stadium_4_share": {
        "label": "Rakovina žaludku — záchyt ve 4. stadiu",
        "human_name": "Záchyt rakoviny žaludku ve 4. stadiu",
        "description": "Procento pacientů s rakovinou žaludku zachycenou až ve 4. stadiu — pokročilý nádor s metastázami. Vysoký podíl pozdního záchytu je v Česku dlouhodobou výzvou.",
        "code": "C16",
        "metric": "stadium_4_share",
        "metric_label": "Pacienti zachycení ve 4. stadiu (%)",
        "relevant_for": [
            "onkologie",
            "trávicí systém",
            "pozdní záchyt",
            "metastázy",
        ],
        "trend_context": "Vysoký podíl pacientů s rakovinou žaludku diagnostikovaných až ve 4. stadiu odráží absenci plošného screeningu. Modernizace léčby pomáhá zlepšovat prognózu i u pokročilých případů.",
        "data_url": "https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv",
        "source_url": "https://www.nzip.cz/data/1770-novotvary-incidence-prevalence-regiony-otevrena-data",
        "aggregation": "stage_share",
        "diagnosis_col": "diagnoza_kod",
        "diagnosis_prefix": "C16",
        "year_col": "rok_dg",
        "stage_col": "stadium",
        "stage_values": ["4"],
    },
}


def download_csv_to_tempfile(url: str) -> Path | None:
    """Stáhne CSV ze zadané URL do dočasného souboru (streaming, ne do paměti).

    NOR CSV mívají 100+ MB, takže je stahujeme po blocích na disk.
    Vrací cestu k dočasnému souboru, nebo None při chybě.
    """
    try:
        print(f"  Stahuji {url} ...")
        response = requests.get(
            url,
            timeout=180,
            stream=True,
            headers={"User-Agent": "Omnimedia-NOR-Sync/1.0 (PR research)"},
        )
        response.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False
        )
        size = 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                tmp.write(chunk)
                size += len(chunk)
        tmp.close()
        print(f"  Staženo {size / 1024 / 1024:.1f} MB do {tmp.name}")
        return Path(tmp.name)
    except Exception as e:
        print(f"  CHYBA při stahování: {e}", file=sys.stderr)
        return None


def count_cases_by_year_multi(
    csv_path: Path, datasets: list[tuple[str, dict]]
) -> dict[str, list]:
    """Spočítá počet řádků podle roku pro víc datasetů v jednom průchodu CSV.

    `datasets` je list `(dataset_id, cfg)` dvojic, které **sdílejí stejný
    CSV** (stejný `data_url`). Pro každý dataset se sleduje vlastní counter
    podle jeho `diagnosis_prefix`. Vrací: dict `dataset_id → [{year, value}]`.

    Filtruje řádky kde hodnota v `diagnosis_col` začíná na některém z prefixů
    daného datasetu (např. "C50" zachytí "C50", "C50.0", "C50.1" …).
    `diagnosis_prefix` může být string nebo seznam stringů (multi-kód, např.
    kolorektum ["C18","C19","C20"]).

    Volitelně lze v `cfg` zadat `age_col` + `age_codes` (set/list kódů ÚZIS
    věkové kategorie, např. ["66000004", "66005009", "66010014", "66015019"]
    pro děti a dospívající 0–19 let). Pokud chybí, věk se nefiltruje.

    Předpoklad: všechny datasety v `datasets` mají stejný `diagnosis_col`
    a `year_col` (u NOR 1770 jsou všechny `diagnoza_kod` + `rok_dg`).
    Pokud se rozcházejí, funkce shodí výjimku.
    """
    if not datasets:
        return {}

    # Validace, že všechny sdílejí dx_col + yr_col (jinak by single-pass
    # nedával smysl — museli bychom CSV procházet vícekrát).
    dx_cols = {cfg["diagnosis_col"] for _, cfg in datasets}
    yr_cols = {cfg["year_col"] for _, cfg in datasets}
    if len(dx_cols) > 1 or len(yr_cols) > 1:
        raise ValueError(
            "Datasety sdílející data_url musí mít stejný diagnosis_col "
            f"a year_col. Nalezeno: dx_col={dx_cols}, yr_col={yr_cols}"
        )
    diagnosis_col = next(iter(dx_cols))
    year_col = next(iter(yr_cols))

    counts: dict[str, dict[int, int]] = {ds_id: {} for ds_id, _ in datasets}

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        dx_col = cols_lower.get(diagnosis_col.lower())
        yr_col = cols_lower.get(year_col.lower())

        if not dx_col or not yr_col:
            raise ValueError(
                f"CSV neobsahuje očekávané sloupce '{diagnosis_col}' / '{year_col}'. "
                f"Nalezené sloupce: {reader.fieldnames}"
            )

        # Předem zkompilovat per-dataset state:
        # (ds_id, prefixes_tuple, age_col_actual_or_None, age_codes_set_or_None,
        #  sex_col_actual_or_None, sex_value_or_None)
        per_ds: list[
            tuple[str, tuple, str | None, set[str] | None, str | None, str | None]
        ] = []
        for ds_id, cfg in datasets:
            p = cfg["diagnosis_prefix"]
            prefixes = (p,) if isinstance(p, str) else tuple(p)

            age_col_name = cfg.get("age_col")
            if age_col_name:
                age_col_actual = cols_lower.get(age_col_name.lower())
                if not age_col_actual:
                    raise ValueError(
                        f"CSV neobsahuje sloupec '{age_col_name}' "
                        f"pro dataset {ds_id}"
                    )
                age_codes = set(cfg["age_codes"])
            else:
                age_col_actual = None
                age_codes = None

            sex_col_name = cfg.get("sex_col")
            if sex_col_name:
                sex_col_actual = cols_lower.get(sex_col_name.lower())
                if not sex_col_actual:
                    raise ValueError(
                        f"CSV neobsahuje sloupec '{sex_col_name}' "
                        f"pro dataset {ds_id}"
                    )
                sex_value = str(cfg["sex_value"])
            else:
                sex_col_actual = None
                sex_value = None

            per_ds.append(
                (ds_id, prefixes, age_col_actual, age_codes, sex_col_actual, sex_value)
            )

        for row in reader:
            dx = (row.get(dx_col) or "").strip()
            if not dx:
                continue
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if not (1950 <= year <= 2030):
                continue

            for ds_id, prefixes, age_col_actual, age_codes, sex_col_actual, sex_value in per_ds:
                if not dx.startswith(prefixes):
                    continue
                if age_codes is not None:
                    age_val = (row.get(age_col_actual) or "").strip()
                    if age_val not in age_codes:
                        continue
                if sex_value is not None:
                    row_sex = (row.get(sex_col_actual) or "").strip()
                    if row_sex != sex_value:
                        continue
                counts[ds_id][year] = counts[ds_id].get(year, 0) + 1

    return {
        ds_id: [{"year": y, "value": d[y]} for y in sorted(d.keys())]
        for ds_id, d in counts.items()
    }


def compute_5year_survival_by_year_multi(
    csv_path: Path, datasets: list[tuple[str, dict]]
) -> dict[str, list]:
    """Spočítá 5-leté přežití per rok diagnózy pro víc datasetů (NOR 1772).

    Per dataset filtruje na `diagnosis_group` (číselný kód 1–29 v poli
    `diagnoza_skupina` — viz mapování v komentáři u datasetů). Vrací
    list `{year, value}` kde `value` = procento pacientů z toho roku,
    kteří přežili 5 a více let.

    Pole v NOR 1772:
    - `preziti = 1` znamená ZEMŘEL (ne přežil — pozor, název je matoucí)
    - `preziti = 0` znamená alive (k datu analýzy)
    - `doba_sledovani` = dny od dg do úmrtí (preziti=1) nebo do dat. analýzy (preziti=0)

    Klasifikace per pacient:
    - "zemřel do 5 let" = `preziti = 1` AND `doba_sledovani < 5*365`
    - "přežil 5+ let" = `doba_sledovani >= 5*365` (bez ohledu na finální stav)
    - "cenzurováno" = `preziti = 0` AND `doba_sledovani < 5*365` (alive, ale ne ještě 5 let — vyřadit)

    5y survival = přežil 5+ let / (přežil 5+ let + zemřel do 5 let).

    Filtruje na pacienty diagnostikované >= 5 let zpět (jinak neznáme stav
    v 5letém milníku). Roky s méně než 30 pacienty s jasným statusem
    vynechány (statistický šum).
    """
    if not datasets:
        return {}

    # Sjednocená validace: všechny datasety v group musí mít stejný
    # group_col (diagnoza_skupina) a year_col (rok_dg).
    group_cols = {cfg["group_col"] for _, cfg in datasets}
    yr_cols = {cfg["year_col"] for _, cfg in datasets}
    if len(group_cols) > 1 or len(yr_cols) > 1:
        raise ValueError(
            f"Datasety sdílející data_url musí mít stejný group_col a year_col. "
            f"Nalezeno: group_col={group_cols}, year_col={yr_cols}"
        )
    group_col = next(iter(group_cols))
    year_col = next(iter(yr_cols))

    # 5-letý milník v dnech (zaokrouhleno na 5×365=1825, ignoruje přestupné roky).
    THRESHOLD_DAYS = 5 * 365
    # Maximální rok diagnózy, pro který už máme aspoň 5letý milník.
    # Předpoklad: data jsou stažena z 2024 release → poslední celý 5letý
    # milník je 2018 (diagnostikováni 2018, milník v 2023).
    MAX_YEAR_WITH_5Y = 2017
    MIN_SAMPLE_PER_YEAR = 30

    # Per dataset, per year: count známých statusů (přežil + zemřel) a samostatně přežil.
    known: dict[str, dict[int, int]] = {ds_id: {} for ds_id, _ in datasets}
    survived: dict[str, dict[int, int]] = {ds_id: {} for ds_id, _ in datasets}

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        gr_col = cols_lower.get(group_col.lower())
        yr_col = cols_lower.get(year_col.lower())
        doba_col = cols_lower.get("doba_sledovani")
        prez_col = cols_lower.get("preziti")

        if not gr_col or not yr_col or not doba_col or not prez_col:
            raise ValueError(
                f"CSV neobsahuje očekávané sloupce. Nalezené: {reader.fieldnames}"
            )

        # Per-dataset filtr: group_value (string) + age filter (volitelně) + sex filter (volitelně).
        per_ds: list[tuple[str, str, str | None, set[str] | None, str | None, str | None]] = []
        for ds_id, cfg in datasets:
            group_value = str(cfg["diagnosis_group"])
            age_col_name = cfg.get("age_col")
            if age_col_name:
                age_col_actual = cols_lower.get(age_col_name.lower())
                age_codes = set(cfg["age_codes"])
            else:
                age_col_actual = None
                age_codes = None

            sex_col_name = cfg.get("sex_col")
            if sex_col_name:
                sex_col_actual = cols_lower.get(sex_col_name.lower())
                sex_value = str(cfg["sex_value"])
            else:
                sex_col_actual = None
                sex_value = None

            per_ds.append((ds_id, group_value, age_col_actual, age_codes, sex_col_actual, sex_value))

        for row in reader:
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if year > MAX_YEAR_WITH_5Y:
                continue
            if not (1990 <= year <= 2030):
                continue

            row_group = (row.get(gr_col) or "").strip()
            try:
                doba = int(row[doba_col])
                preziti = int(row[prez_col])
            except (ValueError, TypeError):
                continue

            # Klasifikace per řádek:
            # - "survived" = doba >= 1825 (sledován 5+ let, ať už pak zemřel nebo žije)
            # - "died_under_5y" = preziti=1 (zemřel) AND doba < 1825 (před 5letým milníkem)
            # - "censored" = preziti=0 (alive) AND doba < 1825 — neznáme 5letý stav, vyřadit
            if doba >= THRESHOLD_DAYS:
                status = "survived"
            elif preziti == 1:
                status = "died"
            else:
                status = "censored"
            if status == "censored":
                continue

            for ds_id, group_value, age_col_actual, age_codes, sex_col_actual, sex_value in per_ds:
                if row_group != group_value:
                    continue
                if age_codes is not None:
                    age_val = (row.get(age_col_actual) or "").strip()
                    if age_val not in age_codes:
                        continue
                if sex_value is not None:
                    row_sex = (row.get(sex_col_actual) or "").strip()
                    if row_sex != sex_value:
                        continue
                known[ds_id][year] = known[ds_id].get(year, 0) + 1
                if status == "survived":
                    survived[ds_id][year] = survived[ds_id].get(year, 0) + 1

    return {
        ds_id: [
            {
                "year": y,
                "value": round(100 * survived[ds_id].get(y, 0) / known[ds_id][y], 1),
            }
            for y in sorted(known[ds_id].keys())
            if known[ds_id][y] >= MIN_SAMPLE_PER_YEAR
        ]
        for ds_id, _ in datasets
    }


def compute_regional_snapshot_multi(
    csv_path: Path, datasets: list[tuple[str, dict]]
) -> dict[str, list]:
    """Snapshot incidence per kraj pro daný target_year.

    Per dataset filtruje na `diagnosis_prefix` (C-kód) + `year_col == target_year`.
    Group by `region_col` (kraj_kod). Vrací list `[{kraj_kod, kraj_nazev, value}]`.

    Mapování kraj_kod → kraj_nazev je napevno (NUTS-3 ČR).
    """
    if not datasets:
        return {}

    # NUTS-3 kraje ČR.
    KRAJE = {
        "CZ010": "Hlavní město Praha",
        "CZ020": "Středočeský",
        "CZ031": "Jihočeský",
        "CZ032": "Plzeňský",
        "CZ041": "Karlovarský",
        "CZ042": "Ústecký",
        "CZ051": "Liberecký",
        "CZ052": "Královéhradecký",
        "CZ053": "Pardubický",
        "CZ063": "Vysočina",
        "CZ064": "Jihomoravský",
        "CZ071": "Olomoucký",
        "CZ072": "Zlínský",
        "CZ080": "Moravskoslezský",
    }

    # Validace shared sloupců.
    dx_cols = {cfg["diagnosis_col"] for _, cfg in datasets}
    yr_cols = {cfg["year_col"] for _, cfg in datasets}
    region_cols = {cfg["region_col"] for _, cfg in datasets}
    target_years = {cfg["target_year"] for _, cfg in datasets}
    if len(dx_cols) > 1 or len(yr_cols) > 1 or len(region_cols) > 1 or len(target_years) > 1:
        raise ValueError(
            f"Datasety regional_snapshot sdílející data_url musí mít stejné sloupce. "
            f"Nalezeno: dx={dx_cols}, yr={yr_cols}, region={region_cols}, target_year={target_years}"
        )
    diagnosis_col = next(iter(dx_cols))
    year_col = next(iter(yr_cols))
    region_col = next(iter(region_cols))
    target_year = next(iter(target_years))

    counts: dict[str, dict[str, int]] = {ds_id: {} for ds_id, _ in datasets}

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        dx_col = cols_lower.get(diagnosis_col.lower())
        yr_col = cols_lower.get(year_col.lower())
        rg_col = cols_lower.get(region_col.lower())

        if not dx_col or not yr_col or not rg_col:
            raise ValueError(
                f"CSV neobsahuje očekávané sloupce. Nalezené: {reader.fieldnames}"
            )

        per_ds: list[tuple[str, tuple]] = []
        for ds_id, cfg in datasets:
            p = cfg["diagnosis_prefix"]
            prefixes = (p,) if isinstance(p, str) else tuple(p)
            per_ds.append((ds_id, prefixes))

        for row in reader:
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if year != target_year:
                continue
            dx = (row.get(dx_col) or "").strip()
            if not dx:
                continue
            region = (row.get(rg_col) or "").strip()
            if region not in KRAJE:
                continue

            for ds_id, prefixes in per_ds:
                if dx.startswith(prefixes):
                    counts[ds_id][region] = counts[ds_id].get(region, 0) + 1

    return {
        ds_id: [
            {"kraj_kod": k, "kraj_nazev": KRAJE[k], "value": counts[ds_id].get(k, 0)}
            for k in sorted(KRAJE.keys())
        ]
        for ds_id, _ in datasets
    }


def compute_stage_share_by_year_multi(
    csv_path: Path, datasets: list[tuple[str, dict]]
) -> dict[str, list]:
    """Spočítá podíl daného stadia záchytu per rok dg pro víc datasetů.

    Per dataset filtruje na `diagnosis_prefix` (C-kód) a počítá procento
    pacientů s `stadium` v `stage_values` (list např. ["1"] pro stadium 1)
    z těch s **známým stadiem** (1-4). Hodnoty 'X' (neznámé) a 'Y'
    (neaplikovatelné) se vyřazují, aby čísla byla srovnatelná v čase.

    Vrací list `{year, value}` kde value = procento.
    Roky s méně než 30 pacienty s jasným stadiem vynechány (šum).
    """
    if not datasets:
        return {}

    # Validace shared sloupců.
    dx_cols = {cfg["diagnosis_col"] for _, cfg in datasets}
    yr_cols = {cfg["year_col"] for _, cfg in datasets}
    stage_cols = {cfg["stage_col"] for _, cfg in datasets}
    if len(dx_cols) > 1 or len(yr_cols) > 1 or len(stage_cols) > 1:
        raise ValueError(
            f"Datasety stage_share sdílející data_url musí mít stejné sloupce. "
            f"Nalezeno: dx={dx_cols}, yr={yr_cols}, stage={stage_cols}"
        )
    diagnosis_col = next(iter(dx_cols))
    year_col = next(iter(yr_cols))
    stage_col = next(iter(stage_cols))

    KNOWN_STAGES = {"1", "2", "3", "4"}
    MIN_SAMPLE_PER_YEAR = 30

    known: dict[str, dict[int, int]] = {ds_id: {} for ds_id, _ in datasets}
    matching: dict[str, dict[int, int]] = {ds_id: {} for ds_id, _ in datasets}

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV nemá hlavičku")

        cols_lower = {c.lower(): c for c in reader.fieldnames}
        dx_col = cols_lower.get(diagnosis_col.lower())
        yr_col = cols_lower.get(year_col.lower())
        st_col = cols_lower.get(stage_col.lower())

        if not dx_col or not yr_col or not st_col:
            raise ValueError(
                f"CSV neobsahuje očekávané sloupce. Nalezené: {reader.fieldnames}"
            )

        # Per dataset: prefix tuple + stage_values set
        per_ds: list[tuple[str, tuple, set[str]]] = []
        for ds_id, cfg in datasets:
            p = cfg["diagnosis_prefix"]
            prefixes = (p,) if isinstance(p, str) else tuple(p)
            stage_values = set(cfg["stage_values"])
            per_ds.append((ds_id, prefixes, stage_values))

        for row in reader:
            dx = (row.get(dx_col) or "").strip()
            if not dx:
                continue
            try:
                year = int(row[yr_col])
            except (ValueError, TypeError):
                continue
            if not (1950 <= year <= 2030):
                continue
            stage = (row.get(st_col) or "").strip()
            if stage not in KNOWN_STAGES:
                continue

            for ds_id, prefixes, stage_values in per_ds:
                if not dx.startswith(prefixes):
                    continue
                known[ds_id][year] = known[ds_id].get(year, 0) + 1
                if stage in stage_values:
                    matching[ds_id][year] = matching[ds_id].get(year, 0) + 1

    return {
        ds_id: [
            {
                "year": y,
                "value": round(100 * matching[ds_id].get(y, 0) / known[ds_id][y], 1),
            }
            for y in sorted(known[ds_id].keys())
            if known[ds_id][y] >= MIN_SAMPLE_PER_YEAR
        ]
        for ds_id, _ in datasets
    }


def compute_meta(series: list, cfg: dict | None = None) -> dict:
    """Spočítá meta-informace pro frontend (trend, delta, peak).

    Pro survival_5y (procenta) používá absolutní rozdíl v procentních
    bodech místo relativního procenta — relativní změna mezi 74 a 80
    je matoucí ("+8 %"), absolutní +6 p.b. je jasnější.

    Delta se počítá z 3letých klouzavých průměrů prvních a posledních
    3 let — stabilizuje výsledek u vzácných dg, kde single-year může
    být silně ovlivněný šumem (např. 1 → 26 případů by jinak dalo
    +2500 %, s rolling průměrem realistických ~+700 %).

    U sérií kratších než 6 bodů se používá single-year hodnota
    (nedostatek dat pro rolling průměr).
    """
    if not series or len(series) < 2:
        return {"trend": "unknown", "delta": 0, "peakYear": None}

    aggregation = cfg.get("aggregation", "count") if cfg else "count"

    # 3letý klouzavý průměr na začátku a na konci série, pokud máme dost dat.
    if len(series) >= 6:
        first_value = sum(p["value"] for p in series[:3]) / 3
        last_value = sum(p["value"] for p in series[-3:]) / 3
    else:
        first_value = series[0]["value"]
        last_value = series[-1]["value"]

    if aggregation in ("survival_5y", "stage_share"):
        # Procentní data — delta v procentních bodech (např. z 60% na 80% = +20).
        delta = round(last_value - first_value, 1)
        if delta > 5:
            trend = "up"
        elif delta < -5:
            trend = "down"
        else:
            trend = "plateau"
    else:
        # Relativní změna v procentech (např. z 1000 na 1500 = +50%)
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


def write_dataset_json(dataset_id: str, cfg: dict, series: list) -> str:
    """Vyrobí výstupní JSON pro jeden dataset a uloží ho. Vrací 'ok' / 'failed'."""
    if not series:
        print(
            f"  [{dataset_id}] CHYBA: žádná data po filtru",
            file=sys.stderr,
        )
        return "failed"

    aggregation = cfg.get("aggregation", "count")

    out = {
        "id": dataset_id,
        "label": cfg["label"],
        "human_name": cfg["human_name"],
        "description": cfg["description"],
        "code": cfg["code"],
        "source": "Národní onkologický registr (ÚZIS)",
        "source_type": "national",
        "metric": cfg["metric"],
        "metric_label": cfg["metric_label"],
        "relevant_for": cfg["relevant_for"],
        "trend_context": cfg["trend_context"],
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "data": series,
        "data_url": cfg["data_url"],
        "source_url": cfg["source_url"],
    }

    if aggregation == "regional_snapshot":
        # Snapshot pro jeden rok, data je [{kraj_kod, kraj_nazev, value}].
        target_year = cfg["target_year"]
        peak = max(series, key=lambda r: r["value"])
        out["source_type"] = "regional_snapshot"
        out["coverage"] = str(target_year)
        out["snapshot_year"] = target_year
        out["trend"] = "snapshot"
        out["delta"] = 0
        out["peakRegion"] = peak["kraj_nazev"]
        log_msg = f"snapshot {target_year}, peak {peak['kraj_nazev']} ({peak['value']})"
    else:
        meta = compute_meta(series, cfg)
        out["coverage"] = f"{series[0]['year']}–{series[-1]['year']}"
        out["trend"] = meta["trend"]
        out["delta"] = meta["delta"]
        out["peakYear"] = meta["peakYear"]
        log_msg = f"{len(series)} let dat, delta {meta['delta']:+}%"

    out_path = OUT_DIR / f"{dataset_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(
        f"  [{dataset_id}] OK: {log_msg}, "
        f"uloženo do {out_path.relative_to(OUT_DIR.parent.parent)}"
    )
    return "ok"


def sync_group(url: str, datasets: list[tuple[str, dict]]) -> dict[str, str]:
    """Stáhne jeden CSV a naparsuje všechny datasety, které ho sdílí.

    Datasety se uvnitř skupiny dál pod-seskupí podle `aggregation` v cfg,
    aby šly mít smíšené typy (count + stage_share, atd.) v jednom CSV.
    Pro každou aggregaci se volá příslušná funkce nad stejným staženým
    souborem (každá funkce dělá vlastní průchod CSV).

    Aggregace:
    - "count" (default) — počet řádků odpovídajících filtru (incidence/mortalita)
    - "survival_5y" — procento přeživších 5+ let
    - "stage_share" — procento pacientů v daném stadiu záchytu

    Vrací: dict `dataset_id → "ok" | "failed"`. Pokud selže stažení,
    všechny datasety v skupině dostanou "failed".
    """
    ds_ids = [ds_id for ds_id, _ in datasets]
    print(f"\n=== Skupina ({len(datasets)} dg): {', '.join(ds_ids)} ===")

    csv_path = download_csv_to_tempfile(url)
    if csv_path is None:
        return {ds_id: "failed" for ds_id in ds_ids}

    # Pod-seskupit podle aggregation type (každý type = jeden průchod CSV).
    by_agg: dict[str, list[tuple[str, dict]]] = {}
    for ds_id, cfg in datasets:
        agg = cfg.get("aggregation", "count")
        by_agg.setdefault(agg, []).append((ds_id, cfg))

    all_series: dict[str, list] = {}
    try:
        for agg, ds_subset in by_agg.items():
            if agg == "survival_5y":
                series = compute_5year_survival_by_year_multi(csv_path, ds_subset)
            elif agg == "stage_share":
                series = compute_stage_share_by_year_multi(csv_path, ds_subset)
            elif agg == "regional_snapshot":
                series = compute_regional_snapshot_multi(csv_path, ds_subset)
            else:
                series = count_cases_by_year_multi(csv_path, ds_subset)
            all_series.update(series)
    except Exception as e:
        print(f"  CHYBA při parsování CSV: {e}", file=sys.stderr)
        return {ds_id: "failed" for ds_id in ds_ids}
    finally:
        try:
            csv_path.unlink()
        except OSError:
            pass

    results = {}
    for ds_id, cfg in datasets:
        series = all_series.get(ds_id, [])
        results[ds_id] = write_dataset_json(ds_id, cfg, series)
    return results


def main():
    print(f"NOR sync — start v {datetime.now().isoformat()}")

    # Seskupit datasety podle data_url (cache stahování — 1 CSV = 1 download).
    groups: dict[str, list[tuple[str, dict]]] = {}
    for ds_id, cfg in DATASETS.items():
        groups.setdefault(cfg["data_url"], []).append((ds_id, cfg))

    print(
        f"  {len(DATASETS)} datasetů v {len(groups)} skupinách "
        f"(={len(groups)} stažení CSV)"
    )

    results: dict[str, str] = {}
    for url, datasets in groups.items():
        results.update(sync_group(url, datasets))

    ok = [k for k, v in results.items() if v == "ok"]
    failed = [k for k, v in results.items() if v == "failed"]

    print("\n=== NOR sync — hotovo ===")
    print(f"  OK ({len(ok)}): {', '.join(ok) if ok else '—'}")
    print(f"  Selhalo ({len(failed)}): {', '.join(failed) if failed else '—'}")

    if not ok:
        print("\nŽÁDNÝ DATASET NEPROŠEL. Pravděpodobné příčiny:", file=sys.stderr)
        print("  1. data.mzcr.cz přejmenoval CSV (zkontroluj data_url v DATASETS)", file=sys.stderr)
        print("  2. data.mzcr.cz server je dočasně nedostupný", file=sys.stderr)
        print("  3. Změnila se struktura CSV (sloupce diagnoza_kod / rok_dg)", file=sys.stderr)
        sys.exit(1)

    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
