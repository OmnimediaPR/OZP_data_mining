// Předpočítá časové řady pro všechny datasety v katalogu a zapíše je do data/catalog.json
// jako pole `series` ([{year, value}]). Frontend pak nemusí stahovat velké CSV v prohlížeči —
// kartu i analýzu postaví z těchto pár čísel okamžitě.
//
// Logika stahování + agregace je shodná s frontend/src/App.jsx parseDataset a s verify_parse.mjs
// (záměrně, ať se výpočet v prohlížeči a ve skriptu nerozejde).
//
// Spuštění:  node --max-old-space-size=4096 scripts/bake_series.mjs
// Re-bake (refresh): stačí pustit znovu, řady se přepíšou aktuálními.
import { gunzipSync, createGunzip } from 'node:zlib';
import { readFileSync, writeFileSync } from 'node:fs';
import { Readable } from 'node:stream';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const Papa = require(process.cwd() + '/frontend/node_modules/papaparse/papaparse.js');

// Běžný prohlížečový User-Agent — WAF ÚZIS blokuje "HeadlessChrome"/node default.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const TIMEOUT_MS = 180000;        // velké soubory (NOR ~197 MB) potřebují čas
const TIMEOUT_STREAM_MS = 540000; // obří streamované soubory (covid 1,4 GB)
const CONCURRENCY = 10;

const stripBom = s => (s == null ? s : s.toString().replace(/^﻿/, ''));

// Per-řádkové filtry + krok agregace — sdílené buffer i stream cestou, ať se nerozejdou.
// Zrcadlí frontend parseDataset (filter_column → row_match → agregace).
function makeAccumulator(entry) {
  const yearCol = stripBom(entry.year_column);
  const dateCol = stripBom(entry.date_column);
  const valueCol = stripBom(entry.value_column);
  const agg = entry.aggregation;
  const dateBased = agg === 'date_to_year' || agg === 'last_in_year';
  const filterCol = entry.filter_column ? stripBom(entry.filter_column) : null;
  const rmCol = entry.row_match ? stripBom(entry.row_match.column) : null;
  const rmPref = entry.row_match ? (Array.isArray(entry.row_match.prefix) ? entry.row_match.prefix : [entry.row_match.prefix]) : null;
  const yearOf = (x) => {
    if (dateBased) { const m = (x[dateCol] || '').toString().match(/(\d{4})/); return m ? parseInt(m[1], 10) : NaN; }
    return parseInt((x[yearCol] || '').toString().trim(), 10);
  };
  const numOf = (x) => parseFloat((x[valueCol] || '').toString().replace(',', '.'));
  const grouped = {}, lastDate = {};
  return {
    add(x) {
      if (filterCol && (x[filterCol] || '').toString().trim() === '') return;
      if (rmCol && !rmPref.some(p => (x[rmCol] || '').toString().startsWith(p))) return;
      const year = yearOf(x);
      if (!Number.isFinite(year)) return;
      if (agg === 'sum_column' || (agg === 'date_to_year' && valueCol)) {
        const v = numOf(x); if (Number.isFinite(v)) grouped[year] = (grouped[year] || 0) + v;
      } else if (agg === 'count_rows' || agg === 'date_to_year') {
        grouped[year] = (grouped[year] || 0) + 1;
      } else if (agg === 'last_in_year') {
        const v = numOf(x); if (!Number.isFinite(v)) return;
        const d = (x[dateCol] || '').toString().trim();
        if (!(year in lastDate) || d > lastDate[year]) { lastDate[year] = d; grouped[year] = v; }
      }
    },
    result() {
      return Object.entries(grouped)
        .map(([y, v]) => ({ year: parseInt(y, 10), value: agg === 'sum_column' ? Math.round(v) : v }))
        .sort((a, b) => a.year - b.year);
    },
  };
}

// Standardní cesta: stáhne celé CSV do paměti a naparsuje. Pro soubory do ~500 MB.
async function bufferSeries(entry) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(entry.csv_url, { headers: { 'User-Agent': UA }, signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    // Obří soubory (přes 500 MB) se nevejdou do paměti — signál pro stream cestu.
    // Throwneme dřív, než stáhneme tělo (fetch má hlavičky hned), ať se nestahuje zbytečně.
    const len = parseInt(r.headers.get('content-length') || '0', 10);
    if (len > 500e6) throw new Error(`TOO_BIG ${(len / 1e6).toFixed(0)}`);
    let buf = Buffer.from(await r.arrayBuffer());
    const mb = (buf.length / 1e6).toFixed(1) + ' MB';
    if (entry.csv_format === 'gzip') buf = gunzipSync(buf);
    const enc = entry.csv_encoding === 'windows-1250' ? 'windows-1250' : 'utf-8';
    const text = new TextDecoder(enc).decode(buf);
    const parsed = Papa.parse(text, { header: true, skipEmptyLines: true, dynamicTyping: false });
    const acc = makeAccumulator(entry);
    for (const row of parsed.data) acc.add(row);
    const series = acc.result();
    if (series.length < 1) throw new Error('prázdná série (0 bodů po agregaci)');
    return { series, info: mb };
  } finally { clearTimeout(timer); }
}

