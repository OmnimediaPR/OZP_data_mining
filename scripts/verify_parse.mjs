// Ověření, že nová parseDataset logika (gzip + encoding + agregace) funguje.
// Napodobuje frontend/src/App.jsx proti reálným CSV ze zdroje.
import { gunzipSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const Papa = require(process.cwd() + '/frontend/node_modules/papaparse/papaparse.js');

const catalog = JSON.parse(readFileSync('data/catalog.json', 'utf-8'));
const byId = Object.fromEntries(catalog.datasets.map(d => [d.id, d]));

const TARGETS = process.argv.slice(2);

const stripBom = s => (s == null ? s : s.toString().replace(/^﻿/, ''));

function aggregate(rows, entry) {
  const yearCol = stripBom(entry.year_column);
  const dateCol = stripBom(entry.date_column);
  const valueCol = stripBom(entry.value_column);
  const agg = entry.aggregation;
  const dateBased = agg === 'date_to_year' || agg === 'last_in_year';
  const yearOf = (r) => {
    if (dateBased) {
      const m = (r[dateCol] || '').toString().match(/(\d{4})/);
      return m ? parseInt(m[1], 10) : NaN;
    }
    return parseInt((r[yearCol] || '').toString().trim(), 10);
  };
  const numOf = (r) => parseFloat((r[valueCol] || '').toString().replace(',', '.'));
  const grouped = {}, lastDate = {};
  for (const r of rows) {
    const year = yearOf(r);
    if (!Number.isFinite(year)) continue;
    if (agg === 'sum_column' || (agg === 'date_to_year' && valueCol)) {
      const v = numOf(r); if (Number.isFinite(v)) grouped[year] = (grouped[year] || 0) + v;
    } else if (agg === 'count_rows' || agg === 'date_to_year') {
      grouped[year] = (grouped[year] || 0) + 1;
    } else if (agg === 'last_in_year') {
      const v = numOf(r); if (!Number.isFinite(v)) continue;
      const d = (r[dateCol] || '').toString().trim();
      if (!(year in lastDate) || d > lastDate[year]) { lastDate[year] = d; grouped[year] = v; }
    }
  }
  return Object.entries(grouped)
    .map(([y, v]) => ({ year: parseInt(y, 10), value: agg === 'sum_column' ? Math.round(v) : v }))
    .sort((a, b) => a.year - b.year);
}

for (const id of TARGETS) {
  const entry = byId[id];
  if (!entry) { console.log(`\n### ${id}\n  CHYBÍ v katalogu`); continue; }
  const t0 = Date.now();
  try {
    const r = await fetch(entry.csv_url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    let buf = Buffer.from(await r.arrayBuffer());
    const dlMb = (buf.length / 1e6).toFixed(1);
    if (entry.csv_format === 'gzip') buf = gunzipSync(buf);
    const decMb = (buf.length / 1e6).toFixed(1);
    const enc = entry.csv_encoding === 'windows-1250' ? 'windows-1250' : 'utf-8';
    const text = new TextDecoder(enc).decode(buf);
    const parsed = Papa.parse(text, { header: true, skipEmptyLines: true, dynamicTyping: false });
    let rows = parsed.data;
    if (entry.filter_column) rows = rows.filter(x => (x[stripBom(entry.filter_column)] || '').toString().trim() !== '');
    const series = aggregate(rows, entry);
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    const head = series.slice(0, 2).map(p => `${p.year}:${p.value}`).join(' ');
    const tail = series.slice(-2).map(p => `${p.year}:${p.value}`).join(' ');
    console.log(`\n### ${id}  [${entry.aggregation}${entry.csv_format ? '+gzip' : ''}${entry.csv_encoding ? '+'+entry.csv_encoding : ''}]`);
    console.log(`  stáhnuto ${dlMb} MB → rozbaleno ${decMb} MB | řádků ${rows.length} | ${secs}s`);
    console.log(`  série: ${series.length} bodů | ${head} … ${tail}`);
    console.log(`  ${series.length >= 2 && series.every(p => Number.isFinite(p.value)) ? '✓ OK' : '✗ PODEZŘELÉ'}`);
  } catch (e) {
    console.log(`\n### ${id}\n  ✗ CHYBA: ${e.message}`);
  }
}
