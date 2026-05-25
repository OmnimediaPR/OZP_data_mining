// Napeče "rozpadové kostky" z onkologického registru NOR (config-driven; jedna konfigurace
// = jeden registr). Zatím onkologická INCIDENCE a ÚMRTNOST (stejná struktura: diagnoza_kod,
// kódovaný věk "66LLLUUU", pohlaví; incidence navíc stadium).
// Rozměry: rok × diagnóza × věk (5letá pásma) × pohlaví × stadium. Jen kurátorované primární
// diagnózy (vypadnou artefaktové kódy). Nehodgkinské lymfomy C82–C86 sloučeny (překlasifikace).
// Výstup: data/cubes/<id>.json (řídké buňky + metadata dimenzí + sken anomálií).
//
// Spuštění:  node --max-old-space-size=4096 scripts/bake_cube.mjs
import { Readable } from 'node:stream';
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const Papa = require(process.cwd() + '/frontend/node_modules/papaparse/papaparse.js');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124';
const YEAR_FROM = 2000;

const NHL = { key: 'NHL', name: 'nehodgkinský lymfom' };
const DG = {
  C15: { key: 'C15', name: 'zhoubný novotvar jícnu' },
  C16: { key: 'C16', name: 'zhoubný novotvar žaludku' },
  C18: { key: 'C18', name: 'zhoubný novotvar tlustého střeva' },
  C19: { key: 'C19', name: 'zhoubný novotvar rektosigmoideálního spojení' },
  C20: { key: 'C20', name: 'zhoubný novotvar konečníku' },
  C22: { key: 'C22', name: 'zhoubný novotvar jater' },
  C25: { key: 'C25', name: 'zhoubný novotvar slinivky břišní' },
  C32: { key: 'C32', name: 'zhoubný novotvar hrtanu' },
  C34: { key: 'C34', name: 'zhoubný novotvar průdušky a plíce' },
  C43: { key: 'C43', name: 'zhoubný melanom kůže' },
  C44: { key: 'C44', name: 'jiný zhoubný novotvar kůže' },
  C50: { key: 'C50', name: 'zhoubný novotvar prsu' },
  C53: { key: 'C53', name: 'zhoubný novotvar děložního hrdla' },
  C54: { key: 'C54', name: 'zhoubný novotvar těla děložního' },
  C56: { key: 'C56', name: 'zhoubný novotvar vaječníku' },
  C61: { key: 'C61', name: 'zhoubný novotvar předstojné žlázy' },
  C62: { key: 'C62', name: 'zhoubný novotvar varlete' },
  C64: { key: 'C64', name: 'zhoubný novotvar ledviny' },
  C67: { key: 'C67', name: 'zhoubný novotvar močového měchýře' },
  C71: { key: 'C71', name: 'zhoubný novotvar mozku' },
  C73: { key: 'C73', name: 'zhoubný novotvar štítné žlázy' },
  C81: { key: 'C81', name: 'Hodgkinův lymfom' },
  C82: NHL, C83: NHL, C84: NHL, C85: NHL, C86: NHL,
  C90: { key: 'C90', name: 'mnohočetný myelom' },
  C91: { key: 'C91', name: 'lymfatická leukémie' },
  C92: { key: 'C92', name: 'myeloidní leukémie' },
};
const dgNameByKey = {};
for (const v of Object.values(DG)) dgNameByKey[v.key] = v.name;

