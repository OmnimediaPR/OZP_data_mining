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
        # (ds_id, prefixes_tuple, age_col_actual_or_None, age_codes_set_or_None)
        per_ds: list[tuple[str, tuple, str | None, set[str] | None]] = []
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

            per_ds.append((ds_id, prefixes, age_col_actual, age_codes))

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

            for ds_id, prefixes, age_col_actual, age_codes in per_ds:
                if not dx.startswith(prefixes):
                    continue
                if age_codes is not None:
                    age_val = (row.get(age_col_actual) or "").strip()
                    if age_val not in age_codes:
                        continue
                counts[ds_id][year] = counts[ds_id].get(year, 0) + 1

    return {
        ds_id: [{"year": y, "value": d[y]} for y in sorted(d.keys())]
        for ds_id, d in counts.items()
    }


def compute_meta(series: list) -> dict:
    """Spočítá meta-informace pro frontend (trend, delta, peak)."""
    if not series or len(series) < 2:
        return {"trend": "unknown", "delta": 0, "peakYear": None}

    first = series[0]
    last = series[-1]
    if first["value"] == 0:
        delta_pct = 0
    else:
        delta_pct = round(((last["value"] - first["value"]) / first["value"]) * 100)

    peak = max(series, key=lambda r: r["value"])

    if delta_pct > 10:
        trend = "up"
    elif delta_pct < -10:
        trend = "down"
    else:
        trend = "plateau"

    return {"trend": trend, "delta": delta_pct, "peakYear": peak["year"]}


def write_dataset_json(dataset_id: str, cfg: dict, series: list) -> str:
    """Vyrobí výstupní JSON pro jeden dataset a uloží ho. Vrací 'ok' / 'failed'."""
    if not series:
        print(
            f"  [{dataset_id}] CHYBA: žádná data po filtru diagnózy",
            file=sys.stderr,
        )
        return "failed"

    meta = compute_meta(series)

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
        "coverage": f"{series[0]['year']}–{series[-1]['year']}",
        "trend": meta["trend"],
        "delta": meta["delta"],
        "peakYear": meta["peakYear"],
        "data": series,
        "data_url": cfg["data_url"],
        "source_url": cfg["source_url"],
    }

    out_path = OUT_DIR / f"{dataset_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(
        f"  [{dataset_id}] OK: {len(series)} let dat, delta {meta['delta']:+}%, "
        f"uloženo do {out_path.relative_to(OUT_DIR.parent.parent)}"
    )
    return "ok"


def sync_group(url: str, datasets: list[tuple[str, dict]]) -> dict[str, str]:
    """Stáhne jeden CSV a single-pass naparsuje všechny datasety, které ho sdílí.

    Vrací: dict `dataset_id → "ok" | "failed"`. Pokud selže stažení nebo
    parsování CSV, všechny datasety v skupině dostanou "failed".
    """
    ds_ids = [ds_id for ds_id, _ in datasets]
    print(f"\n=== Skupina ({len(datasets)} dg): {', '.join(ds_ids)} ===")

    csv_path = download_csv_to_tempfile(url)
    if csv_path is None:
        return {ds_id: "failed" for ds_id in ds_ids}

    try:
        series_by_id = count_cases_by_year_multi(csv_path, datasets)
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
        series = series_by_id.get(ds_id, [])
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
