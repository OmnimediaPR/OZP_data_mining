// Napeče "rozpadové kostky" z registrů NZIP/ÚZIS. Config-driven a OBECNÉ DIMENZE:
// každá kostka nese pole dims [{key,label,kind,values,primary?}] + řídké buňky
// [yearIdx, ...dimIdx, count] + sken anomálií. Frontend renderuje zužovátka dynamicky.
//
// kind: 'category' (values = pole stringů nebo {key,name}) | 'age' (values = počátky 5letých pásem).
// Jedna dim má primary:true (hlavní rozpad — nad ní běží sken anomálií).
//
// Spuštění:  node --max-old-space-size=4096 scripts/bake_cube.mjs
import { Readable } from 'node:stream';
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const Papa = require(process.cwd() + '/frontend/node_modules/papaparse/papaparse.js');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124';

// ---- sdílené číselníky ----
const NHL = { key: 'NHL', name: 'nehodgkinský lymfom' };
const DG_ONKO = {
  C15: { key: 'C15', name: 'zhoubný novotvar jícnu' }, C16: { key: 'C16', name: 'zhoubný novotvar žaludku' },
  C18: { key: 'C18', name: 'zhoubný novotvar tlustého střeva' }, C19: { key: 'C19', name: 'zhoubný novotvar rektosigmoideálního spojení' },
  C20: { key: 'C20', name: 'zhoubný novotvar konečníku' }, C22: { key: 'C22', name: 'zhoubný novotvar jater' },
  C25: { key: 'C25', name: 'zhoubný novotvar slinivky břišní' }, C32: { key: 'C32', name: 'zhoubný novotvar hrtanu' },
  C34: { key: 'C34', name: 'zhoubný novotvar průdušky a plíce' }, C43: { key: 'C43', name: 'zhoubný melanom kůže' },
  C44: { key: 'C44', name: 'jiný zhoubný novotvar kůže' }, C50: { key: 'C50', name: 'zhoubný novotvar prsu' },
  C53: { key: 'C53', name: 'zhoubný novotvar děložního hrdla' }, C54: { key: 'C54', name: 'zhoubný novotvar těla děložního' },
  C56: { key: 'C56', name: 'zhoubný novotvar vaječníku' }, C61: { key: 'C61', name: 'zhoubný novotvar předstojné žlázy' },
  C62: { key: 'C62', name: 'zhoubný novotvar varlete' }, C64: { key: 'C64', name: 'zhoubný novotvar ledviny' },
  C67: { key: 'C67', name: 'zhoubný novotvar močového měchýře' }, C71: { key: 'C71', name: 'zhoubný novotvar mozku' },
  C73: { key: 'C73', name: 'zhoubný novotvar štítné žlázy' }, C81: { key: 'C81', name: 'Hodgkinův lymfom' },
  C82: NHL, C83: NHL, C84: NHL, C85: NHL, C86: NHL,
  C90: { key: 'C90', name: 'mnohočetný myelom' }, C91: { key: 'C91', name: 'lymfatická leukémie' }, C92: { key: 'C92', name: 'myeloidní leukémie' },
};
const SEX = (v) => (v === '1' ? 'muž' : v === '2' ? 'žena' : null);
const SEX_MZ = (v) => (v === 'M' ? 'muž' : v === 'Z' ? 'žena' : null);