const ageBandStart = (code) => {
  const low = parseInt((code || '').toString().slice(2, 5), 10);
  return Number.isFinite(low) ? Math.floor(low / 5) * 5 : null;
};
const ageLabel = (s) => (s >= 85 ? '85 a více' : `${s}–${s + 4}`);
const STAGE = (v) => { const s = (v || '').toString().replace(/"/g, '').trim(); return ['1', '2', '3', '4'].includes(s) ? ['', 'I', 'II', 'III', 'IV'][+s] : 'neuvedeno'; };
const SEX = (v) => (v === '1' ? 'muž' : v === '2' ? 'žena' : null);

const CONFIGS = [
  {
    id: 'onkologie_incidence',
    src: 'https://data.mzcr.cz/data/distribuce/372/Otevrena-data-NR-07-01-incidence-prevalence-zhoubne-nadory-regiony-cr-2024-01.csv',
    source_url: 'https://www.nzip.cz/data/2054-incidence-prevalence-zhoubne-nadory',
    human_name: 'Onkologie — nově diagnostikované zhoubné nádory',
    description: 'Počty nově diagnostikovaných zhoubných nádorů v Česku z Národního onkologického registru, rozpadnutelné podle diagnózy, věku, pohlaví a stadia při záchytu.',
    metric_label: 'Nově diagnostikované případy',
    yearCol: 'rok_dg', ageCol: 'vek_kategorie_kod_dg', hasStage: true,
    note: 'Kurátorované primární diagnózy. Nehodgkinské lymfomy (C82–C86) sloučeny. Stadium III+IV = pozdní záchyt; „neuvedeno" je u některých diagnóz (mozek) převažující.',
  },
  {
    id: 'onkologie_umrti',
    src: 'https://data.mzcr.cz/data/distribuce/377/Otevrena-data-NR-07-02-mortalita-zhoubne-nadory-regiony-cr-2024-01.csv',
    source_url: 'https://www.nzip.cz/data/2056-mortalita-zhoubne-nadory',
    human_name: 'Onkologie — úmrtí na zhoubné nádory',
    description: 'Počty úmrtí na zhoubné nádory v Česku z Národního onkologického registru, rozpadnutelné podle diagnózy, věku a pohlaví.',
    metric_label: 'Úmrtí',
    yearCol: 'umrti_rok', ageCol: 'umrti_vek_kategorie_kod', hasStage: false,
    note: 'Kurátorované primární diagnózy. Nehodgkinské lymfomy (C82–C86) sloučeny. Bez stadia (registr úmrtí ho neeviduje).',
  },
];

async function bakeOne(cfg) {
  const counts = new Map();
  const dgTotal = {};
  let nRows = 0, nUsed = 0;
  const r = await fetch(cfg.src, { headers: { 'User-Agent': UA } });
  if (!r.ok) throw new Error(`${cfg.id}: HTTP ${r.status}`);
  const ns = Readable.fromWeb(r.body); ns.setEncoding('utf8');
  const t0 = Date.now();
  await new Promise((res, rej) => Papa.parse(ns, {
    header: true, skipEmptyLines: true,
    step: ({ data: x }) => {
      nRows++;
      const d = DG[(x.diagnoza_kod || '').toString().slice(0, 3)]; if (!d) return;
      const y = parseInt((x[cfg.yearCol] || '').toString(), 10); if (!Number.isFinite(y) || y < YEAR_FROM) return;
      const a = ageBandStart(x[cfg.ageCol]); if (a == null) return;
      const sex = SEX((x.pohlavi || '').toString()); if (!sex) return;
      const st = cfg.hasStage ? STAGE(x.stadium) : 'neuvedeno';
      const key = `${y}|${d.key}|${a}|${sex}|${st}`;
      counts.set(key, (counts.get(key) || 0) + 1);
      dgTotal[d.key] = (dgTotal[d.key] || 0) + 1; nUsed++;
    }, complete: res, error: rej,
  }));

  const diagnosis = Object.keys(dgTotal).sort((a, b) => dgTotal[b] - dgTotal[a]).map(k => ({ key: k, name: dgNameByKey[k] }));
  const ageStarts = [...new Set([...counts.keys()].map(k => +k.split('|')[2]))].sort((a, b) => a - b);
  const age = ageStarts.map(ageLabel);
  const sexDim = ['muž', 'žena'];
  const stageDim = cfg.hasStage ? ['I', 'II', 'III', 'IV', 'neuvedeno'] : ['neuvedeno'];
  const years = [...new Set([...counts.keys()].map(k => +k.split('|')[0]))].sort((a, b) => a - b);
  const di = Object.fromEntries(diagnosis.map((d, i) => [d.key, i]));
  const ai = Object.fromEntries(ageStarts.map((s, i) => [s, i]));
  const yi = Object.fromEntries(years.map((y, i) => [y, i]));
  const sxi = Object.fromEntries(sexDim.map((s, i) => [s, i]));
  const sti = Object.fromEntries(stageDim.map((s, i) => [s, i]));
  const cells = [];
  for (const [k, n] of counts) { const [y, dk, a, sex, st] = k.split('|'); cells.push([yi[+y], di[dk], ai[+a], sxi[sex], sti[st], n]); }

  // ---- anomálie ----
  const BASE = [2011, 2012, 2013].filter(y => years.includes(y));
  const REC = [2020, 2021, 2022].filter(y => years.includes(y));
  const byDgYear = {}, byDgPerYoung = {}, byDgPerLate = {};
  for (const [k, n] of counts) {
    const [y, dk, a, , st] = k.split('|'); const Y = +y, A = +a;
    (byDgYear[dk] = byDgYear[dk] || {})[Y] = (byDgYear[dk][Y] || 0) + n;
    const per = BASE.includes(Y) ? 'b' : REC.includes(Y) ? 'r' : null;
    if (per) {
      const yo = byDgPerYoung[dk] = byDgPerYoung[dk] || { b: { t: 0, y: 0 }, r: { t: 0, y: 0 } };
      yo[per].t += n; if (A < 50) yo[per].y += n;
      if (cfg.hasStage) {
        const la = byDgPerLate[dk] = byDgPerLate[dk] || { b: { staged: 0, late: 0 }, r: { staged: 0, late: 0 } };
        if (st === 'III' || st === 'IV') { la[per].staged += n; la[per].late += n; }
        else if (st === 'I' || st === 'II') la[per].staged += n;
      }
    }
  }
  const avg = (o, ys) => ys.reduce((s, y) => s + (o[y] || 0), 0) / (ys.length || 1);
  const maxJump = (o) => { let m = 0; for (let i = 1; i < years.length; i++) { const a = o[years[i - 1]] || 0, b = o[years[i]] || 0; if (a >= 30) m = Math.max(m, Math.abs((b - a) / a)); } return m; };
  const anomalies = [];
  for (const d of diagnosis) {
    const k = d.key;
    const b = avg(byDgYear[k], BASE), rc = avg(byDgYear[k], REC);
    if (rc >= 150 && b > 0) { const pct = Math.round((rc - b) / b * 100); if (Math.abs(pct) >= 15) anomalies.push({ type: 'trend', dg: k, name: d.name, pct, from: Math.round(b), to: Math.round(rc), artifact_risk: maxJump(byDgYear[k]) > 0.35 }); }
    const yo = byDgPerYoung[k];
    if (yo && yo.r.t >= 800) { const sb = yo.b.t ? yo.b.y / yo.b.t * 100 : 0, sr = yo.r.t ? yo.r.y / yo.r.t * 100 : 0; if (Math.abs(sr - sb) >= 2.5) anomalies.push({ type: 'vek_posun', dg: k, name: d.name, from_pct: +sb.toFixed(1), to_pct: +sr.toFixed(1), diff: +(sr - sb).toFixed(1) }); }
    const la = byDgPerLate[k];
    if (la && la.r.staged >= 400) { const lb = la.b.staged ? la.b.late / la.b.staged * 100 : 0, lr = la.r.staged ? la.r.late / la.r.staged * 100 : 0; if (Math.abs(lr - lb) >= 3) anomalies.push({ type: 'stadium_posun', dg: k, name: d.name, from_pct: +lb.toFixed(1), to_pct: +lr.toFixed(1), diff: +(lr - lb).toFixed(1) }); }
  }
  const byType = (t) => anomalies.filter(a => a.type === t).sort((a, b) => Math.abs(b.diff ?? b.pct) - Math.abs(a.diff ?? a.pct));
  const tr = byType('trend'), ve = byType('vek_posun'), st2 = byType('stadium_posun');
  const mixed = [];
  for (let i = 0; i < Math.max(tr.length, ve.length, st2.length); i++) { if (tr[i]) mixed.push(tr[i]); if (ve[i]) mixed.push(ve[i]); if (st2[i]) mixed.push(st2[i]); }

  const cube = {
    id: cfg.id, human_name: cfg.human_name, description: cfg.description,
    source: 'Národní onkologický registr (ÚZIS ČR)', source_url: cfg.source_url,
    metric_label: cfg.metric_label, baked_at: new Date().toISOString().slice(0, 10), note: cfg.note,
    dims: { diagnosis, age, sex: sexDim, stage: stageDim, years }, cells, anomalies: mixed,
  };
  mkdirSync('data/cubes', { recursive: true });
  writeFileSync(`data/cubes/${cfg.id}.json`, JSON.stringify(cube) + '\n');
  const secs = ((Date.now() - t0) / 1000).toFixed(0);
  console.log(`✓ ${cfg.id}: ${nUsed.toLocaleString()}/${nRows.toLocaleString()} řádků, ${diagnosis.length} dg, ${cells.length.toLocaleString()} buněk, ${(JSON.stringify(cube).length / 1024).toFixed(0)} KB, ${secs}s, ${mixed.length} anomálií`);
  return mixed.slice(0, 6);
}

for (const cfg of CONFIGS) {
  const top = await bakeOne(cfg);
  for (const a of top) {
    if (a.type === 'trend') console.log(`    [trend] ${a.pct > 0 ? '+' : ''}${a.pct}% ${a.name}${a.artifact_risk ? ' ⚠' : ''}`);
    if (a.type === 'vek_posun') console.log(`    [věk] ${a.diff > 0 ? '+' : ''}${a.diff} b.b. <50 ${a.name}`);
    if (a.type === 'stadium_posun') console.log(`    [stadium] ${a.diff > 0 ? '+' : ''}${a.diff} b.b. pozdní ${a.name}`);
  }
}
