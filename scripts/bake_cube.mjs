// Napeče "rozpadové kostky" z registrů NZIP/ÚZIS. Config-driven a OBECNÉ DIMENZE:
// každá kostka nese pole dims [{key,label,kind,values,primary?}] + řídké buňky
// [yearIdx, ...dimIdx, count] + sken anomálií. Frontend renderuje zužovátka dynamicky.
//
// kind: 'category' (values = pole stringů nebo {key,name}) | 'age' (values = počátky 5letých pásem).
// Jedna dim má primary:true (hlavní rozpad — nad ní běží sken anomálií).
//
// Spuštění:  node --max-old-space-size=4096 scripts/bake_cube.mjs
import { Readable } from 'node:stream';
import { createGunzip } from 'node:zlib';
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

// Kraje (NUTS3) — kód → název. Sdílené napříč kostkami s krajským členěním.
const KRAJ = {
  CZ010: 'Praha', CZ020: 'Středočeský kraj', CZ031: 'Jihočeský kraj', CZ032: 'Plzeňský kraj',
  CZ041: 'Karlovarský kraj', CZ042: 'Ústecký kraj', CZ051: 'Liberecký kraj', CZ052: 'Královéhradecký kraj',
  CZ053: 'Pardubický kraj', CZ063: 'Kraj Vysočina', CZ064: 'Jihomoravský kraj', CZ071: 'Olomoucký kraj',
  CZ072: 'Zlínský kraj', CZ080: 'Moravskoslezský kraj',
};
// Indikační skupiny lázeňské péče (vyhláška 2/2015 Sb., příloha 5 zák. 48/1997). Dospělí I–XI,
// děti a dorost XXI–XXXI = stejných 11 nemocí (dětské číslo = dospělé + 20). Sjednoceno na názvy
// nemocí; věk drží samostatná dimenze.
const LAZNE_NEMOC = ['nemoci onkologické', 'nemoci oběhového ústrojí', 'nemoci trávicího ústrojí',
  'nemoci z poruch výměny látkové a žláz s vnitřní sekrecí', 'netuberkulózní nemoci dýchacího ústrojí',
  'nemoci nervové', 'nemoci pohybového ústrojí', 'nemoci ledvin a močových cest', 'duševní poruchy',
  'nemoci kožní', 'nemoci gynekologické'];
const ADULT_RNUM = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI'];
const CHILD_RNUM = ['XXI', 'XXII', 'XXIII', 'XXIV', 'XXV', 'XXVI', 'XXVII', 'XXVIII', 'XXIX', 'XXX', 'XXXI'];
const LAZNE_INDIKACE = {};
LAZNE_NEMOC.forEach((nemoc, i) => { LAZNE_INDIKACE[ADULT_RNUM[i]] = nemoc; LAZNE_INDIKACE[CHILD_RNUM[i]] = nemoc; });
const LAZNE_TYP = { KLP: 'komplexní lázeňská péče (plně hrazená)', PLP: 'příspěvková lázeňská péče', Samoplátce: 'samoplátce', Cizinec: 'cizinec (samoplátce)' };

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
  if (dim.valueMap) return (r) => dim.valueMap[(r[col] ?? '').toString().trim()] || null; // číselník kód→název
  // plain category — hodnota přímo ze sloupce (volitelně očištěná o prefix a přeložená přes relabel)
  return (r) => {
    let v = (r[col] ?? '').toString().trim();
    if (dim.clean === 'stripNumPrefix') v = v.replace(/^\d+[.\s]*/, '');
    if (v === '') return null;
    if (dim.clean === 'lower') v = v.charAt(0).toUpperCase() + v.slice(1).toLowerCase();
    if (dim.relabel) v = dim.relabel[v] || v;
    return v;
  };
}