// MKN-10 kód (např. "I21") → název kapitoly. Pro seskupení diagnóz do velkých skupin.
function mknChapter(code) {
  const m = (code || '').toString().toUpperCase().match(/^([A-Z])(\d{2})/);
  if (!m) return null;
  const L = m[1], n = +m[2];
  switch (L) {
    case 'A': case 'B': return 'infekční a parazitární nemoci';
    case 'C': return 'novotvary';
    case 'D': return n <= 48 ? 'novotvary' : 'nemoci krve a poruchy imunity';
    case 'E': return 'nemoci endokrinní, výživy a látkové přeměny';
    case 'F': return 'duševní poruchy a poruchy chování';
    case 'G': return 'nemoci nervové soustavy';
    case 'H': return n <= 59 ? 'nemoci oka' : 'nemoci ucha';
    case 'I': return 'nemoci oběhové soustavy';
    case 'J': return 'nemoci dýchací soustavy';
    case 'K': return 'nemoci trávicí soustavy';
    case 'L': return 'nemoci kůže a podkoží';
    case 'M': return 'nemoci svalové a kosterní soustavy a pojiva';
    case 'N': return 'nemoci močové a pohlavní soustavy';
    case 'O': return 'těhotenství, porod a šestinedělí';
    case 'P': return 'stavy vzniklé v perinatálním období';
    case 'Q': return 'vrozené vady a chromozomální abnormality';
    case 'R': return 'příznaky a nálezy nezařazené jinde';
    case 'S': case 'T': return 'poranění, otravy a vnější následky';
    case 'V': case 'W': case 'X': case 'Y': return 'vnější příčiny nemocnosti a úmrtnosti';
    case 'Z': return 'preventivní kontakty se zdravotnictvím';
    case 'U': return 'kódy pro speciální účely (např. covid)';
    default: return null;
  }
}
const STAGE = (v) => { const s = (v || '').toString().replace(/"/g, '').trim(); return ['1', '2', '3', '4'].includes(s) ? ['', 'I', 'II', 'III', 'IV'][+s] : 'neuvedeno'; };
const nor5 = (code) => { const low = parseInt((code || '').toString().slice(2, 5), 10); return Number.isFinite(low) ? Math.floor(low / 5) * 5 : null; };
const ageLabel = (s) => (s >= 85 ? '85 a více' : `${s}–${s + 4}`);
const SEP = '';

// Vrátí funkci row → hodnota dimenze (nebo null = řádek zahodit).
function extractor(dim) {
  const col = dim.col;
  if (dim.kind === 'age') {
    if (dim.decode === 'nor5') return (r) => nor5(r[col]);
    if (dim.decode === 'range') return (r) => { const m = (r[col] || '').toString().match(/(\d+)/); return m ? parseInt(m[1], 10) : null; }; // "65-69"→65, "00-04"→0
    throw new Error(`neznámý decode věku: ${dim.decode}`);
  }
  if (dim.map === 'DG_ONKO') return (r) => { const m = DG_ONKO[(r[col] || '').toString().slice(0, 3)]; return m ? m.key : null; };
  if (dim.map === 'MKN_CHAPTER') return (r) => mknChapter(r[col]);
  if (dim.map === 'SEX') return (r) => SEX((r[col] || '').toString());
  if (dim.map === 'SEX_MZ') return (r) => SEX_MZ((r[col] || '').toString());
  if (dim.map === 'STAGE') return (r) => STAGE(r[col]);
  // plain category — hodnota přímo ze sloupce (volitelně očištěná o číselný prefix)
  return (r) => { let v = (r[col] ?? '').toString().trim(); if (dim.clean === 'stripNumPrefix') v = v.replace(/^\d+[.\s]*/, ''); return v === '' ? null : v; };
}

async function bakeOne(cfg) {
  const exs = cfg.dims.map(extractor);
  const counts = new Map();        // klíč: year SEP v0 SEP v1 ... → metrika
  const dimSeen = cfg.dims.map(() => new Map()); // dim → Map(value → total) pro řazení
  const yearsSeen = new Set();
  let nRows = 0, nUsed = 0;
  const r = await fetch(cfg.src, { headers: { 'User-Agent': UA } });
  if (!r.ok) throw new Error(`${cfg.id}: HTTP ${r.status}`);
  const ns = Readable.fromWeb(r.body); ns.setEncoding(cfg.encoding === 'windows-1250' ? 'latin1' : 'utf8');
  const t0 = Date.now();
  await new Promise((res, rej) => Papa.parse(ns, {
    header: true, skipEmptyLines: true,
    step: ({ data: x }) => {
      nRows++;
      const y = parseInt((x[cfg.yearCol] || '').toString(), 10);
      if (!Number.isFinite(y) || y < cfg.year_from) return;
      const vals = [];
      for (let i = 0; i < exs.length; i++) { const v = exs[i](x); if (v == null) return; vals.push(v); }
      let amount = 1;
      if (cfg.metric.type === 'sum') { amount = parseFloat((x[cfg.metric.col] || '').toString().replace(',', '.')); if (!Number.isFinite(amount)) return; }
      const key = y + SEP + vals.join(SEP);
      counts.set(key, (counts.get(key) || 0) + amount);
      yearsSeen.add(y);
      for (let i = 0; i < vals.length; i++) dimSeen[i].set(vals[i], (dimSeen[i].get(vals[i]) || 0) + amount);
      nUsed++;
    }, complete: res, error: rej,
  }));

  // sestav dimenze
  const years = [...yearsSeen].sort((a, b) => a - b);
  const dims = cfg.dims.map((d, i) => {
    let values;
    if (d.kind === 'age') values = [...dimSeen[i].keys()].sort((a, b) => a - b);
    else if (d.order === 'fixed') values = d.fixed.filter(v => dimSeen[i].has(v));
    else { values = [...dimSeen[i].keys()].sort((a, b) => (dimSeen[i].get(b) - dimSeen[i].get(a))); if (d.maxValues) values = values.slice(0, d.maxValues); } // podle objemu, příp. strop
    // názvy: pro DG_ONKO doplň lidský název
    let outValues = values;
    if (d.map === 'DG_ONKO') { const nm = {}; for (const v of Object.values(DG_ONKO)) nm[v.key] = v.name; outValues = values.map(k => ({ key: k, name: nm[k] })); }
    return { key: d.key, label: d.label, kind: d.kind, primary: !!d.primary, values: outValues };
  });
  const idxMaps = dims.map((d, i) => {
    const m = new Map();
    (cfg.dims[i].kind === 'age' ? d.values : d.values.map(v => (v && typeof v === 'object') ? v.key : v)).forEach((v, j) => m.set(v, j));
    return m;
  });
  const yi = new Map(years.map((y, i) => [y, i]));
  const cells = [];
  for (const [k, n] of counts) {
    const parts = k.split(SEP); const y = +parts[0];
    const tuple = [yi.get(y)];
    let ok = true;
    for (let i = 0; i < dims.length; i++) { const v = cfg.dims[i].kind === 'age' ? +parts[i + 1] : parts[i + 1]; const ix = idxMaps[i].get(v); if (ix == null) { ok = false; break; } tuple.push(ix); }
    if (ok) { tuple.push(cfg.metric.type === 'sum' ? Math.round(n) : n); cells.push(tuple); }
  }

  const anomalies = scanAnomalies(cfg, dims, years, counts);
  const cube = {
    id: cfg.id, human_name: cfg.human_name, description: cfg.description,
    source: cfg.source, source_url: cfg.source_url, metric_label: cfg.metric_label,
    baked_at: new Date().toISOString().slice(0, 10), note: cfg.note,
    years, dims, cells, anomalies,
  };
  mkdirSync('data/cubes', { recursive: true });
  writeFileSync(`data/cubes/${cfg.id}.json`, JSON.stringify(cube) + '\n');
  const secs = ((Date.now() - t0) / 1000).toFixed(0);
  console.log(`✓ ${cfg.id}: ${nUsed.toLocaleString()}/${nRows.toLocaleString()} řádků, ${cells.length.toLocaleString()} buněk, ${(JSON.stringify(cube).length / 1024).toFixed(0)} KB, ${secs}s, ${anomalies.length} anomálií`);
  for (const a of anomalies.slice(0, 6)) {
    if (a.type === 'trend') console.log(`    [trend] ${a.pct > 0 ? '+' : ''}${a.pct}% ${a.name}${a.artifact_risk ? ' ⚠' : ''}`);
    if (a.type === 'vek_posun') console.log(`    [věk] ${a.diff > 0 ? '+' : ''}${a.diff} b.b. <50 ${a.name}`);
    if (a.type === 'stadium_posun') console.log(`    [stadium] ${a.diff > 0 ? '+' : ''}${a.diff} b.b. pozdní ${a.name}`);
  }
}

// Sken anomálií nad primární dimenzí (+ věk + stadium, pokud existují).
function scanAnomalies(cfg, dims, years, counts) {
  const pIdx = dims.findIndex(d => d.primary); if (pIdx < 0) return [];
  const ageIdx = dims.findIndex(d => d.kind === 'age');
  const stageIdx = dims.findIndex(d => d.values.includes && d.values.includes('III') && d.values.includes('IV'));
  const pVals = dims[pIdx].values; const pName = (k) => { const v = pVals.find(x => ((x && typeof x === 'object') ? x.key : x) === k); return (v && typeof v === 'object') ? v.name : k; };
  // Adaptivní období: první 3 a poslední 3 roky, které registr má (ne napevno) — jinak vznikají
  // falešné skoky u registrů s jiným pokrytím (covid, očkování).
  const BASE = years.slice(0, 3), REC = years.slice(-3);
  const byPYear = {}, byPYoung = {}, byPLate = {};
  for (const [key, n] of counts) {
    const parts = key.split(SEP); const Y = +parts[0]; const pv = parts[pIdx + 1];
    (byPYear[pv] = byPYear[pv] || {})[Y] = (byPYear[pv][Y] || 0) + n;
    const per = BASE.includes(Y) ? 'b' : REC.includes(Y) ? 'r' : null;
    if (per && ageIdx >= 0) { const a = +parts[ageIdx + 1]; const yo = byPYoung[pv] = byPYoung[pv] || { b: { t: 0, y: 0 }, r: { t: 0, y: 0 } }; yo[per].t += n; if (a < 50) yo[per].y += n; }
    if (per && stageIdx >= 0) { const st = parts[stageIdx + 1]; const la = byPLate[pv] = byPLate[pv] || { b: { s: 0, l: 0 }, r: { s: 0, l: 0 } }; if (st === 'III' || st === 'IV') { la[per].s += n; la[per].l += n; } else if (st === 'I' || st === 'II') la[per].s += n; }
  }
  const avg = (o, ys) => ys.reduce((s, y) => s + ((o && o[y]) || 0), 0) / ys.length;
  const maxJump = (o) => { let m = 0; for (let i = 1; i < years.length; i++) { const a = o[years[i - 1]] || 0, b = o[years[i]] || 0; if (a >= 30) m = Math.max(m, Math.abs((b - a) / a)); } return m; };
  const out = [];
  for (const pv of Object.keys(byPYear)) {
    const b = avg(byPYear[pv], BASE), rc = avg(byPYear[pv], REC);
    if (rc >= 150 && b >= 30) { const pct = Math.round((rc - b) / b * 100); if (Math.abs(pct) >= 15) out.push({ type: 'trend', dg: pv, name: pName(pv), pct, from: Math.round(b), to: Math.round(rc), artifact_risk: maxJump(byPYear[pv]) > 0.35 }); }
    const yo = byPYoung[pv];
    if (yo && yo.r.t >= 800 && yo.b.t >= 200) { const sb = yo.b.y / yo.b.t * 100, sr = yo.r.y / yo.r.t * 100; if (Math.abs(sr - sb) >= 2.5) out.push({ type: 'vek_posun', dg: pv, name: pName(pv), from_pct: +sb.toFixed(1), to_pct: +sr.toFixed(1), diff: +(sr - sb).toFixed(1) }); }
    const la = byPLate[pv];
    if (la && la.r.s >= 400 && la.b.s >= 200) { const lb = la.b.l / la.b.s * 100, lr = la.r.l / la.r.s * 100; if (Math.abs(lr - lb) >= 3) out.push({ type: 'stadium_posun', dg: pv, name: pName(pv), from_pct: +lb.toFixed(1), to_pct: +lr.toFixed(1), diff: +(lr - lb).toFixed(1) }); }
  }
  const byType = (t) => out.filter(a => a.type === t).sort((a, b) => Math.abs(b.diff ?? b.pct) - Math.abs(a.diff ?? a.pct));
  const tr = byType('trend'), ve = byType('vek_posun'), st = byType('stadium_posun'), mixed = [];
  for (let i = 0; i < Math.max(tr.length, ve.length, st.length); i++) { if (tr[i]) mixed.push(tr[i]); if (ve[i]) mixed.push(ve[i]); if (st[i]) mixed.push(st[i]); }
  return mixed;
}

const ONKO_SRC_INC = 'https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv';
const ONKO_SRC_MOR = 'https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv';

const CONFIGS = [
  {
    id: 'onkologie_incidence', src: ONKO_SRC_INC, source: 'Národní onkologický registr (ÚZIS ČR)',
    source_url: 'https://www.nzip.cz/data/2054-incidence-prevalence-zhoubne-nadory',
    human_name: 'Onkologie — nově diagnostikované zhoubné nádory',
    description: 'Počty nově diagnostikovaných zhoubných nádorů v Česku z Národního onkologického registru, rozpadnutelné podle diagnózy, věku, pohlaví a stadia při záchytu.',
    metric_label: 'Nově diagnostikované případy', metric: { type: 'count' }, yearCol: 'rok_dg', year_from: 2000,
    note: 'Kurátorované primární diagnózy. Nehodgkinské lymfomy (C82–C86) sloučeny. Stadium III+IV = pozdní záchyt; „neuvedeno" je u některých diagnóz (mozek) převažující.',
    dims: [
      { key: 'diagnosis', label: 'Diagnóza', kind: 'category', primary: true, col: 'diagnoza_kod', map: 'DG_ONKO' },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kategorie_kod_dg', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
      { key: 'stage', label: 'Stadium', kind: 'category', col: 'stadium', map: 'STAGE', order: 'fixed', fixed: ['I', 'II', 'III', 'IV', 'neuvedeno'] },
    ],
  },
  {
    id: 'onkologie_umrti', src: ONKO_SRC_MOR, source: 'Národní onkologický registr (ÚZIS ČR)',
    source_url: 'https://www.nzip.cz/data/2056-mortalita-zhoubne-nadory',
    human_name: 'Onkologie — úmrtí na zhoubné nádory',
    description: 'Počty úmrtí na zhoubné nádory v Česku z Národního onkologického registru, rozpadnutelné podle diagnózy, věku a pohlaví.',
    metric_label: 'Úmrtí', metric: { type: 'count' }, yearCol: 'umrti_rok', year_from: 2000,
    note: 'Kurátorované primární diagnózy. Nehodgkinské lymfomy (C82–C86) sloučeny. Bez stadia (registr úmrtí ho neeviduje).',
    dims: [
      { key: 'diagnosis', label: 'Diagnóza', kind: 'category', primary: true, col: 'diagnoza_kod', map: 'DG_ONKO' },
      { key: 'age', label: 'Věk', kind: 'age', col: 'umrti_vek_kategorie_kod', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  {
    id: 'infekcni_nemoci', src: 'https://datanzis.uzis.gov.cz/data/NR-27-ISIN/NR-27-01/Otevrena-data-NR-27-01-infekcni-nemoci.csv',
    source: 'Informační systém infekčních nemocí (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/2621-infekcni-nemoci-otevrena-data',
    human_name: 'Infekční nemoci — hlášené případy',
    description: 'Počty hlášených případů infekčních nemocí v Česku, rozpadnutelné podle nemoci, věku a pohlaví.',
    metric_label: 'Hlášené případy', metric: { type: 'sum', col: 'pocet_pripadu' }, yearCol: 'rok', year_from: 2010,
    note: 'Zobrazeno 40 nejčastějších nemocí. Velké meziroční skoky bývají epidemie (chřipka, covid) — ne chyba.',
    dims: [
      { key: 'nemoc', label: 'Nemoc', kind: 'category', primary: true, col: 'diagnoza_nazev', maxValues: 40 },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kod', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX_MZ' },
    ],
  },
  {
    id: 'hospitalizace_akutni', src: 'https://data.mzcr.cz/data/distribuce/364/Otevrena-data-NR-04-08-hospitalizacni-pripady-akutni-pece-2024-01.csv',
    source: 'Národní registr hrazených zdravotních služeb (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1751-hospitalizacni-pripady-akutni-pece-otevrena-data',
    human_name: 'Hospitalizace v akutní péči',
    description: 'Počty hospitalizačních případů v akutní lůžkové péči, rozpadnutelné podle skupiny diagnóz (kapitola MKN), věku a pohlaví.',
    metric_label: 'Hospitalizační případy', metric: { type: 'sum', col: 'pocet_hosp' }, yearCol: 'rok', year_from: 2010,
    note: 'Diagnózy seskupené do kapitol MKN-10. Hlavní diagnóza hospitalizace (ZDG).',
    dims: [
      { key: 'skupina', label: 'Skupina diagnóz', kind: 'category', primary: true, col: 'ZDG', map: 'MKN_CHAPTER' },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kod', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  // Pozn.: očkování (vakcinace) zatím vynecháno — „trendy" jsou hlavně spouštění/rozšiřování
  // očkovacích programů (0 → plošně), takže auto-anomálie klamou. Vrátit se k němu jinak (proočkovanost).
];

const only = process.argv.slice(2);
for (const cfg of CONFIGS) { if (only.length && !only.includes(cfg.id)) continue; await bakeOne(cfg); }