// Stream cesta: parsuje po řádcích s konstantní pamětí. Pro obří soubory (covid 1,4 GB).
async function streamSeries(entry) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_STREAM_MS);
  try {
    const r = await fetch(entry.csv_url, { headers: { 'User-Agent': UA }, signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    let ns = Readable.fromWeb(r.body);
    if (entry.csv_format === 'gzip') ns = ns.pipe(createGunzip());
    // setEncoding ošetří dělení vícebajtových znaků na hranicích chunků.
    ns.setEncoding(entry.csv_encoding === 'windows-1250' ? 'latin1' : 'utf8');
    const acc = makeAccumulator(entry);
    await new Promise((resolve, reject) => {
      Papa.parse(ns, {
        header: true, skipEmptyLines: true, dynamicTyping: false,
        step: (res) => acc.add(res.data),
        complete: resolve,
        error: reject,
      });
    });
    const series = acc.result();
    if (series.length < 1) throw new Error('prázdná série (0 bodů po agregaci)');
    return { series, info: 'streamováno' };
  } finally { clearTimeout(timer); }
}

// Vybere cestu: zkusí buffer; když je soubor moc velký, přepne na streaming
// (signál TOO_BIG přijde dřív, než se cokoli velkého stáhne).
async function computeSeries(entry) {
  try {
    return await bufferSeries(entry);
  } catch (e) {
    if (e.message?.startsWith('TOO_BIG')) {
      console.log(`  ↳ ${entry.id}: ${e.message.split(' ')[1]} MB → streamuji`);
      return await streamSeries(entry);
    }
    throw e;
  }
}

const RETRIES = 3;        // počet pokusů na dataset (řeší dočasné výpadky)
const RETRY_DELAY_MS = 2000;
const FORCE = process.argv.includes('--force'); // přepočítat i už hotové

const catalog = JSON.parse(readFileSync('data/catalog.json', 'utf-8'));
catalog.schema_version = '2.2';
if (catalog.schema_notes?.fields) {
  catalog.schema_notes.fields.series = 'předpočítaná časová řada [{year, value}] (scripts/bake_series.mjs); pokud chybí, frontend stáhne CSV živě';
}
const ds = catalog.datasets;
const results = [];
let idx = 0;

// Průběžné ukládání — skript je přerušitelný, re-run přeskočí už hotové (mají series).
// Node je jednovláknový, writeFileSync z více workerů se neprokládá.
function save() {
  catalog.updated = new Date().toISOString().slice(0, 10);
  writeFileSync('data/catalog.json', JSON.stringify(catalog, null, 2) + '\n');
}

async function worker() {
  while (idx < ds.length) {
    const i = idx++;
    const e = ds[i];
    if (e.series && !FORCE) { console.log(`• ${e.id}: už hotovo, přeskakuji`); continue; }
    const t0 = Date.now();
    let lastErr;
    for (let attempt = 1; attempt <= RETRIES; attempt++) {
      try {
        const { series, info } = await computeSeries(e);
        e.series = series;
        save();
        const secs = ((Date.now() - t0) / 1000).toFixed(1);
        results.push({ id: e.id, ok: true });
        console.log(`✓ ${e.id}: ${series.length} bodů (${info}, ${secs}s${attempt > 1 ? `, pokus ${attempt}` : ''})`);
        lastErr = null;
        break;
      } catch (err) {
        lastErr = err.name === 'AbortError' ? `timeout >${TIMEOUT_MS / 1000}s` : err.message;
        if (attempt < RETRIES) await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
      }
    }
    if (lastErr) {
      delete e.series;
      save();
      results.push({ id: e.id, ok: false, err: lastErr });
      console.log(`✗ ${e.id}: ${lastErr} (${RETRIES} pokusy)`);
    }
  }
}

await Promise.all(Array.from({ length: CONCURRENCY }, worker));
save();

const ok = results.filter(r => r.ok);
const bad = results.filter(r => !r.ok);
const baked = ds.filter(d => d.series).length;
console.log(`\n=== HOTOVO: ${ok.length} nově OK, ${bad.length} selhalo | celkem s daty ${baked}/${ds.length} ===`);
if (bad.length) console.log('Selhalo:\n' + bad.map(r => `  ${r.id}: ${r.err}`).join('\n'));