async function bakeOne(cfg) {
  const wideIdx = cfg.dims.findIndex(d => d.wide); // „široký" formát: primární dim z příčinových sloupců
  const exs = cfg.dims.map(d => d.wide ? null : extractor(d));
  const counts = new Map();        // klíč: year SEP v0 SEP v1 ... → metrika
  const dimSeen = cfg.dims.map(() => new Map()); // dim → Map(value → total) pro řazení
  const yearsSeen = new Set();
  let nRows = 0, nUsed = 0;
  // Zdroj lze přepsat lokálním souborem přes env (CUBESRC_<id>) — pro velké soubory, které
  // se přes fetch utrhávají, je stáhneme robustně curl-em do /tmp a zpracujeme lokálně.
  const srcUrl = process.env['CUBESRC_' + cfg.id] || cfg.src;
  const isLocal = !/^https?:/.test(srcUrl);
  let src;
  if (isLocal) {
    src = (await import('node:fs')).createReadStream(srcUrl);
  } else {
    const r = await fetch(srcUrl, { headers: { 'User-Agent': UA } });
    if (!r.ok) throw new Error(`${cfg.id}: HTTP ${r.status}`);
    src = Readable.fromWeb(r.body);
  }
  let ns = src;
  if (srcUrl.endsWith('.gz')) ns = src.pipe(createGunzip()); // gzipované zdroje (.csv.gz)
  ns.setEncoding(cfg.encoding === 'windows-1250' ? 'latin1' : 'utf8');
  const t0 = Date.now();
  const addCell = (y, vals, amount) => {
    const key = y + SEP + vals.join(SEP);
    counts.set(key, (counts.get(key) || 0) + amount);
    yearsSeen.add(y);
    for (let i = 0; i < vals.length; i++) dimSeen[i].set(vals[i], (dimSeen[i].get(vals[i]) || 0) + amount);
    nUsed++;
  };
  await new Promise((res, rej) => {
    src.on('error', rej);            // chyba zdrojového streamu (výpadek socketu)
    if (ns !== src) ns.on('error', rej); // chyba rozbalování
    Papa.parse(ns, {
    header: true, skipEmptyLines: true,
    step: ({ data: x }) => {
      nRows++;
      const y = parseInt((x[cfg.yearCol] || '').toString(), 10);
      if (!Number.isFinite(y) || y < cfg.year_from) return;
      const vals = [];
      for (let i = 0; i < exs.length; i++) { if (i === wideIdx) { vals.push(null); continue; } const v = exs[i](x); if (v == null) return; vals.push(v); }
      if (wideIdx >= 0) {
        // jeden řádek → po jedné buňce za každou příčinu se zápornou/nenulovou hodnotou
        for (const cause of cfg.wideCauses) {
          const amt = parseFloat((x[cause.col] || '').toString().replace(',', '.'));
          if (!Number.isFinite(amt) || amt <= 0) continue;
          const vv = vals.slice(); vv[wideIdx] = cause.name;
          addCell(y, vv, amt);
        }
      } else {
        let amount = 1;
        if (cfg.metric.type === 'sum') { amount = parseFloat((x[cfg.metric.col] || '').toString().replace(',', '.')); if (!Number.isFinite(amount)) return; }
        addCell(y, vals, amount);
      }
    }, complete: res, error: rej,
    });
  });

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

  // U některých registrů (očkování) jsou „trendy" jen spouštění programů → anomálie klamou.
  // Takové kostky slouží čistě popisně (zužovátka + čísla), sken se vypne.
  const anomalies = cfg.noAnomalies ? [] : scanAnomalies(cfg, dims, years, counts);
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
  {
    id: 'umrti_priciny', src: 'https://data.mzcr.cz/data/distribuce/467/Otevrena-data-NR-06-33-denni-umrti-vek-pohlavi-pricina.csv',
    source: 'Národní registr úmrtí (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/2516-denni-umrti-vek-pohlavi-pricina-otevrena-data',
    human_name: 'Úmrtí podle příčiny',
    description: 'Počty úmrtí v Česku podle hlavní skupiny příčin (kapitola MKN), rozpadnutelné podle příčiny, věku a pohlaví. Ukazuje, na co Češi umírají a jak se to v čase mění.',
    metric_label: 'Úmrtí', metric: { type: 'wide' }, yearCol: 'rok_umrti', year_from: 2010,
    note: 'Příčiny dle hlavních kapitol MKN-10 (sloupce zem_*). Celkový součet (zem_celkem) nezahrnut, aby se příčiny nedvojily.',
    wideCauses: [
      { col: 'zem_obehova', name: 'nemoci oběhové soustavy' },
      { col: 'zem_novotvary', name: 'novotvary (nádory)' },
      { col: 'zem_dychaci', name: 'nemoci dýchací soustavy' },
      { col: 'zem_travici', name: 'nemoci trávicí soustavy' },
      { col: 'zem_vnejsi', name: 'vnější příčiny (úrazy, otravy)' },
      { col: 'zem_nervova', name: 'nemoci nervové soustavy' },
      { col: 'zem_endokrinni', name: 'nemoci endokrinní a látkové přeměny' },
      { col: 'zem_dusevni', name: 'duševní poruchy' },
      { col: 'zem_infekcni', name: 'infekční nemoci' },
      { col: 'zem_mocova', name: 'nemoci močové a pohlavní soustavy' },
    ],
    dims: [
      { key: 'pricina', label: 'Příčina úmrtí', kind: 'category', primary: true, wide: true },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kat', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  {
    id: 'srdecni_selhani', src: 'https://data.mzcr.cz/data/distribuce/332/Otevrena-data-OIS-01-03-epidemiologie-srdecni-selhani.csv',
    source: 'Národní zdravotnický informační systém (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1664-srdecni-selhani-epidemiologie-otevrena-data',
    human_name: 'Srdeční selhání — pacienti podle typu péče',
    description: 'Počty pacientů se srdečním selháním podle typu poskytnuté péče, rozpadnutelné podle typu péče, věku a pohlaví. Jeden pacient se může objevit ve více typech péče.',
    metric_label: 'Pacienti (case-years)', metric: { type: 'wide' }, yearCol: 'rok', year_from: 2015,
    note: 'Typy péče z příznakových sloupců (pacient může mít více). Počítají se pacient-roky.',
    wideCauses: [
      { col: 'lecba_ambulantni', name: 'ambulantní léčba' },
      { col: 'lecba_hospitalizacni_primarni', name: 'hospitalizace (srdeční selhání hlavní diagnóza)' },
      { col: 'lecba_hospitalizacni_sekundarni', name: 'hospitalizace (srdeční selhání vedlejší diagnóza)' },
      { col: 'lecba_implantace_transplantace', name: 'implantace přístroje nebo transplantace' },
    ],
    dims: [
      { key: 'pece', label: 'Typ péče', kind: 'category', primary: true, wide: true },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kod', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  {
    id: 'porody_zpusob', src: 'https://data.mzcr.cz/data/distribuce/322/rodicky-zpusob-porodu.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1622-rodicky-zpusob-porodu-otevrena-data',
    human_name: 'Porody — způsob porodu',
    description: 'Počty porodů podle způsobu porodu (vaginální porod nebo císařský řez) a věku matky. Ukazuje mimo jiné trend míry císařských řezů a porodů u starších matek.',
    metric_label: 'Porody', metric: { type: 'count' }, yearCol: 'rok_porodu', year_from: 2000,
    note: 'Věkové skupiny matek dle standardního pětiletého členění ÚZIS (kódy 1–6).',
    dims: [
      { key: 'zpusob', label: 'Způsob porodu', kind: 'category', primary: true, col: 'zpusob_porodu', valueMap: { '1': 'vaginální porod', '2': 'císařský řez' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
    ],
  },
  {
    id: 'porody_komplikace', src: 'https://data.mzcr.cz/data/distribuce/325/rodicky-komplikace-porod.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1625-rodicky-komplikace-porod-otevrena-data',
    human_name: 'Porody — komplikace porodu',
    description: 'Počty porodů provázených konkrétní komplikací (nástřih hráze, poranění hráze, ruptura dělohy, výhřez pupečníku, větší krevní ztráta…), rozpadnutelné podle věku matky, parity a typu poskytovatele zdravotních služeb. Jeden porod může mít více komplikací.',
    metric_label: 'Porody s danou komplikací', metric: { type: 'wide' }, yearCol: 'rok_porodu', year_from: 2000,
    note: 'Příznakové sloupce komplikací (hodnota 1 = ano), jeden porod může spadat do více komplikací → počty napříč komplikacemi nelze sčítat. Poranění čípku, hrdla nebo pochvy a poranění hráze I.–IV. stupně registr eviduje až od roku 2016. Parita: prvorodička = žádný předchozí porod, vícerodička = alespoň jeden.',
    wideCauses: [
      { col: 'komplikace_por_epiziotomie', name: 'epiziotomie (nástřih hráze)' },
      { col: 'komplikace_por_porhraze1', name: 'poranění hráze I. a II. stupně' },
      { col: 'komplikace_por_porhraze2', name: 'poranění hráze III. a IV. stupně' },
      { col: 'komplikace_por_poraneni', name: 'poranění děložního čípku, hrdla nebo pochvy' },
      { col: 'komplikace_por_ztratakrve', name: 'ztráta krve nad 500 mililitrů' },
      { col: 'komplikace_por_dystokie', name: 'dystokie ramének' },
      { col: 'komplikace_por_ruptura', name: 'ruptura dělohy' },
      { col: 'komplikace_por_vyhrez', name: 'výhřez pupečníku' },
      { col: 'komplikace_por_hysterektomie', name: 'hysterektomie do 48 hodin po porodu' },
    ],
    dims: [
      { key: 'komplikace', label: 'Komplikace', kind: 'category', primary: true, wide: true },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
      { key: 'parita', label: 'Parita', kind: 'category', col: 'parita', valueMap: { '1': 'prvorodička', '2': 'vícerodička' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'tehotenstvi_komplikace', src: 'https://data.mzcr.cz/data/distribuce/321/rodicky-komplikace-tehotenstvi.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1624-rodicky-komplikace-tehotenstvi-otevrena-data',
    human_name: 'Těhotenství — komplikace v těhotenství',
    description: 'Počty těhotenství provázených konkrétní komplikací (hrozící předčasný porod, krvácení, poruchy placenty, vysoký krevní tlak a kardiovaskulární onemocnění, preeklampsie, eklampsie, růstová retardace plodu), rozpadnutelné podle věku matky a typu poskytovatele zdravotních služeb. Jedno těhotenství může mít více komplikací.',
    metric_label: 'Těhotenství s danou komplikací', metric: { type: 'wide' }, yearCol: 'rok_porodu', year_from: 2000,
    note: 'Příznakové sloupce komplikací (hodnota 1 = ano), jedno těhotenství může mít více komplikací → počty napříč komplikacemi nelze sčítat. Krvácení v této podobě registr eviduje až od roku 2016. Názvy komplikací jsou odvozené z názvů sloupců registru.',
    wideCauses: [
      { col: 'komplikace_teh_hrozicipredcasporod', name: 'hrozící předčasný porod' },
      { col: 'komplikace_teh_krvaceni', name: 'krvácení v těhotenství' },
      { col: 'komplikace_teh_placenta', name: 'poruchy placenty' },
      { col: 'komplikace_teh_kardio_hypertenze', name: 'vysoký krevní tlak a kardiovaskulární onemocnění' },
      { col: 'komplikace_teh_preeklampsie', name: 'preeklampsie' },
      { col: 'komplikace_teh_eklampsie', name: 'eklampsie' },
      { col: 'komplikace_teh_iugr', name: 'růstová retardace plodu' },
    ],
    dims: [
      { key: 'komplikace', label: 'Komplikace', kind: 'category', primary: true, wide: true },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'rodicky_sociodemografie', src: 'https://datanzis.uzis.gov.cz/data/NR-12-NRRZ-ROD/NR-12-02/Otevrena-data-NR-12-02-rodicky-sociodemograficke-charakteristiky.csv.gz',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1621-rodicky-sociodemograficke-charakteristiky-otevrena-data',
    human_name: 'Rodičky — vzdělání, rodinný stav, věk a kraj',
    description: 'Interaktivní rozpad rodiček podle nejvyššího dosaženého vzdělání, rodinného stavu, věku a kraje bydliště. Ukazuje, jak se v čase mění složení rodiček — například podíl vysokoškolaček nebo neprovdaných matek. Popisná data, ne hledání anomálií.',
    metric_label: 'Rodičky', metric: { type: 'count' }, yearCol: 'rok_porodu', year_from: 1994, noAnomalies: true,
    note: 'Jedna řádka = jeden porod (rodička). Vzdělání má část záznamů neuvedenou (od roku 2016 zhruba pětinu), počty podle vzdělání proto v posledních letech podhodnocují skutečnost. Číselníky vzdělání a rodinného stavu podle metodiky Národního registru rodiček. Kategorie „nezjištěno“ je ponechána, aby součty seděly.',
    dims: [
      { key: 'vzdelani', label: 'Vzdělání', kind: 'category', primary: true, col: 'vzdelani', order: 'fixed',
        fixed: ['základní i neukončené', 'střední bez maturity', 'střední s maturitou (včetně vyššího odborného)', 'vysokoškolské (včetně bakalářského)', 'nezjištěno'],
        valueMap: { '1': 'základní i neukončené', '2': 'střední bez maturity', '3': 'střední s maturitou (včetně vyššího odborného)', '4': 'vysokoškolské (včetně bakalářského)', '': 'nezjištěno' } },
      { key: 'rodinny_stav', label: 'Rodinný stav', kind: 'category', col: 'rodinny_stav', order: 'fixed',
        fixed: ['svobodná', 'vdaná', 'rozvedená', 'ovdovělá', 'družka', 'nezjištěno'],
        valueMap: { '1': 'svobodná', '2': 'vdaná', '3': 'rozvedená', '4': 'ovdovělá', '5': 'družka', '0': 'nezjištěno', '': 'nezjištěno' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', order: 'fixed',
        fixed: ['do 19 let', '20–24 let', '25–29 let', '30–34 let', '35–39 let', '40 a více let', 'nezjištěno'],
        valueMap: { '66000019': 'do 19 let', '66020024': '20–24 let', '66025029': '25–29 let', '66030034': '30–34 let', '66035039': '35–39 let', '66040999': '40 a více let', '70001000': 'nezjištěno' } },
      { key: 'kraj', label: 'Kraj bydliště', kind: 'category', col: 'kraj_bydliste', valueMap: { ...KRAJ, CZ099: 'nezjištěno', CZ088: 'nezjištěno' } },
    ],
  },
  {
    id: 'novorozenci_charakteristiky', src: 'https://datanzis.uzis.gov.cz/data/NR-10-NRRZ-NAR/NR-10-01/Otevrena-data-NR-10-01-novorozenci-sociodemograficke-charakteristiky.csv.gz',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1615-novorozenci-sociodemograficke-charakteristiky-otevrena-data',
    human_name: 'Novorozenci — porodní hmotnost, gestační stáří a pohlaví',
    description: 'Interaktivní rozpad narozených dětí podle porodní hmotnosti, gestačního stáří (zralosti při narození), pohlaví, četnosti těhotenství a kraje bydliště matky. Ukazuje mimo jiné podíl dětí s nízkou porodní hmotností a předčasně narozených. Popisná data, ne hledání anomálií.',
    metric_label: 'Narozené děti', metric: { type: 'count' }, yearCol: 'rok_narozeni', year_from: 1994, noAnomalies: true,
    note: 'Jedna řádka = jedno narozené dítě. Porodní hmotnost a gestační stáří jsou kvůli ochraně osobních údajů členěny do širokých pásem podle metodiky Národního registru reprodukčního zdraví. Pásma porodní hmotnosti „méně než 1500 g" a „1500–2499 g" dohromady odpovídají nízké porodní hmotnosti, gestační pásma „do 31. týdne" a „32.–36. týden" předčasnému porodu. Četnost těhotenství registr eviduje až od roku 2000, dřívější roky jsou u ní „nezjištěno". Kategorie „nezjištěno" jsou ponechány, aby součty seděly.',
    dims: [
      { key: 'hmotnost', label: 'Porodní hmotnost', kind: 'category', primary: true, col: 'porodni_hmotnost', order: 'fixed',
        fixed: ['méně než 1500 g', '1500–2499 g', '2500–3499 g', '3500 g a více', 'nezjištěno'],
        valueMap: { '1': 'méně než 1500 g', '2': '1500–2499 g', '3': '2500–3499 g', '4': '3500 g a více', '': 'nezjištěno' } },
      { key: 'gestace', label: 'Gestační stáří', kind: 'category', col: 'gestacni_stari', order: 'fixed',
        fixed: ['do 31. týdne', '32.–36. týden', '37.–38. týden', '39. týden a více', 'nezjištěno'],
        valueMap: { '1': 'do 31. týdne', '2': '32.–36. týden', '3': '37.–38. týden', '4': '39. týden a více', '': 'nezjištěno' } },
      { key: 'pohlavi', label: 'Pohlaví', kind: 'category', col: 'pohlavi', order: 'fixed',
        fixed: ['chlapec', 'dívka', 'nespecifikováno'],
        valueMap: { '1': 'chlapec', '2': 'dívka', '3': 'nespecifikováno' } },
      { key: 'cetnost', label: 'Četnost těhotenství', kind: 'category', col: 'cetnost', order: 'fixed',
        fixed: ['jednočetné', 'vícečetné', 'nezjištěno'],
        valueMap: { '1': 'jednočetné', '2': 'vícečetné', '': 'nezjištěno' } },
      { key: 'kraj', label: 'Kraj bydliště matky', kind: 'category', col: 'kraj_bydliste', valueMap: { ...KRAJ, CZ099: 'cizinci', CZ088: 'bezdomovci', '': 'nezjištěno' } },
    ],
  },
  {
    id: 'novorozenci_vrozene_vady', src: 'https://data.mzcr.cz/data/distribuce/318/novorozenci-vady.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1612-novorozenci-vrozene-vady-otevrena-data',
    human_name: 'Novorozenci — vrozené vady a vitalita',
    description: 'Interaktivní rozpad narozených dětí podle toho, zda měly při narození zjištěnou vrozenou vadu, a podle vitality (živě, nebo mrtvě narozené), v členění podle gestačního stáří, porodní hmotnosti, věku matky a typu poskytovatele. Ukazuje mimo jiné, jak často se vrozené vady pojí s nízkou porodní hmotností a předčasným porodem.',
    metric_label: 'Narozené děti', metric: { type: 'count' }, yearCol: 'rok_narozeni', year_from: 2000, noAnomalies: true,
    note: 'Jedna řádka = jedno narozené dítě, registr eviduje od roku 2000. „Vrozená vada" je příznak ano/ne, ne typ konkrétní vady. Podíl dětí s evidovanou vrozenou vadou ovlivňuje i dostupnost a důslednost záchytu, ne jen skutečný výskyt. Pásma porodní hmotnosti a gestačního stáří podle metodiky registru; kategorie „nezjištěno" jsou ponechány, aby součty seděly.',
    dims: [
      { key: 'vada', label: 'Vrozená vada', kind: 'category', primary: true, col: 'vrozena_vada', order: 'fixed',
        fixed: ['s vrozenou vadou', 'bez vrozené vady'],
        valueMap: { '1': 's vrozenou vadou', '0': 'bez vrozené vady' } },
      { key: 'vitalita', label: 'Vitalita', kind: 'category', col: 'vitalita', order: 'fixed',
        fixed: ['živě narozené', 'mrtvě narozené'],
        valueMap: { '1': 'živě narozené', '2': 'mrtvě narozené' } },
      { key: 'gestace', label: 'Gestační stáří', kind: 'category', col: 'gestacni_stari', order: 'fixed',
        fixed: ['do 31. týdne', '32.–36. týden', '37.–38. týden', '39. týden a více', 'nezjištěno'],
        valueMap: { '1': 'do 31. týdne', '2': '32.–36. týden', '3': '37.–38. týden', '4': '39. týden a více', '': 'nezjištěno' } },
      { key: 'hmotnost', label: 'Porodní hmotnost', kind: 'category', col: 'porodni_hmotnost', order: 'fixed',
        fixed: ['méně než 1500 g', '1500–2499 g', '2500–3499 g', '3500 g a více', 'nezjištěno'],
        valueMap: { '1': 'méně než 1500 g', '2': '1500–2499 g', '3': '2500–3499 g', '4': '3500 g a více', '': 'nezjištěno' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', order: 'fixed',
        fixed: ['do 19 let', '20–24 let', '25–29 let', '30–34 let', '35–39 let', '40 a více let', 'nezjištěno'],
        valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let', '': 'nezjištěno' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'novorozenci_screening', src: 'https://data.mzcr.cz/data/distribuce/316/novorozenci-screening.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1623-novorozenci-screening-otevrena-data',
    human_name: 'Novorozenci — screeningová vyšetření',
    description: 'Počty novorozenců, u nichž bylo provedeno dané screeningové vyšetření (laboratorní screening z patní krve, screening srdečních vad pulzní oxymetrií, oční screening katarakty, screening sluchu a kyčlí), rozpadnutelné podle gestačního stáří, věku matky a typu poskytovatele. U jednoho novorozence se obvykle provádí víc screeningů, počty napříč vyšetřeními proto nelze sčítat.',
    metric_label: 'Novorozenci s provedeným screeningem', metric: { type: 'wide' }, yearCol: 'rok_narozeni', year_from: 2016, noAnomalies: true,
    note: 'Příznakové sloupce screeningů (hodnota 1 = provedeno), registr eviduje až od roku 2016. U jednoho novorozence se provádí víc screeningů → počty napříč vyšetřeními nelze sčítat. Názvy vyšetření jsou odvozené z metodiky registru.',
    wideCauses: [
      { col: 'screening_nls', name: 'laboratorní screening (z patní krve)' },
      { col: 'screening_sluch', name: 'screening sluchu' },
      { col: 'screening_kycle', name: 'screening kyčlí' },
      { col: 'screening_katarakta', name: 'oční screening (katarakta)' },
      { col: 'screening_koarktace', name: 'screening srdečních vad (pulzní oxymetrie)' },
      { col: 'screening_jiny', name: 'jiný screening' },
    ],
    dims: [
      { key: 'screening', label: 'Druh screeningu', kind: 'category', primary: true, wide: true },
      { key: 'gestace', label: 'Gestační stáří', kind: 'category', col: 'gestacni_stari', order: 'fixed',
        fixed: ['do 31. týdne', '32.–36. týden', '37.–38. týden', '39. týden a více', 'nezjištěno'],
        valueMap: { '1': 'do 31. týdne', '2': '32.–36. týden', '3': '37.–38. týden', '4': '39. týden a více', '': 'nezjištěno' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', order: 'fixed',
        fixed: ['do 19 let', '20–24 let', '25–29 let', '30–34 let', '35–39 let', '40 a více let', 'nezjištěno'],
        valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let', '': 'nezjištěno' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'novorozenci_lecba_sal', src: 'https://data.mzcr.cz/data/distribuce/311/novorozenci-lecba-sal.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1614-novorozenci-lecba-porodni-sal-otevrena-data',
    human_name: 'Novorozenci — léčba na porodním sále',
    description: 'Počty novorozenců, u nichž byl na porodním sále proveden daný resuscitační výkon (podání kyslíku, prodýchnutí maskou, intubace, nepřímá srdeční masáž, podání léků, přetlaková podpora dýchání), rozpadnutelné podle gestačního stáří, věku matky a typu poskytovatele. U jednoho novorozence může být provedeno víc výkonů, počty napříč výkony proto nelze sčítat.',
    metric_label: 'Novorozenci s daným výkonem', metric: { type: 'wide' }, yearCol: 'rok_narozeni', year_from: 2000, noAnomalies: true,
    note: 'Příznakové sloupce výkonů (hodnota 1 = proveden), registr eviduje od roku 2000. Přetlakovou podporu dýchání (CPAP) eviduje až od pozdějších let, dřívější roky jsou u ní prázdné. U jednoho novorozence může být provedeno víc výkonů → počty napříč výkony nelze sčítat. Názvy výkonů jsou odvozené z metodiky registru.',
    wideCauses: [
      { col: 'lecba_sal_o2', name: 'podání kyslíku' },
      { col: 'lecba_sal_ppv', name: 'prodýchnutí maskou (ventilace přetlakem)' },
      { col: 'lecba_sal_cpap', name: 'přetlaková podpora dýchání (CPAP)' },
      { col: 'lecba_sal_intubace', name: 'intubace' },
      { col: 'lecba_sal_masaz', name: 'nepřímá srdeční masáž' },
      { col: 'lecba_sal_leky', name: 'podání léků' },
    ],
    dims: [
      { key: 'vykon', label: 'Výkon na sále', kind: 'category', primary: true, wide: true },
      { key: 'gestace', label: 'Gestační stáří', kind: 'category', col: 'gestacni_stari', order: 'fixed',
        fixed: ['do 31. týdne', '32.–36. týden', '37.–38. týden', '39. týden a více', 'nezjištěno'],
        valueMap: { '1': 'do 31. týdne', '2': '32.–36. týden', '3': '37.–38. týden', '4': '39. týden a více', '': 'nezjištěno' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', order: 'fixed',
        fixed: ['do 19 let', '20–24 let', '25–29 let', '30–34 let', '35–39 let', '40 a více let', 'nezjištěno'],
        valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let', '': 'nezjištěno' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'novorozenci_lecba_oddeleni', src: 'https://data.mzcr.cz/data/distribuce/310/novorozenci-lecba-oddeleni.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1613-novorozenci-lecba-oddeleni-otevrena-data',
    human_name: 'Novorozenci — léčba na oddělení',
    description: 'Počty novorozenců, u nichž byl na novorozeneckém oddělení proveden daný léčebný výkon nebo léčba (podání kyslíku, neinvazivní a umělá plicní ventilace, podání steroidů, surfaktantu nebo antibiotik, operace, řízená hypotermie a další), rozpadnutelné podle gestačního stáří, věku matky a typu poskytovatele. U jednoho novorozence může být provedeno víc výkonů, počty napříč výkony proto nelze sčítat.',
    metric_label: 'Novorozenci s danou léčbou', metric: { type: 'wide' }, yearCol: 'rok_narozeni', year_from: 2000, noAnomalies: true,
    note: 'Příznakové sloupce léčby (hodnota 1 = provedena), registr eviduje od roku 2000. Některé výkony (kyslík, antibiotika, hypotermie, oběhová podpora, inhalační oxid dusnatý) registr doplnil až v pozdějších letech, dřívější roky jsou u nich prázdné. U jednoho novorozence může být provedeno víc výkonů → počty napříč výkony nelze sčítat. Názvy výkonů jsou odvozené z metodiky registru.',
    wideCauses: [
      { col: 'lecba_odd_o2', name: 'podání kyslíku' },
      { col: 'lecba_odd_niv', name: 'neinvazivní ventilace' },
      { col: 'lecba_odd_steroidy', name: 'podání steroidů' },
      { col: 'lecba_odd_upv', name: 'umělá plicní ventilace' },
      { col: 'lecba_odd_surfaktant', name: 'podání surfaktantu' },
      { col: 'lecba_odd_operace', name: 'operace' },
      { col: 'lecba_odd_antibiotika', name: 'podání antibiotik' },
      { col: 'lecba_odd_steroidybpd', name: 'steroidy kvůli bronchopulmonální dysplazii' },
      { col: 'lecba_odd_ligacepda', name: 'podvaz otevřené tepenné dučeje' },
      { col: 'lecba_odd_hypotermie', name: 'řízená hypotermie' },
      { col: 'lecba_odd_inotpodpora', name: 'oběhová podpora (inotropika)' },
      { col: 'lecba_odd_ino', name: 'inhalační oxid dusnatý' },
    ],
    dims: [
      { key: 'vykon', label: 'Léčba na oddělení', kind: 'category', primary: true, wide: true },
      { key: 'gestace', label: 'Gestační stáří', kind: 'category', col: 'gestacni_stari', order: 'fixed',
        fixed: ['do 31. týdne', '32.–36. týden', '37.–38. týden', '39. týden a více', 'nezjištěno'],
        valueMap: { '1': 'do 31. týdne', '2': '32.–36. týden', '3': '37.–38. týden', '4': '39. týden a více', '': 'nezjištěno' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', order: 'fixed',
        fixed: ['do 19 let', '20–24 let', '25–29 let', '30–34 let', '35–39 let', '40 a více let', 'nezjištěno'],
        valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let', '': 'nezjištěno' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'porody_leky', src: 'https://data.mzcr.cz/data/distribuce/317/rodicky-leky.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1620-rodicky-porod-leky-otevrena-data',
    human_name: 'Porody — léky podané za porodu',
    description: 'Počty porodů, u nichž byl podán lék dané skupiny (uterotonika na stahy dělohy, spasmolytika, analgetika proti bolesti, epidurální analgezie, antibiotika, uterolytika), rozpadnutelné podle věku matky, typu poskytovatele a způsobu porodu. U jednoho porodu může být podáno víc skupin léků.',
    metric_label: 'Porody s podaným lékem', metric: { type: 'wide' }, yearCol: 'rok_porodu', year_from: 2000,
    note: 'Příznakové sloupce léků (hodnota 1 = ano), u jednoho porodu může být podáno víc skupin léků → počty napříč skupinami nelze sčítat. Epidurální analgezii registr eviduje až od roku 2016, dřívější roky jsou u ní prázdné. Názvy skupin jsou odvozené z názvů sloupců registru.',
    wideCauses: [
      { col: 'leky_uterotonika', name: 'uterotonika (léky na stahy dělohy)' },
      { col: 'leky_uterolytika', name: 'uterolytika (léky tlumící stahy dělohy)' },
      { col: 'leky_spasmolytika', name: 'spasmolytika (léky uvolňující křeče)' },
      { col: 'leky_analgetika', name: 'analgetika (léky proti bolesti)' },
      { col: 'leky_epidural', name: 'epidurální analgezie' },
      { col: 'leky_antibiotika', name: 'antibiotika' },
    ],
    dims: [
      { key: 'lek', label: 'Skupina léků', kind: 'category', primary: true, wide: true },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
      { key: 'zpusob', label: 'Způsob porodu', kind: 'category', col: 'zpusob_porodu', valueMap: { '1': 'vaginální porod', '2': 'císařský řez' } },
    ],
  },
  {
    id: 'porody_cisar', src: 'https://data.mzcr.cz/data/distribuce/324/rodicky-cisar.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1616-rodicky-cisarske-rezy-otevrena-data',
    human_name: 'Porody — císařské řezy (typ a anestezie)',
    description: 'Interaktivní rozpad porodů ukončených císařským řezem podle typu (plánovaný nebo akutní, v těhotenství nebo za porodu), typu anestezie (celková, epidurální, spinální), parity, předchozího císařského řezu, věku matky a typu poskytovatele. Obsahuje jen porody vedené císařským řezem.',
    metric_label: 'Císařské řezy', metric: { type: 'count' }, yearCol: 'rok_porodu', year_from: 2000,
    note: 'Jedna řádka = jeden porod císařským řezem. Číselníky typu císaře a anestezie podle metodiky Národního registru rodiček. „Plánovaný v těhotenství“ = rozhodnuto před začátkem porodu z dlouhodobé indikace; „akutní za porodu“ = náhlá komplikace při probíhajícím porodu.',
    dims: [
      { key: 'ukonceni', label: 'Typ císařského řezu', kind: 'category', primary: true, col: 'ukonceni_cisarsky_rez', order: 'fixed',
        fixed: ['plánovaný v těhotenství', 'akutní v těhotenství', 'plánovaný za porodu', 'akutní za porodu'],
        valueMap: { '1': 'plánovaný v těhotenství', '2': 'akutní v těhotenství', '3': 'plánovaný za porodu', '4': 'akutní za porodu' } },
      { key: 'anestezie', label: 'Anestezie', kind: 'category', col: 'anestezie_sc', order: 'fixed',
        fixed: ['celková', 'epidurální', 'spinální'],
        valueMap: { '1': 'celková', '2': 'epidurální', '3': 'spinální' } },
      { key: 'parita', label: 'Parita', kind: 'category', col: 'parita', valueMap: { '1': 'prvorodička', '2': 'vícerodička' } },
      { key: 'predchozi_sc', label: 'Předchozí císařský řez', kind: 'category', col: 'predchozi_sc', valueMap: { '0': 'bez předchozího císařského řezu', '1': 's předchozím císařským řezem' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'rodicky_diabetes', src: 'https://data.mzcr.cz/data/distribuce/320/rodicky-diabetes.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1617-rodicky-diabetes-otevrena-data',
    human_name: 'Rodičky — diabetes v těhotenství',
    description: 'Interaktivní rozpad porodů podle toho, zda u matky byl zjištěn diabetes (cukrovka — zahrnuje těhotenskou cukrovku i cukrovku zjištěnou už před těhotenstvím), dále podle věku matky a typu poskytovatele. Umožňuje sledovat rostoucí podíl těhotenství provázených diabetem.',
    metric_label: 'Porody', metric: { type: 'count' }, yearCol: 'rok_porodu', year_from: 2000,
    note: 'Jedna řádka = jeden porod (rodička). Příznak diabetu otevřená data uvádějí zjednodušeně jako ano/ne (zahrnuje cukrovku zjištěnou před těhotenstvím i v jeho průběhu, včetně těhotenské cukrovky). Podíl porodů s diabetem výrazně roste, což odráží jak skutečný nárůst, tak rozšíření vyšetřování těhotenských cukrovek.',
    dims: [
      { key: 'diabetes', label: 'Diabetes', kind: 'category', primary: true, col: 'diabetes', order: 'fixed',
        fixed: ['bez diabetu', 's diabetem'],
        valueMap: { '0': 'bez diabetu', '1': 's diabetem' } },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
      { key: 'typ_pzs', label: 'Typ poskytovatele', kind: 'category', col: 'typ_pzs', valueMap: { '1': 'poskytovatel základní úrovně', '2': 'perinatologické centrum intermediární péče', '3': 'perinatologické centrum intenzivní péče' } },
    ],
  },
  {
    id: 'rodicky_screening', src: 'https://data.mzcr.cz/data/distribuce/319/rodicky-screening.csv',
    source: 'Národní registr reprodukčního zdraví (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1619-rodicky-screening-otevrena-data',
    human_name: 'Rodičky — ultrazvukové screeningy v těhotenství',
    description: 'Interaktivní rozpad těhotenství podle toho, které ze tří doporučených ultrazvukových screeningů žena podstoupila (v 10.–13., 18.–22. a 27.–32. týdnu těhotenství), v členění podle věku matky. Jedna žena může mít víc vyšetření.',
    metric_label: 'Rodičky s daným ultrazvukem', metric: { type: 'wide' }, yearCol: 'rok_porodu', year_from: 2016, noAnomalies: true,
    note: 'Příznakové sloupce vyšetření (hodnota 1 = ano), jedna žena obvykle podstoupí víc vyšetření → počty napříč vyšetřeními nelze sčítat. Tato vyšetření registr eviduje až od roku 2016. Tři termíny odpovídají doporučenému screeningu: prvotrimestrální (10.–13. týden), morfologický (18.–22. týden) a růstový (27.–32. týden).',
    wideCauses: [
      { col: 'screening_uzv_10_13', name: 'ultrazvuk v 10.–13. týdnu' },
      { col: 'screening_uzv_18_22', name: 'ultrazvuk v 18.–22. týdnu' },
      { col: 'screening_uzv_27_32', name: 'ultrazvuk v 27.–32. týdnu' },
    ],
    dims: [
      { key: 'screening', label: 'Ultrazvukové vyšetření', kind: 'category', primary: true, wide: true },
      { key: 'vek_matky', label: 'Věk matky', kind: 'category', col: 'vek_matky', valueMap: { '1': 'do 19 let', '2': '20–24 let', '3': '25–29 let', '4': '30–34 let', '5': '35–39 let', '6': '40 a více let' } },
    ],
  },
  {
    id: 'urazy', src: 'https://data.mzcr.cz/data/distribuce/381/Otevrena-data-NR-16-01-urazy.csv.gz',
    source: 'Národní registr úrazů (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1786-urazy-otevrena-data',
    human_name: 'Úrazy — hospitalizační případy',
    description: 'Počty hospitalizací pro úraz, rozpadnutelné podle typu poranění (část těla, popáleniny, otravy…), věku a pohlaví. Jeden úraz může mít více typů poranění.',
    metric_label: 'Úrazy (hospitalizace)', metric: { type: 'wide' }, yearCol: 'rok', year_from: 2010,
    note: 'Typ poranění z příznakových sloupců MKN S00–T98. Jeden úraz může spadat do více typů (polytrauma).',
    wideCauses: [
      { col: 'S00_S09', name: 'poranění hlavy' }, { col: 'S10_S19', name: 'poranění krku' },
      { col: 'S20_S29', name: 'poranění hrudníku' }, { col: 'S30_S39', name: 'poranění břicha, zad a pánve' },
      { col: 'S40_S49', name: 'poranění ramene a paže' }, { col: 'S50_S59', name: 'poranění lokte a předloktí' },
      { col: 'S60_S69', name: 'poranění zápěstí a ruky' }, { col: 'S70_S79', name: 'poranění kyčle a stehna' },
      { col: 'S80_S89', name: 'poranění kolena a bérce' }, { col: 'S90_S99', name: 'poranění kotníku a nohy' },
      { col: 'T00_T07', name: 'mnohočetná poranění' }, { col: 'T08_T14', name: 'poranění neurčené části těla' },
      { col: 'T15_T19', name: 'cizí těleso v tělním otvoru' },
      { col: 'T20_T25', name: 'popáleniny' }, { col: 'T26_T28', name: 'popáleniny' }, { col: 'T29_T32', name: 'popáleniny' },
      { col: 'T33_T35', name: 'omrzliny' }, { col: 'T36_T50', name: 'otrava léky a návykovými látkami' },
      { col: 'T51_T65', name: 'toxické účinky nelékových látek' }, { col: 'T66_T78', name: 'jiné účinky vnějších příčin' },
      { col: 'T80_T88', name: 'komplikace zdravotní péče' }, { col: 'T90_T98', name: 'následky poranění a otrav' },
    ],
    dims: [
      { key: 'typ', label: 'Typ poranění', kind: 'category', primary: true, wide: true },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kod', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  {
    id: 'diabetes', src: 'https://data.mzcr.cz/data/distribuce/362/Otevrena-data-NR-18-01-diabetes-mellitus.csv.gz',
    source: 'Národní registr hrazených zdravotních služeb (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1768-diabetes-mellitus-epidemiologie-otevrena-data',
    human_name: 'Diabetes — pacienti podle typu léčby',
    description: 'Počty pacientů s diabetem podle typu léčby a používaných prostředků (antidiabetika, inzulínová pumpa, glukózové senzory), rozpadnutelné podle věku a pohlaví.',
    metric_label: 'Pacienti (case-years)', metric: { type: 'wide' }, yearCol: 'rok', year_from: 2013,
    note: 'Typy léčby z příznakových sloupců (pacient může mít více). Počítají se pacient-roky.',
    wideCauses: [
      { col: 'DM_antidiabetika', name: 'antidiabetika (léky)' },
      { col: 'DM_prostredky_IP', name: 'inzulínová pumpa' },
      { col: 'DM_prostredky_CGM', name: 'kontinuální monitor glykémie (CGM)' },
      { col: 'DM_prostredky_FGM', name: 'okamžitý monitor glykémie (FGM)' },
    ],
    dims: [
      { key: 'lecba', label: 'Typ léčby', kind: 'category', primary: true, wide: true },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek_kod', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  {
    id: 'leky_atc', src: 'https://datanzis.uzis.gov.cz/data/NR-04-NRHZS/NR-04-96/Otevrena-data-NR-04-96-hromadne-vyrabene-lecive-pripravky-2-uroven-atc.csv.gz',
    source: 'Národní registr hrazených zdravotních služeb (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/2759-hromadne-vyrabene-lecive-pripravky-2-uroven-atc-otevrena-data',
    human_name: 'Spotřeba léků podle skupiny (ATC)',
    description: 'Počty pacientů, kterým byl vydán hromadně vyráběný léčivý přípravek dané skupiny ATC (2. úroveň), rozpadnutelné podle skupiny léků, věku a pohlaví.',
    metric_label: 'Pacienti s vydaným lékem', metric: { type: 'sum', col: 'pocet_UOP' }, yearCol: 'rok', year_from: 2018,
    noAnomalies: true,
    note: 'Popisná data — bez skenu trendů (spotřebu léků silně ovlivňuje úhradová politika a kódování). Skupiny dle 2. úrovně ATC, metrika: počet unikátních ošetřených pacientů.',
    dims: [
      { key: 'skupina', label: 'Skupina léků', kind: 'category', primary: true, col: 'ATC_nazev', clean: 'lower', maxValues: 40 },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vek', decode: 'nor5' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX' },
    ],
  },
  {
    id: 'ockovani', src: 'https://data.mzcr.cz/data/distribuce/342/vakcinace-verejne-zdravotni-pojisteni.csv',
    source: 'Vykázané očkování z veřejného zdravotního pojištění (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/1701-vakcinace-verejne-zdravotni-pojisteni-otevrena-data',
    human_name: 'Očkování — vykázané dávky',
    description: 'Počty vykázaných očkovacích dávek hrazených z veřejného zdravotního pojištění, rozpadnutelné podle skupiny vakcíny, věku a pohlaví. Popisná data o stavu — slouží k odečtu počtů, ne k hledání trendů (počty silně ovlivňuje spouštění a rozšiřování očkovacích programů).',
    metric_label: 'Vykázané dávky', metric: { type: 'sum', col: 'pocet' }, yearCol: 'rok_vakcinace', year_from: 2011,
    noAnomalies: true,
    note: 'Bez skenu anomálií — počty dávek určuje hlavně spouštění programů, ne epidemiologie. Skupina vakcíny dle číselníku ÚZIS (číselný prefix odstraněn).',
    dims: [
      {
        key: 'vakcina', label: 'Skupina vakcíny', kind: 'category', primary: true, col: 'vakcina_skupina', clean: 'stripNumPrefix', maxValues: 40,
        relabel: {
          Chripka: 'chřipka', Tetanus: 'tetanus', Pneumokok: 'pneumokok', HPV: 'lidský papilomavirus (HPV)',
          MMR: 'spalničky, příušnice a zarděnky', Encefalitida: 'klíšťová encefalitida', Vzteklina: 'vzteklina',
          HepB: 'žloutenka typu B', HepA: 'žloutenka typu A', TBC: 'tuberkulóza',
          MeningokokB: 'meningokok skupiny B', MeningokokACWY: 'meningokok skupin A, C, W, Y',
          'InfluenzaB': 'hemofilus influenzae typu B', HEXA: 'hexavakcína (6 nemocí)', HEXA5: 'hexavakcína (6 nemocí)', HEXA10: 'hexavakcína (6 nemocí)',
        },
      },
      { key: 'age', label: 'Věk', kind: 'age', col: 'vekova_kategorie', decode: 'range' },
      { key: 'sex', label: 'Pohlaví', kind: 'category', col: 'pohlavi', map: 'SEX_MZ' },
    ],
  },
  {
    id: 'lazne_pacienti', src: 'https://datanzis.uzis.gov.cz/data/NR-04-NRHZS/NR-04-90/Otevrena-data-NR-04-90-lazenska-pece-pacienti.csv',
    source: 'Národní registr hrazených zdravotních služeb (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/2740-lazenska-pece-pacienti-otevrena-data',
    human_name: 'Lázeňská péče — pacienti',
    description: 'Počty pacientů v lázeňské léčebně rehabilitační péči, rozpadnutelné podle indikace (na co se léčí), věku, typu úhrady a kraje poskytovatele. Ukazuje mimo jiné, kolik péče plně hradí pojišťovna, kolik je příspěvkové a kolik si lidé platí sami.',
    metric_label: 'Pacienti v lázeňské péči', metric: { type: 'sum', col: 'pocet' }, yearCol: 'rok', year_from: 2015,
    noAnomalies: true,
    note: 'Popisná data — bez skenu trendů (počty silně ovlivňuje úhradová politika). Indikační skupiny sjednoceny pro dospělé i děti/dorost; kraj je sídlo poskytovatele lázní, ne bydliště pacienta.',
    dims: [
      { key: 'indikace', label: 'Indikace', kind: 'category', primary: true, col: 'indikace', valueMap: LAZNE_INDIKACE },
      { key: 'vek', label: 'Věk', kind: 'category', col: 'vek', order: 'fixed', fixed: ['Děti', 'Dorost', 'Dospělí'] },
      { key: 'uhrada', label: 'Typ úhrady', kind: 'category', col: 'typ', valueMap: LAZNE_TYP },
      { key: 'kraj', label: 'Kraj poskytovatele', kind: 'category', col: 'kraj_kod', valueMap: KRAJ },
    ],
  },
  {
    id: 'lazne_vykony', src: 'https://datanzis.uzis.gov.cz/data/SSS-07-A-VYKAZY/SSS-07-29/Otevrena-data-SSS-07-29-lazenska-pece-lecebne-vykony.csv',
    source: 'Výkazy zdravotní péče (ÚZIS ČR)', source_url: 'https://www.nzip.cz/data/2744-lazenska-pece-lecebne-vykony-otevrena-data',
    human_name: 'Lázeňská péče — léčebné výkony',
    description: 'Počty provedených léčebných výkonů v lázeňské péči (rehabilitace, vodoléčby a masáže, koupele, inhalace, peloidní a elektrofyzikální výkony…), rozpadnutelné podle druhu výkonu a kraje poskytovatele.',
    metric_label: 'Provedené léčebné výkony', metric: { type: 'sum', col: 'mnozstvi' }, yearCol: 'rok', year_from: 2015,
    noAnomalies: true,
    note: 'Popisná data — bez skenu trendů. Kraj je sídlo poskytovatele lázní.',
    dims: [
      { key: 'vykon', label: 'Druh výkonu', kind: 'category', primary: true, col: 'vykon', relabel: { 'elektrofyzikalní výkony': 'elektrofyzikální výkony', 'ostatní výkony s použitím PLZ': 'ostatní výkony s použitím přírodního léčivého zdroje' } },
      { key: 'kraj', label: 'Kraj poskytovatele', kind: 'category', col: 'kraj_kod', valueMap: KRAJ },
    ],
  },
];

const only = process.argv.slice(2);
for (const cfg of CONFIGS) {
  if (only.length && !only.includes(cfg.id)) continue;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try { await bakeOne(cfg); break; }
    catch (e) {
      console.log(`✗ ${cfg.id}: ${e.message}${attempt < 3 ? ' — zkouším znovu za 3 s' : ' — VZDÁVÁM po 3 pokusech'}`);
      if (attempt < 3) await new Promise(r => setTimeout(r, 3000));
    }
  }
}
