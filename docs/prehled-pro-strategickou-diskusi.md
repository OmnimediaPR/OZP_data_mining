# Datový brief — přehled nástroje pro strategickou diskusi

> Tento dokument je sebevysvětlující shrnutí interního nástroje „Datový brief" agentury Omnimedia PR. Slouží jako podklad pro samostatnou diskusi (např. v Claude chatu) o dalším rozvoji, monetizaci a přenosu na jiné obory a datové zdroje. Čtenář nemá přístup ke kódu ani k repozitáři — vše podstatné je popsáno zde.

---

## 1. Co jsme vytvořili

**Datový brief** je interní webový nástroj, který z **veřejných českých zdravotnických dat** vyrábí **datový podklad pro PR** — strukturovaná zjištění, doporučené komunikační úhly a exportovatelný onepager (.docx). Cílem není psát tiskové zprávy, ale dát PR profesionálovi **ověřená čísla z reálných zdrojů** místo intuice, aby na nich postavil sdělení.

Klíčová myšlenka: zdravotnická open data jsou veřejná, ale prakticky **nepoužitelná pro netechnického člověka** — jsou roztroušená v desítkách registrů, v surových CSV o milionech řádků, s kódovanými číselníky. Nástroj tuhle propast překlenuje: data jednorázově předzpracuje do lehkých, prohledávatelných struktur a nad nimi pustí jazykový model, který z nich vytáhne zjištění a pohlídá, co data naopak **nedovolují** tvrdit.

Aktuální stav: ~**125 datasetů** napříč onkologií, kardiovaskulárními nemocemi, hospitalizacemi, úmrtností, reprodukcí a novorozenci, prevencí, očkováním, lázněmi, léky a dalšími oblastmi. Nasazeno na webu, používá se.

---

## 2. Komu to slouží

- **Primárně:** PR a komunikační profesionálové (netechnickí) v agentuře, kteří dělají kampaně pro klienty ze zdravotnictví a farmacie.
- **Jejich problém:** potřebují rychle, věrohodně a doložitelně podložit sdělení čísly — „rakovina tlustého střeva se posouvá k mladším", „čekání na kolonoskopii vzrostlo o 38 %" — a unést, když je novinář nebo klient požádá o zdroj.
- **Dělba práce:** nástroj udělá analýzu dat a navrhne úhly; **text tiskovky napíše člověk sám.** Nástroj záměrně negeneruje hotové copy — drží roli „datového analytika", ne „copywritera".

Sekundárně je tu zřejmý přesah na **datovou žurnalistiku, public affairs, think-tanky a komunikaci veřejného sektoru** — kdokoli, kdo potřebuje rychle a obhajitelně argumentovat veřejnými daty.

---

## 3. Jak to funguje (uživatelský tok + architektura)

**Uživatelský tok:**
1. Uživatel zadá **téma briefu** (volný text).
2. Jazykový model projde katalog datasetů a **vybere relevantní** (levný rychlý model, katalog je v prompt cache).
3. Uživatel výběr **upraví** (odškrtá/přidá karty).
4. Model **zanalyzuje** vybraná data a vrátí strukturovaný výstup:
   - *klíčová zjištění* (číslo + co + proč je to relevantní k tématu),
   - *meta-pattern* (co data dohromady říkají),
   - *doporučené úhly* (pozorování + riziko v tezi),
   - *co data NEPODPORUJÍ* (explicitní brzda proti přestřelení).
5. **Každá teze (zjištění i úhel) nese odkaz na konkrétní datový zdroj**, aby si ji šlo ověřit — na obrazovce klikací, v exportu jako URL.
6. Export **.docx onepageru** připraveného k použití.

**Architektura (záměrně minimalistická):**
- **Frontend:** React + Vite, hostovaný na **GitHub Pages**. **Žádný backend, žádná databáze.**
- **Jazykový model:** Anthropic API se volá **přímo z prohlížeče**, klíč si zadává každý uživatel sám (uloží se jen lokálně).
- **Data:** statický `catalog.json` (metadata všech datasetů) + předpečené datové soubory. Prohlížeč stahuje jen to, co uživatel vybere.
- **Aktualizace:** předzpracování dat běží mimo prohlížeč (skripty), výsledek se commitne do repa a automaticky nasadí.

Tahle „bezserverová" volba má důsledek pro byznys: provoz je skoro zdarma, ale veškerá inteligence je v **kurátorství dat** a v **promptu/guardrailech**, ne v infrastruktuře.

---

## 4. Jak pracuje se zdrojovými daty (jádro hodnoty)

Zdroje jsou **veřejná otevřená data** — především **ÚZIS / NZIS / NZIP** (národní zdravotnické registry: reprodukce, onkologie, hospitalizace, úmrtnost, hrazené služby, screeningové programy) a pro mezinárodní srovnání **Eurostat a OECD**.

Surová data jsou ale nepřívětivá: jednotlivé registry mají miliony až **stovky milionů řádků** (jeden zpracovaný soubor měl 4,5 GB), hodnoty jsou kódované (věk, kraj, diagnóza, pásma hmotnosti…) a srozumitelné jen přes oficiální metodické číselníky. Nástroj to řeší **jednorázovým předzpracováním do čtyř lehkých tvarů**, které prohlížeč unese:

1. **Plché časové řady** — roční hodnota v čase (např. počet úmrtí).
2. **Rozpadové „kostky"** — řídké vícerozměrné agregace (rok × diagnóza × věk × pohlaví × kraj × …). Z milionů mikrozáznamů se *streamově* napeče malá kostka (stovky KB), kterou prohlížeč **řeže lokálně** bez dalšího stahování. Engine je **konfigurační** (metriky počet/součet/„široký" formát, dekodéry věku, mapování diagnóz na kapitoly MKN, převod okresu na kraj) a umí i **automatický sken anomálií** (trendy, posun k mladším, pozdní záchyt) — ty slouží jako *tipy na úhly* pro PR.
3. **Snímkové karty** — popisná čísla bez časové řady (např. souhrn pandemie).
4. **Krajské heatmapy** — matice kraj × rok (např. čekací doby), když data nejdou agregovat jako počty.

Tři principy, které dělají výstup důvěryhodným (a které jsou samy o sobě hodnotou):
- **Číselníky z oficiálních metodik, ne odhadem** — pásma hmotnosti, kategorie přijetí apod. se dohledávají v metodických PDF ÚZIS.
- **Popisná data vs. trendy** — kde trend klame (např. změny kódování, stárnutí populace, úhradová politika), sken anomálií se vypíná a dataset slouží jen popisně.
- **Poctivost o limitech** — explicitní sekce „co data nepodporují", upozornění na vyřazené diagnózy kvůli GDPR, na to že jde o počty a ne podíly, atd. Plus **odkaz na zdroj u každé teze**.

> **Stručně:** skutečné jádro není web ani prompt, ale **pipeline „otevřená data → kurátorovaný katalog → předagregované kostky s ověřenými číselníky → AI analýza s doložitelným zdrojem → exportovatelný brief"** a **redakční disciplína**, která brání tomu, aby model přestřeloval.

---

## 5. Co je na tom přenositelné (a kde je obrana)

**Doménově nezávislé jádro (přenese se jinam beze změny principu):**
- Katalogový model + čtyři datové tvary (řada / kostka / snímek / heatmapa).
- Konfigurační „bake" engine na převod velkých mikrodat do lehkých agregací.
- AI vrstva, která z dat dělá zjištění + úhly + brzdy a **vždy připojí zdroj**.
- Export do podkladu, který cílový profesionál reálně použije.

**Co je specifické pro ČR-zdravotnictví (a tvoří náskok / obranu):**
- Znalost konkrétních registrů, jejich číselníků a metodik.
- Kurátorství: které datasety mají smysl, kde data klamou, jak je správně agregovat.
- Redakční guardraily proti halucinaci — důvěra je produkt, ne vedlejšák.

Obrana tedy **není v technologii** (tu lze replikovat), ale v **kurátorství + důvěryhodnosti + doménové hloubce**. To je důležité pro úvahy o monetizaci.

---

## 6. Otázky k diskusi

Tohle je to, o čem chci přemýšlet. Body níže jsou **startovní hypotézy, ne závěry** — čekám oponenturu, rozšíření i úplně jiné směry.

### 6.1 Další využití (stejná doména, širší záběr)
- Datová žurnalistika (rychlé, ozdrojované podklady pro redakce).
- Public affairs / advocacy (NGO, pacientské organizace, odborné společnosti — argumentace daty).
- Komunikace nemocnic, krajů, pojišťoven, ministerstva.
- Interní reporting farma/medtech firem (market access, evidence pro jednání).
- „Always-on" newsroom: automatické hlášení anomálií v nových datech jako námět na obsah.

### 6.2 Potenciální monetizace
- SaaS pro PR/komunikační agentury (per-seat / per-brief).
- Vertikální edice (zdravotnictví, finance, vzdělávání…) jako samostatné produkty.
- White-label pro větší agentury či vydavatelství.
- **Data-as-a-service:** prodej samotných kurátorovaných kostek/datasetů (i bez AI vrstvy).
- Prémiová „ověřitelnost / audit trail" vrstva pro regulovaná odvětví.
- Otázky k probrání: kdo přesně platí a za co (čas? důvěra? rychlost?), jak velký je trh, jaká je ochota platit u agentur vs. in-house, kde je cenová kotva.

### 6.3 Aplikace na jiné obory
- Vzdělávání, trh práce, ekonomika (ČSÚ), životní prostředí, doprava, kriminalita, energetika, zemědělství, bydlení.
- Kritérium vhodnosti oboru: existují **veřejné registry/řady**, je tam **komunikační/advokační poptávka**, a **jde pochybit** (tj. ověřitelnost má cenu).
- Otázka: je lepší jít do hloubky v jednom oboru (moat = doménová znalost), nebo do šířky jako horizontální platforma?

### 6.4 Jiné datové zdroje
- ČSÚ, plný Eurostat, OECD, otevřená data ministerstev, [data.gov.cz], evropský portál otevřených dat, municipální data, případně komerční/placené zdroje.
- Mezinárodní rozměr: stejný princip pro jinou zemi = nová znalost registrů a číselníků (náklad i příležitost).
- Otázka: kde je hranice mezi „čistě veřejná data" a „přidaná hodnota přístupu k placeným/těžko dostupným datům" jako součást nabídky?

### 6.5 Rizika a otevřené otázky
- Replikovatelnost technologie → obrana stojí na kurátorství a důvěře.
- Náklad na údržbu číselníků a metodik při škálování na víc oborů/zemí.
- Odpovědnost za správnost (PR výstup → veřejné tvrzení); jak silně garantovat.
- Závislost na kvalitě a dostupnosti veřejných dat (formáty se mění, registry mizí).

---

*Připraveno jako podklad k diskusi. Čísla a stav odpovídají době vzniku dokumentu; nástroj se vyvíjí.*
