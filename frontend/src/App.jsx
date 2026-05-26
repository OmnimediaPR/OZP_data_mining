import React, { useState, useEffect, useMemo } from 'react';
import { LineChart, Line, ResponsiveContainer, ReferenceDot } from 'recharts';
import { ChevronRight, Check, Loader2, Sparkles, Key, X, Download } from 'lucide-react';
import {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, ShadingType, BorderStyle, WidthType,
} from 'docx';
import { saveAs } from 'file-saver';
import Papa from 'papaparse';
import ozpLogo from './assets/ozp-logo.svg';

// ============================================================
// ON-DEMAND DATA FETCH (KROK 3 nové architektury)
// CSV se stahuje až ve chvíli, kdy uživatel dataset vybere.
// Cache je per csv_url, takže NOR (5 dg sdílí 197 MB CSV) se stáhne jednou.
// ============================================================

const csvCache = new Map(); // url → Promise<csvText>

// Stáhne a dekóduje CSV. Rozbalí gzip (server posílá .csv.gz bez hlavičky
// Content-Encoding, prohlížeč ho proto sám nerozbalí) a dekóduje podle
// csv_encoding (default UTF-8, u některých sad windows-1250). TextDecoder
// zároveň odstraní případný BOM na začátku hlavičky.
async function fetchAndDecode(entry) {
  const r = await fetch(entry.csv_url);
  if (!r.ok) throw new Error(`HTTP ${r.status} pro ${entry.csv_url}`);
  let buf = await r.arrayBuffer();
  if (entry.csv_format === 'gzip') {
    const stream = new Response(buf).body.pipeThrough(new DecompressionStream('gzip'));
    buf = await new Response(stream).arrayBuffer();
  }
  const encoding = entry.csv_encoding === 'windows-1250' ? 'windows-1250' : 'utf-8';
  return new TextDecoder(encoding).decode(buf);
}

function fetchCsvCached(entry) {
  const url = entry.csv_url;
  if (csvCache.has(url)) return csvCache.get(url);
  const promise = fetchAndDecode(entry).catch(e => {
    csvCache.delete(url); // umožni retry po chybě
    throw e;
  });
  csvCache.set(url, promise);
  return promise;
}

// Postaví časovou řadu [{year, value}]. Primárně z předpočítané řady v katalogu
// (scripts/bake_series.mjs) — pak prohlížeč nestahuje žádné CSV. Pokud řada chybí
// (např. čerstvě přidaný dataset), spadne zpět na živé stažení a parse CSV ze zdroje.
async function parseDataset(entry) {
  if (Array.isArray(entry.series) && entry.series.length > 0) return entry.series;
  const csvText = await fetchCsvCached(entry);
  const parsed = Papa.parse(csvText, {
    header: true,
    skipEmptyLines: true,
    dynamicTyping: false,
  });
  if (parsed.errors.length > 5) {
    console.warn(`Papa parse warnings pro ${entry.id}:`, parsed.errors.slice(0, 3));
  }
  let rows = parsed.data;

  // Filter 1: NKIS-style non-empty filter (subtotal rows mají prázdný okres_bydliste).
  if (entry.filter_column) {
    rows = rows.filter(r => (r[entry.filter_column] || '').toString().trim() !== '');
  }

  // Filter 2: NOR-style match na konkrétní hodnotu (diagnoza_kod prefix).
  if (entry.row_match) {
    const { column, prefix } = entry.row_match;
    const prefixes = Array.isArray(prefix) ? prefix : [prefix];
    rows = rows.filter(r => {
      const val = (r[column] || '').toString();
      return prefixes.some(p => val.startsWith(p));
    });
  }

  // Agregace per rok. Rok bereme z year_column, u date_* agregací z date_column.
  // stripBom: katalog má u některých sloupců BOM (např. covid "﻿datum"), ale
  // TextDecoder ho z hlaviček odstraní — názvy z katalogu proto taky očistíme.
  const stripBom = s => (s == null ? s : s.toString().replace(/^﻿/, ''));
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

  const grouped = {};
  const lastDate = {}; // pro last_in_year: nejpozdější datum v daném roce
  for (const r of rows) {
    const year = yearOf(r);
    if (!Number.isFinite(year)) continue;

    if (agg === 'sum_column' || (agg === 'date_to_year' && valueCol)) {
      const v = numOf(r);
      if (Number.isFinite(v)) grouped[year] = (grouped[year] || 0) + v;
    } else if (agg === 'count_rows' || agg === 'date_to_year') {
      grouped[year] = (grouped[year] || 0) + 1;
    } else if (agg === 'last_in_year') {
      const v = numOf(r);
      if (!Number.isFinite(v)) continue;
      const d = (r[dateCol] || '').toString().trim();
      if (!(year in lastDate) || d > lastDate[year]) {
        lastDate[year] = d;
        grouped[year] = v;
      }
    }
  }
  return Object.entries(grouped)
    .map(([y, v]) => ({ year: parseInt(y, 10), value: agg === 'sum_column' ? Math.round(v) : v }))
    .sort((a, b) => a.year - b.year);
}

// Spočítá trend/delta/peakYear v %. Mirror logiky z scripts/sync_nor.py compute_meta.
function computeMeta(series) {
  if (!series || series.length < 2) return { trend: 'unknown', delta: 0, peakYear: null };
  const sorted = [...series].sort((a, b) => a.year - b.year);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const peak = sorted.reduce((m, x) => x.value > m.value ? x : m, sorted[0]);
  if (first.value === 0) return { trend: 'unknown', delta: 0, peakYear: peak.year };
  const delta = Math.round(((last.value - first.value) / first.value) * 100);
  let trend = 'flat';
  if (delta > 10) trend = 'up';
  else if (delta < -10) trend = 'down';
  return { trend, delta, peakYear: peak.year };
}

// ============================================================
// ROZPADOVÁ KOSTKA (kind: 'cube')
// Kostka drží řídké buňky [yearIdx, dgIdx, ageIdx, sexIdx, stageIdx, count] + metadata
// dimenzí + předpočítaný sken anomálií (scripts/bake_cube.mjs). Stáhne se až po výběru,
// pak se "krájí" lokálně podle filtru bez dalšího stahování.
// ============================================================

const cubeCache = new Map(); // url → Promise<cube>
function fetchCubeCached(entry) {
  const url = import.meta.env.BASE_URL + entry.cube_url;
  if (cubeCache.has(url)) return cubeCache.get(url);
  const p = fetch(url)
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .catch(e => { cubeCache.delete(url); throw e; });
  cubeCache.set(url, p);
  return p;
}

// Kostka má OBECNÉ dimenze: cube.dims = [{key,label,kind:'category'|'age',values,primary?}].
// Filtr = { [dimKey]: 'vše' | hodnota | 'pozdní (III+IV)' | věkové pásmo }. Buňka = [yearIdx, ...dimIdx, count].
const DEFAULT_CUBE_FILTER = {};
const valKey = (v) => (v && typeof v === 'object') ? v.key : v;
const valName = (v) => (v && typeof v === 'object') ? v.name : v;
function ageMatch(mode, low) {
  if (mode === 'do 50') return low < 50;
  if (mode === '50–64') return low >= 50 && low < 65;
  if (mode === '65+') return low >= 65;
  return true;
}
function dimMatches(dim, idx, sel) {
  if (sel == null || sel === 'vše') return true;
  if (dim.kind === 'age') return ageMatch(sel, dim.values[idx]);
  const v = valKey(dim.values[idx]);
  if (sel === 'pozdní (III+IV)') return v === 'III' || v === 'IV';
  return v === sel;
}

// Sečte buňky odpovídající filtru → časová řada [{year, value}].
function sliceCube(cube, f = DEFAULT_CUBE_FILTER) {
  const byYear = {};
  for (const cell of cube.cells) {
    let ok = true;
    for (let d = 0; d < cube.dims.length; d++) {
      if (!dimMatches(cube.dims[d], cell[d + 1], f[cube.dims[d].key])) { ok = false; break; }
    }
    if (!ok) continue;
    const y = cube.years[cell[0]];
    byYear[y] = (byYear[y] || 0) + cell[cell.length - 1];
  }
  return cube.years.filter(y => y in byYear).map(y => ({ year: y, value: byYear[y] }));
}

// Lidský popis filtru — pro nadpis karty, analýzu i brief.
function cubeFilterLabel(cube, f = {}) {
  const parts = [];
  for (const dim of cube.dims) {
    const sel = f[dim.key];
    if (!sel || sel === 'vše') continue;
    if (dim.kind === 'age') parts.push(sel === 'do 50' ? 'mladší 50 let' : `${sel} let`);
    else if (sel === 'pozdní (III+IV)') parts.push('pozdní záchyt (stadium III+IV)');
    else parts.push(valName(dim.values.find(v => valKey(v) === sel)) || sel);
  }
  if (parts.length) return parts.join(', ');
  const p = cube.dims.find(d => d.primary);
  return p ? `všechny ${p.label.toLowerCase()}` : 'celkem';
}

// Filtr, který demonstruje danou anomálii (klik na anomálii ho nastaví).
function anomalyToFilter(cube, a) {
  const primary = cube.dims.find(d => d.primary)?.key;
  const ageKey = cube.dims.find(d => d.kind === 'age')?.key;
  const stageKey = cube.dims.find(d => Array.isArray(d.values) && d.values.some(v => valKey(v) === 'III'))?.key;
  const f = {};
  if (primary) f[primary] = a.dg;
  if (a.type === 'vek_posun' && ageKey) f[ageKey] = 'do 50';
  if (a.type === 'stadium_posun' && stageKey) f[stageKey] = 'pozdní (III+IV)';
  return f;
}

// ============================================================
// KONSTANTY
// ============================================================

// Nástroj je pro jednoho klienta — OZP. Dřív tu bylo vybírací menu klientů, ale nemělo
// žádnou funkci. Hodnotu držíme napevno (potřebuje ji text briefu, hlavička .docx i název souboru).
const CLIENT = { id: 'ozp', full: 'Oborová zdravotní pojišťovna' };

// Mezinárodní datasety jsou statické (data pomalu se měnící, ukládáme rovnou).
// Národní (NKIS) se načítají z /data/nkis/*.json soubory generované GitHub Actions.
const INTL_DATASETS = [
  {
    id: 'eu_cvd_share',
    label: 'Podíl KVO na všech úmrtích — EU srovnání',
    human_name: 'Podíl srdečních a cévních úmrtí (EU srovnání)',
    description: 'Kolik procent všech úmrtí způsobí kardiovaskulární onemocnění — pozice ČR v rámci EU.',
    code: 'hlth_cd_aro',
    source: 'Eurostat', source_type: 'international', updated: '7/2025', coverage: '2022',
    source_url: 'https://ec.europa.eu/eurostat/databrowser/view/hlth_cd_aro/default/table',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'celkový pohled'],
    data: [
      { year: 2018, value: 35.4 }, { year: 2019, value: 34.8 }, { year: 2020, value: 33.5 },
      { year: 2021, value: 32.1 }, { year: 2022, value: 32.7 },
    ],
    comparison: [
      { country: 'Bulharsko', value: 61, hi: true },
      { country: 'Rumunsko', value: 56, hi: true },
      { country: 'ČR', value: 38, hi: true, isUs: true },
      { country: 'EU průměr', value: 32.7 },
      { country: 'Nizozemsko', value: 24 },
      { country: 'Francie', value: 20.5 },
    ],
    trend_context: 'EU 27 průměr 32,7 % všech úmrtí; ČR ve středovýchodní zóně vysokého rizika. Srovnatelná metodika napříč státy (Eurostat hlth_cd_aro), stejný rok.'
  },
  {
    id: 'eu_cancer_mortality_sdr',
    label: 'Úmrtnost na novotvary — EU srovnání',
    human_name: 'Standardizovaná úmrtnost na rakovinu (EU srovnání)',
    description: 'Standardizovaná úmrtnost na všechny novotvary na 100 tisíc obyvatel — porovnání ČR s evropskými zeměmi. Standardizace vyrovnává rozdíly ve věkové struktuře populace, takže čísla jsou srovnatelná napříč státy.',
    code: 'hlth_cd_asdr2 (C00–C97)',
    source: 'Eurostat', source_type: 'international', updated: '2024 (data 2022)', coverage: '2022',
    source_url: 'https://ec.europa.eu/eurostat/databrowser/view/hlth_cd_asdr2/default/table',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'onkologie', 'mortalita', 'veřejné zdraví'],
    data: [
      { year: 2018, value: 295 }, { year: 2019, value: 285 }, { year: 2020, value: 275 },
      { year: 2021, value: 270 }, { year: 2022, value: 270 },
    ],
    comparison: [
      { country: 'Maďarsko', value: 295, hi: true },
      { country: 'Polsko', value: 280, hi: true },
      { country: 'Slovensko', value: 275, hi: true },
      { country: 'ČR', value: 270, hi: true, isUs: true },
      { country: 'EU průměr', value: 245 },
      { country: 'Itálie', value: 215 },
      { country: 'Švédsko', value: 200 },
    ],
    trend_context: 'Středovýchodní Evropa (Polsko, Maďarsko, Slovensko, ČR) má dlouhodobě nadprůměrnou úmrtnost na rakovinu — odraz historicky vyšší míry kouření, dietních zvyklostí, alkoholu a pomalejšího rozjezdu screeningových programů. Pozn.: čísla jsou orientační, přesné hodnoty viz Eurostat hlth_cd_asdr2.'
  },
  {
    id: 'oecd_prsa_preziti',
    label: 'Rakovina prsu — 5leté přežití — OECD srovnání',
    human_name: '5leté přežití u rakoviny prsu (OECD srovnání)',
    description: 'Procento pacientek, které žijí 5 a více let po diagnóze rakoviny prsu. Porovnání ČR s vyspělými zeměmi.',
    code: 'OECD Cancer Care (2024)',
    source: 'OECD Health at a Glance', source_type: 'international', updated: '2024 (data 2015-2019)', coverage: '2015–2019',
    source_url: 'https://www.oecd.org/en/publications/health-at-a-glance-2024_7a7afb35-en.html',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'onkologie', 'ženské zdraví', 'kvalita péče', 'mamografický screening'],
    data: [
      { year: 2010, value: 78 }, { year: 2014, value: 80 }, { year: 2019, value: 82 },
    ],
    comparison: [
      { country: 'Belgie', value: 90 },
      { country: 'Island', value: 90 },
      { country: 'USA', value: 89 },
      { country: 'Austrálie', value: 89 },
      { country: 'Německo', value: 87 },
      { country: 'OECD průměr', value: 86 },
      { country: 'ČR', value: 82, hi: true, isUs: true },
      { country: 'Polsko', value: 78, hi: true },
    ],
    trend_context: 'ČR se v 5letém přežití u rakoviny prsu blíží OECD průměru, ale za špičkou (Belgie, Island, USA) zaostává o 7-8 procentních bodů. Rozdíl odráží především dostupnost moderní cílené léčby a důslednost screeningu. Pozn.: data jsou z 2015-2019, ČR od té doby dál zlepšila.'
  },
  {
    id: 'oecd_kolorektum_preziti',
    label: 'Rakovina tlustého střeva a konečníku — 5leté přežití — OECD srovnání',
    human_name: '5leté přežití u rakoviny tlustého střeva a konečníku (OECD srovnání)',
    description: 'Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny tlustého střeva nebo konečníku. Porovnání ČR s vyspělými zeměmi.',
    code: 'OECD Cancer Care (2024)',
    source: 'OECD Health at a Glance', source_type: 'international', updated: '2024 (data 2015-2019)', coverage: '2015–2019',
    source_url: 'https://www.oecd.org/en/publications/health-at-a-glance-2024_7a7afb35-en.html',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'onkologie', 'screening tlustého střeva', 'kvalita péče'],
    data: [
      { year: 2010, value: 54 }, { year: 2014, value: 56 }, { year: 2019, value: 60 },
    ],
    comparison: [
      { country: 'Jižní Korea', value: 72 },
      { country: 'Austrálie', value: 71 },
      { country: 'Belgie', value: 69 },
      { country: 'OECD průměr', value: 63 },
      { country: 'Německo', value: 63 },
      { country: 'ČR', value: 60, hi: true, isUs: true },
      { country: 'Polsko', value: 55, hi: true },
    ],
    trend_context: 'ČR se v 5letém přežití u rakoviny tlustého střeva přibližuje OECD průměru. Asijské země (Korea) vedou žebříček díky kombinaci časného záchytu a moderní léčby. Český screening (od 2000) přispěl k postupnému zlepšení. Pozn.: data 2015-2019.'
  },
  {
    id: 'oecd_plice_preziti',
    label: 'Rakovina plic — 5leté přežití — OECD srovnání',
    human_name: '5leté přežití u rakoviny plic (OECD srovnání)',
    description: 'Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny plic. Patří k onkologicky nejhůře léčitelným diagnózám.',
    code: 'OECD Cancer Care (2024)',
    source: 'OECD Health at a Glance', source_type: 'international', updated: '2024 (data 2015-2019)', coverage: '2015–2019',
    source_url: 'https://www.oecd.org/en/publications/health-at-a-glance-2024_7a7afb35-en.html',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'onkologie', 'kouření', 'kvalita péče'],
    data: [
      { year: 2010, value: 13 }, { year: 2014, value: 15 }, { year: 2019, value: 18 },
    ],
    comparison: [
      { country: 'Japonsko', value: 35 },
      { country: 'Jižní Korea', value: 33 },
      { country: 'Izrael', value: 27 },
      { country: 'OECD průměr', value: 22 },
      { country: 'Německo', value: 21 },
      { country: 'ČR', value: 18, hi: true, isUs: true },
      { country: 'Polsko', value: 15, hi: true },
    ],
    trend_context: 'ČR i OECD se v 5letém přežití u rakoviny plic posouvají vpřed, ale stále zaostává za asijskými zeměmi (Japonsko, Korea), kde se daří díky kombinaci časného záchytu a moderní léčby. ČR má od 2022 plicní screening pro dlouhodobé kuřáky. Pozn.: data 2015-2019.'
  },
  {
    id: 'oecd_prostata_preziti',
    label: 'Rakovina prostaty — 5leté přežití — OECD srovnání',
    human_name: '5leté přežití u rakoviny prostaty (OECD srovnání)',
    description: 'Procento pacientů, kteří žijí 5 a více let po diagnóze rakoviny prostaty. Patří k onkologicky nejlépe prognosticky diagnózám.',
    code: 'OECD Cancer Care (2024)',
    source: 'OECD Health at a Glance', source_type: 'international', updated: '2024 (data 2015-2019)', coverage: '2015–2019',
    source_url: 'https://www.oecd.org/en/publications/health-at-a-glance-2024_7a7afb35-en.html',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'onkologie', 'mužské zdraví', 'kvalita péče'],
    data: [
      { year: 2010, value: 86 }, { year: 2014, value: 90 }, { year: 2019, value: 92 },
    ],
    comparison: [
      { country: 'Belgie', value: 99 },
      { country: 'Island', value: 98 },
      { country: 'Norsko', value: 97 },
      { country: 'USA', value: 97 },
      { country: 'OECD průměr', value: 93 },
      { country: 'ČR', value: 92, hi: true, isUs: true },
      { country: 'Polsko', value: 80, hi: true },
    ],
    trend_context: 'U rakoviny prostaty patří ČR k zemím s velmi dobrou prognózou — blíží se OECD průměru. Severské země a USA vedou žebříček díky kombinaci PSA screeningu a moderní léčby. Pozn.: data 2015-2019.'
  },
  {
    id: 'eu_ihd_mortality_sdr',
    label: 'Úmrtnost na ischemickou chorobu srdeční — EU srovnání',
    human_name: 'Standardizovaná úmrtnost na ischemickou chorobu srdeční (EU srovnání)',
    description: 'Standardizovaná úmrtnost na ischemickou chorobu srdeční (akutní infarkt myokardu a další) na 100 tisíc obyvatel — porovnání ČR s evropskými zeměmi.',
    code: 'hlth_cd_asdr2 (I20–I25)',
    source: 'Eurostat', source_type: 'international', updated: '2024 (data 2022)', coverage: '2022',
    source_url: 'https://ec.europa.eu/eurostat/databrowser/view/hlth_cd_asdr2/default/table',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'kardiovaskulární', 'mortalita', 'akutní infarkt myokardu'],
    data: [
      { year: 2018, value: 145 }, { year: 2019, value: 138 }, { year: 2020, value: 142 },
      { year: 2021, value: 138 }, { year: 2022, value: 130 },
    ],
    comparison: [
      { country: 'Litva', value: 285, hi: true },
      { country: 'Maďarsko', value: 270, hi: true },
      { country: 'Slovensko', value: 220, hi: true },
      { country: 'ČR', value: 130, hi: true, isUs: true },
      { country: 'EU průměr', value: 110 },
      { country: 'Francie', value: 55 },
      { country: 'Nizozemsko', value: 50 },
    ],
    trend_context: 'ČR se v úmrtnosti na ischemickou chorobu srdeční drží mezi středovýchodní Evropou (vyšší úmrtnost) a západní Evropou (nižší). Pokrok proti pobaltí a Maďarsku je významný — odraz zavedení sítě 23 katetrizačních center a dostupné statinové léčby. Pozn.: čísla jsou orientační, přesné hodnoty viz Eurostat hlth_cd_asdr2.'
  },
  {
    id: 'eu_stroke_mortality_sdr',
    label: 'Úmrtnost na cévní mozkové příhody — EU srovnání',
    human_name: 'Standardizovaná úmrtnost na cévní mozkové příhody (EU srovnání)',
    description: 'Standardizovaná úmrtnost na cévní mozkové příhody na 100 tisíc obyvatel — porovnání ČR s evropskými zeměmi.',
    code: 'hlth_cd_asdr2 (I60–I69)',
    source: 'Eurostat', source_type: 'international', updated: '2024 (data 2022)', coverage: '2022',
    source_url: 'https://ec.europa.eu/eurostat/databrowser/view/hlth_cd_asdr2/default/table',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'kardiovaskulární', 'mortalita', 'cévní mozková příhoda'],
    data: [
      { year: 2018, value: 75 }, { year: 2019, value: 70 }, { year: 2020, value: 68 },
      { year: 2021, value: 65 }, { year: 2022, value: 60 },
    ],
    comparison: [
      { country: 'Bulharsko', value: 175, hi: true },
      { country: 'Rumunsko', value: 160, hi: true },
      { country: 'Maďarsko', value: 110, hi: true },
      { country: 'ČR', value: 60, hi: true, isUs: true },
      { country: 'EU průměr', value: 55 },
      { country: 'Švýcarsko', value: 35 },
      { country: 'Francie', value: 30 },
    ],
    trend_context: 'ČR se v úmrtnosti na cévní mozkové příhody dostala blízko EU průměru. Klíčem byla síť specializovaných center pro léčbu cévních mozkových příhod (od 2011) a moderní léčba (mechanická trombektomie). Pozn.: čísla jsou orientační, přesné hodnoty viz Eurostat hlth_cd_asdr2.'
  },
  {
    id: 'oecd_health_spending_gdp',
    label: 'Výdaje na zdravotnictví — podíl HDP — OECD srovnání',
    human_name: 'Výdaje na zdravotnictví jako podíl hrubého domácího produktu (OECD srovnání)',
    description: 'Procento hrubého domácího produktu (HDP), které země vydává na zdravotní péči. Klíčový makro-ekonomický ukazatel financování zdravotnictví — vyšší podíl nemusí znamenat lepší péči (viz USA), ale ukazuje politické priority.',
    code: 'OECD Health Statistics (2024)',
    source: 'OECD Health at a Glance', source_type: 'international', updated: '2024 (data 2022)', coverage: '2022',
    source_url: 'https://www.oecd.org/en/publications/health-at-a-glance-2024_7a7afb35-en.html',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'financování zdravotnictví', 'veřejné zdraví', 'politika'],
    data: [
      { year: 2018, value: 7.6 }, { year: 2019, value: 7.8 }, { year: 2020, value: 9.0 },
      { year: 2021, value: 9.1 }, { year: 2022, value: 8.8 },
    ],
    comparison: [
      { country: 'USA', value: 16.6, hi: true },
      { country: 'Německo', value: 12.7 },
      { country: 'Francie', value: 12.1 },
      { country: 'Švédsko', value: 10.7 },
      { country: 'OECD průměr', value: 9.2 },
      { country: 'ČR', value: 8.8, hi: true, isUs: true },
      { country: 'Polsko', value: 6.7, hi: true },
    ],
    trend_context: 'ČR vydává na zdravotnictví zhruba 9 % HDP — pod OECD průměrem, ale výrazně víc než středovýchodní Evropa (Polsko, Maďarsko). USA je outlier (drahé soukromé pojištění), Skandinávie a Německo jsou nahoře díky veřejnému zdravotnímu systému. Pozn.: čísla jsou orientační, přesné hodnoty viz OECD Health Statistics.'
  },
  {
    id: 'oecd_health_spending_per_capita',
    label: 'Výdaje na zdravotnictví na obyvatele — OECD srovnání',
    human_name: 'Výdaje na zdravotnictví na obyvatele (USD podle parity kupní síly)',
    description: 'Roční výdaje na zdravotnictví na obyvatele v amerických dolarech přepočtených podle parity kupní síly (PPP). Lépe vyjadřuje skutečnou úroveň investice než pouhý kurz dolaru.',
    code: 'OECD Health Statistics (2024)',
    source: 'OECD Health at a Glance', source_type: 'international', updated: '2024 (data 2022)', coverage: '2022',
    source_url: 'https://www.oecd.org/en/publications/health-at-a-glance-2024_7a7afb35-en.html',
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['mezinárodní kontext', 'financování zdravotnictví', 'kvalita péče'],
    data: [
      { year: 2018, value: 2900 }, { year: 2019, value: 3050 }, { year: 2020, value: 3400 },
      { year: 2021, value: 3700 }, { year: 2022, value: 3800 },
    ],
    comparison: [
      { country: 'USA', value: 12550, hi: true },
      { country: 'Německo', value: 8000 },
      { country: 'Nizozemsko', value: 6700 },
      { country: 'Francie', value: 5600 },
      { country: 'OECD průměr', value: 5000 },
      { country: 'ČR', value: 3800, hi: true, isUs: true },
      { country: 'Polsko', value: 2900, hi: true },
    ],
    trend_context: 'V přepočtu na obyvatele ČR vydává cca 3800 USD ročně — zhruba 75 % OECD průměru. Postupně se zvyšuje, ale za hlavními evropskými ekonomikami zaostává. Při porovnání pamatujte, že nižší výdaje v ČR nutně neznamenají horší péči — mnohé služby jsou levnější (mzdy zdravotníků, léky). Pozn.: data 2022, USD PPP.'
  },
  {
    id: 'fh_detection',
    label: 'Detekce FH — mezinárodní srovnání programů',
    human_name: 'Dědičně vysoký cholesterol — diagnostika',
    description: 'Procento osob s dědičnou hypercholesterolemií, které jsou v zemi diagnostikovány.',
    code: 'MedPed / NL FH',
    source: 'Vrablík et al. / PLOS GPH', source_type: 'international', updated: '2016 / 2023', coverage: 'různé roky',
    source_url: null,
    trend: 'comparison', delta: null, peakYear: null,
    relevant_for: ['genetika', 'cholesterol', 'prevence u mladých', 'mezinárodní srovnání'],
    data: [
      { year: 2010, value: 8 }, { year: 2013, value: 12 }, { year: 2016, value: 17.4 },
    ],
    comparison: [
      { country: 'Nizozemsko (špička)', value: 71, hi: false },
      { country: 'Norsko', value: 50 },
      { country: 'ČR (MedPed 2016)', value: 17.4, hi: true, isUs: true },
      { country: 'V. Británie (NHS)', value: 8 },
    ],
    trend_context: 'Procento odhadované populace s dědičně vysokým cholesterolem, která je už diagnostikovaná. POZOR: roky se mírně liší (ČR 2016, NL/UK 2023), srovnatelnost spíše orientační.'
  },
];

// Base URL pro načítání dat — v produkci jde o relativní cestu k /public/data/.
const DATA_BASE = import.meta.env.BASE_URL + 'data/';

// ============================================================
// API KEY MANAGEMENT
// ============================================================

const API_KEY_STORAGE = 'omnimedia_anthropic_key';

function getStoredKey() {
  try {
    return localStorage.getItem(API_KEY_STORAGE);
  } catch (e) {
    return null;
  }
}

function setStoredKey(key) {
  try {
    if (key) {
      localStorage.setItem(API_KEY_STORAGE, key);
    } else {
      localStorage.removeItem(API_KEY_STORAGE);
    }
  } catch (e) {}
}

// ============================================================
// HELPERY PRO EXPORT DOCX
// ============================================================

function slug(s) {
  return (s || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
}

function formatDateISO(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatDateCS(d) {
  return `${d.getDate()}. ${d.getMonth() + 1}. ${d.getFullYear()}`;
}

// ============================================================
// API KEY MODAL
// ============================================================

function ApiKeyModal({ onSave, onClose, currentKey }) {
  const [input, setInput] = useState(currentKey || '');
  const [showKey, setShowKey] = useState(false);

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(26,26,26,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#FFFFFF', padding: 32, maxWidth: 540, width: '90%',
        border: '1px solid #E0D6EA', borderRadius: 16, boxShadow: '0 12px 40px rgba(112,32,130,0.22)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h2 className="serif" style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Anthropic API klíč</h2>
          {onClose && (
            <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
              <X size={20} />
            </button>
          )}
        </div>

        <p style={{ fontSize: 14, color: '#555', lineHeight: 1.5, marginBottom: 16 }}>
          Klíč si vygeneruj v <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" style={{ color: '#ed8b00' }}>console.anthropic.com/settings/keys</a>.
          Uloží se výhradně do tvého prohlížeče (localStorage), nikam se neodesílá kromě přímého volání Anthropic API.
        </p>

        <div style={{ position: 'relative', marginBottom: 20 }}>
          <input
            type={showKey ? 'text' : 'password'}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="sk-ant-api03-..."
            style={{
              width: '100%', padding: '10px 70px 10px 12px', fontSize: 14,
              fontFamily: 'monospace', border: '1.5px solid #702082',
              background: '#FFFFFF',
            }}
          />
          <button
            onClick={() => setShowKey(!showKey)}
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              background: 'none', border: 'none', cursor: 'pointer', fontSize: 12,
              color: '#666', padding: '4px 8px',
            }}
          >
            {showKey ? 'skrýt' : 'zobrazit'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {currentKey && (
            <button
              onClick={() => { setStoredKey(null); onSave(null); }}
              style={{
                padding: '10px 16px', background: 'transparent', border: '1.5px solid #999',
                cursor: 'pointer', fontSize: 14, color: '#666',
              }}
            >
              Zapomenout klíč
            </button>
          )}
          <button
            onClick={() => { setStoredKey(input); onSave(input); }}
            disabled={!input || input.length < 20}
            style={{
              padding: '10px 20px', background: '#702082', color: '#FFFFFF',
              border: 'none', cursor: input ? 'pointer' : 'not-allowed',
              fontSize: 14, fontWeight: 600, opacity: input ? 1 : 0.5,
            }}
          >
            Uložit klíč
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// HLAVNÍ APP
// ============================================================

export default function App() {
  const [apiKey, setApiKey] = useState(getStoredKey());
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [topic, setTopic] = useState('');
  const [step, setStep] = useState(1);
  const [nationalDatasets, setNationalDatasets] = useState([]);
  const [loadingData, setLoadingData] = useState(true);
  // datasetData: Map<id, {loading: bool, error: string|null, series: [{year, value}]|null}>
  // Populátí se lazy po výběru datasetu — fetch CSV ze zdroje + Papa parse + agregace.
  const [datasetData, setDatasetData] = useState(() => new Map());
  const [selectedIds, setSelectedIds] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [recommending, setRecommending] = useState(false);
  // recommendations: [{id, reason}] — návrhy AI po kliknutí "Najít relevantní data".
  const [recommendations, setRecommendations] = useState(null);
  const [error, setError] = useState(null);
  // includeIntl: zařadit i mezinárodní srovnání (EU/OECD). Default jen česká data.
  const [includeIntl, setIncludeIntl] = useState(false);
  // browseAll: zobrazit celý katalog karet (jinak jen AI-doporučené + vybrané).
  const [browseAll, setBrowseAll] = useState(false);
  // noResults: klidná informační hláška, když k tématu nejsou vhodná data (ne chyba).
  const [noResults, setNoResults] = useState(null);
  // cubeFilters: { [cubeId]: {diagnosis, age, sex, stage} } — stav zužování každé kostky.
  const [cubeFilters, setCubeFilters] = useState({});
  const cubeFilterOf = (id) => cubeFilters[id] || DEFAULT_CUBE_FILTER;
  const setCubeFilter = (id, f) => setCubeFilters(prev => ({ ...prev, [id]: f }));

  // Krok A — při startu: stáhni catalog.json (metadata pro všechny datasety, žádná data).
  useEffect(() => {
    async function loadCatalog() {
      try {
        const response = await fetch(`${DATA_BASE}catalog.json`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const catalog = await response.json();
        setNationalDatasets(catalog.datasets || []);
      } catch (e) {
        console.error('Nelze načíst catalog.json:', e);
        setError(`Nelze načíst katalog datasetů: ${e.message}`);
      } finally {
        setLoadingData(false);
      }
      if (!apiKey) setShowKeyModal(true);
    }
    loadCatalog();
  }, []);

  // Krok B — když uživatel vybere dataset, kterému ještě nemáme data, spusť lazy fetch CSV.
  // Cache je per csv_url (csvCache nahoře), takže NOR (sdílené CSV) se stáhne jednou.
  useEffect(() => {
    if (nationalDatasets.length === 0) return;
    for (const id of selectedIds) {
      if (datasetData.has(id)) continue;
      const entry = nationalDatasets.find(d => d.id === id);
      if (!entry) continue;
      if (entry.kind === 'snapshot') continue; // souhrn má hodnoty rovnou v katalogu, nestahuje se
      setDatasetData(prev => new Map(prev).set(id, { loading: true, error: null, series: null }));
      const loader = entry.kind === 'cube'
        ? fetchCubeCached(entry).then(cube => setDatasetData(prev => new Map(prev).set(id, { loading: false, error: null, cube })))
        : parseDataset(entry).then(series => setDatasetData(prev => new Map(prev).set(id, { loading: false, error: null, series })));
      loader.catch(e => {
        console.error(`Fetch failed pro ${id}:`, e);
        setDatasetData(prev => new Map(prev).set(id, { loading: false, error: e.message, series: null }));
      });
    }
  }, [selectedIds, nationalDatasets]);

  // Krok C — vyrobí "enriched" datasety: metadata + (lazy) data + computed trend/delta/peakYear.
  // Nevybraný dataset má _hasData=false → karta ukáže skeleton bez grafu.
  const allDatasets = useMemo(() => {
    const national = nationalDatasets.map(meta => {
      const baseSourceType = meta.source_type || 'national';
      // Souhrn (snapshot) má hodnoty rovnou v katalogu — vždy připravený, žádný fetch.
      if (meta.kind === 'snapshot') return { ...meta, source_type: baseSourceType, _loading: false, _hasData: true };
      const state = datasetData.get(meta.id);
      if (!state) return { ...meta, source_type: baseSourceType, _loading: false, _hasData: false };
      if (state.loading) return { ...meta, source_type: baseSourceType, _loading: true, _hasData: false };
      if (state.error) return { ...meta, source_type: baseSourceType, _loading: false, _hasData: false, _error: state.error };
      // Kostka: řez podle aktuálního filtru → časová řada jako u běžného datasetu.
      let series, extra = {};
      if (meta.kind === 'cube' && state.cube) {
        const f = cubeFilterOf(meta.id);
        series = sliceCube(state.cube, f);
        const label = cubeFilterLabel(state.cube, f);
        const primaryKey = state.cube.dims.find(d => d.primary)?.key;
        const primarySel = primaryKey && f[primaryKey] && f[primaryKey] !== 'vše' ? f[primaryKey] : null;
        extra = {
          cube: state.cube,
          cubeFilter: f,
          human_name: `${meta.human_name}: ${label}`,
          metric_label: state.cube.metric_label || 'Počet',
          code: primarySel,
          trend_context: `${meta.trend_context} Aktuální výřez: ${label}.`,
        };
      } else {
        series = state.series || [];
      }
      const computed = computeMeta(series);
      const coverage = series.length > 0 ? `${series[0].year}–${series[series.length - 1].year}` : '';
      return {
        ...meta,
        source_type: baseSourceType,
        _loading: false,
        _hasData: true,
        data: series,
        coverage,
        trend: computed.trend,
        delta: computed.delta,
        peakYear: computed.peakYear,
        ...extra,
      };
    });
    if (!includeIntl) return national;
    // Mezinárodní datasety mají data napevno (žádný fetch) — přidáme je jen když je checkbox zapnutý.
    const intl = INTL_DATASETS.map(meta => ({ ...meta, _loading: false, _hasData: true }));
    return [...national, ...intl];
  }, [nationalDatasets, datasetData, includeIntl, cubeFilters]);
  const selectedDatasets = allDatasets.filter(d => selectedIds.includes(d.id));
  // Některý vybraný dataset ještě stahuje/parsuje data ze zdroje — dokud běží, analýzu nepouštíme.
  const selectedLoading = selectedDatasets.some(d => d._loading);

  // Karty k zobrazení v Section 02: dokud uživatel nespustí doporučení ani neotevře
  // celý katalog, sekce se vůbec nezobrazí. Pak ukazujeme jen doporučené + ručně vybrané,
  // nebo (po kliknutí na „Procházet celý katalog") všechny.
  const recommendedIds = recommendations ? recommendations.map(r => r.id) : [];
  const displayedDatasets = browseAll
    ? allDatasets
    : allDatasets.filter(d => recommendedIds.includes(d.id) || selectedIds.includes(d.id));
  const showDataSection = recommendations !== null || browseAll;

  const toggleDataset = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  // KROK 4 — AI doporučení datasetů. Pošle téma + zkrácený katalog na Anthropic,
  // dostane zpět 5–10 ID s důvodem, automaticky je zaškrtne v Section 02 (a tím spustí
  // lazy fetch CSV přes existující useEffect na selectedIds).
  const recommendDatasets = async () => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    if (!topic.trim()) {
      setError('Zadej téma briefu.');
      return;
    }
    if (nationalDatasets.length === 0) {
      setError('Katalog datasetů ještě není načtený.');
      return;
    }

    setRecommending(true);
    setError(null);
    setNoResults(null);

    let text = '';
    try {
      const pool = includeIntl ? [...nationalDatasets, ...INTL_DATASETS] : nationalDatasets;
      const catalogShort = pool.map(d => ({
        id: d.id,
        category: d.category || '',
        human_name: d.human_name || '',
        description: d.description || '',
        relevant_for: d.relevant_for || [],
      }));

      const intlHint = includeIntl
        ? 'Katalog obsahuje národní česká data i mezinárodní srovnání (EU/OECD). PR brief obvykle těží z kombinace národních trendů a mezinárodního kontextu — pokud je mezinárodní srovnání k tématu relevantní, zařaď ho.'
        : 'Katalog obsahuje jen národní česká data. Vybírej pouze z něj, mezinárodní srovnání teď uživatel nechce.';

      // Stabilní část (instrukce + celý katalog) je stejná napříč voláními → dáme ji do prompt cache.
      // Mění se jen téma (variabilní blok na konci), takže opakované „Najít data" do 5 min platí
      // katalog jen ~10 %. Doporučování je filtrování katalogu → stačí Haiku (~10× levnější než Sonnet).
      const cachedPrompt = `Jsi datový analytik pro českou PR agenturu. Z katalogu datasetů vybíráš ty nejrelevantnější k zadanému tématu briefu.

K dispozici máš tento katalog datasetů (každý má id, kategorii, lidský název, popis a oblasti relevance):

${JSON.stringify(catalogShort, null, 2)}

${intlHint}

Vyber 5 až 10 datasetů, které jsou pro téma nejrelevantnější. Pokud katalog obsahuje méně relevantních datasetů, vyber raději míň (klidně jen 3) než nesedící. Pokud k tématu nesedí vůbec nic, vrať prázdné pole. U každého datasetu napiš 1 krátkou větu důvodu, proč se k tématu hodí.

Vrať POUZE platný JSON, žádné markdown, žádný úvod ani závěr:
{"recommended": [{"id": "id_z_katalogu", "reason": "Krátký důvod, 1 věta česky."}]}

DŮLEŽITÉ: pole "id" musí být přesně jedno z id v katalogu výše. Žádné jiné id nevymýšlej.`;

      const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true',
        },
        body: JSON.stringify({
          model: 'claude-haiku-4-5-20251001',
          max_tokens: 2048,
          messages: [{
            role: 'user',
            content: [
              { type: 'text', text: cachedPrompt, cache_control: { type: 'ephemeral' } },
              { type: 'text', text: `Téma briefu: "${topic}"` },
            ],
          }],
        }),
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Anthropic API: ${response.status} — ${errText.substring(0, 200)}`);
      }

      const data = await response.json();
      text = data.content?.[0]?.text || '';
      const match = text.match(/\{[\s\S]*\}/);
      if (!match) throw new Error(`Odpověď AI neobsahuje JSON. Začátek odpovědi: "${text.substring(0, 150)}"`);
      const parsed = JSON.parse(match[0]);
      const knownIds = new Set(pool.map(d => d.id));
      const valid = (parsed.recommended || []).filter(r => r.id && knownIds.has(r.id));
      if (valid.length === 0) {
        // Není to chyba — jen pro dané téma nemáme vhodná data. Klidná hláška, ne červená lišta.
        setRecommendations(null);
        setSelectedIds([]);
        setNoResults(
          `Pro téma „${topic}" jsme v dostupných datech${includeIntl ? '' : ' (jen česká)'} nenašli vhodné datasety. ` +
          `Zkus formulaci upravit, zvolit obecnější téma${includeIntl ? '' : ', nebo zapnout mezinárodní srovnání'}, ` +
          `případně si datasety vyber ručně přes „Procházet celý katalog".`
        );
        return;
      }
      setRecommendations(valid);
      setSelectedIds(valid.map(r => r.id));
    } catch (e) {
      console.error('Recommend raw response (full):', text);
      setError(`Nelze získat doporučení datasetů: ${e.message}`);
    } finally {
      setRecommending(false);
    }
  };

  const runAnalysis = async () => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    if (selectedDatasets.length === 0) {
      setError('Vyber alespoň jeden dataset.');
      return;
    }

    setAnalyzing(true);
    setError(null);

    let text = '';
    try {
      const intlDs = selectedDatasets.filter(d => d.source_type === 'international');
      // Národní/krajové datasety musí mít stažená a zparsovaná data. Když se analýza spustí dřív,
      // než CSV dotáhne (nebo se stahování nepovede), pole data chybí — takové datasety vyřadíme,
      // ať analýza nespadne na čtení prázdné časové řady (d.data[0]).
      const fetchedDs = selectedDatasets.filter(d => d.source_type !== 'international');
      const readyDs = fetchedDs.filter(d => Array.isArray(d.data) && d.data.length > 0);
      const snapshotDs = selectedDatasets.filter(d => d.kind === 'snapshot' && Array.isArray(d.snapshot));
      if (readyDs.length === 0 && intlDs.length === 0 && snapshotDs.length === 0) {
        setAnalyzing(false);
        setError('Data se ještě načítají nebo se je nepodařilo stáhnout. Počkej, až karty dočtou data (zmizí „Načítám…"), nebo odškrtni karty, u kterých svítí hláška o chybě stahování.');
        return;
      }
      const nationalDs = readyDs.filter(d => !['regional_snapshot', 'regional_timeseries'].includes(d.source_type));
      const regionalDs = readyDs.filter(d => d.source_type === 'regional_snapshot');
      const regionalTSDs = readyDs.filter(d => d.source_type === 'regional_timeseries');

      const nationalSummary = nationalDs.map(d => {
        const first = d.data[0], last = d.data[d.data.length - 1];
        return `- [id: ${d.id}] ${d.human_name || d.label} (MKN ${d.code}): ${first.value.toLocaleString('cs-CZ')} v ${first.year} → ${last.value.toLocaleString('cs-CZ')} v ${last.year} (Δ ${d.delta > 0 ? '+' : ''}${d.delta} %). Trend: ${d.trend === 'up' ? 'rostoucí' : d.trend === 'down' ? 'klesající' : 'plateau'}, peak ${d.peakYear}. Kontext: ${d.trend_context || ''}`;
      }).join('\n');

      const regionalSummary = regionalDs.map(d => {
        const sorted = [...d.data].sort((a, b) => b.value - a.value);
        const breakdown = sorted.map(r => `${r.kraj_nazev}: ${r.value.toLocaleString('cs-CZ')}`).join('; ');
        return `- [id: ${d.id}] ${d.human_name || d.label} (MKN ${d.code}, rok ${d.snapshot_year}): ${breakdown}. Peak kraj: ${d.peakRegion}. Kontext: ${d.trend_context || ''}`;
      }).join('\n');

      const regionalTSSummary = regionalTSDs.map(d => {
        // Pro každý kraj spočítat průběh (první a poslední rok).
        const years = [...new Set(d.data.map(r => r.year))].sort((a, b) => a - b);
        const firstYr = years[0], lastYr = years[years.length - 1];
        const krajeMap = new Map();
        for (const r of d.data) {
          if (!krajeMap.has(r.kraj_kod)) krajeMap.set(r.kraj_kod, { kraj: r.kraj_nazev, first: null, last: null });
          if (r.year === firstYr) krajeMap.get(r.kraj_kod).first = r.value;
          if (r.year === lastYr) krajeMap.get(r.kraj_kod).last = r.value;
        }
        const breakdown = [...krajeMap.values()]
          .sort((a, b) => b.last - a.last)
          .map(k => `${k.kraj}: ${k.first}→${k.last} (Δ ${k.first ? Math.round((k.last - k.first) / k.first * 100) : 0}%)`)
          .join('; ');
        return `- [id: ${d.id}] ${d.human_name || d.label} (MKN ${d.code}, ${firstYr}-${lastYr} per kraj): ${breakdown}. Kontext: ${d.trend_context || ''}`;
      }).join('\n');

      const intlSummary = intlDs.map(d => {
        const comp = d.comparison ? d.comparison.map(c => `${c.country}: ${c.value}${typeof c.value === 'number' && Math.abs(c.value) < 200 ? ' %' : ''}`).join('; ') : '';
        return `- [id: ${d.id}] ${d.human_name || d.label} (zdroj: ${d.source} ${d.code}, ${d.coverage}): ${comp}. Pozn. ke srovnatelnosti: ${d.trend_context || ''}`;
      }).join('\n');

      // Anomálie z rozpadových kostek — silní kandidáti na úhly.
      const cubeDs = readyDs.filter(d => d.kind === 'cube' && d.cube);
      const cubeAnomSummary = cubeDs.flatMap(d => (d.cube.anomalies || []).slice(0, 14).map(a => {
        if (a.type === 'trend') return `- [${a.dg}] ${a.name}: výskyt ${a.pct > 0 ? '+' : ''}${a.pct} % (${a.from}→${a.to}/rok, 2011–13 vs 2020–22)${a.artifact_risk ? ' ⚠ POZOR: možná změna kódování, ne reálný trend' : ''}`;
        if (a.type === 'vek_posun') return `- [${a.dg}] ${a.name}: podíl mladších 50 let ${a.from_pct} % → ${a.to_pct} % (${a.diff > 0 ? '+' : ''}${a.diff} b.b.)`;
        if (a.type === 'stadium_posun') return `- [${a.dg}] ${a.name}: pozdní záchyt (stadium III+IV) ${a.from_pct} % → ${a.to_pct} % (${a.diff > 0 ? '+' : ''}${a.diff} b.b.)`;
        return '';
      })).filter(Boolean).join('\n');

      // Souhrnná (snapshot) data — popisná fakta o stavu.
      const snapshotSummary = snapshotDs.map(d =>
        `- ${d.human_name}${d.snapshot_date ? ` (stav k ${d.snapshot_date})` : ''}: ${d.snapshot.map(s => `${s.label}: ${typeof s.value === 'number' ? s.value.toLocaleString('cs-CZ') : s.value}`).join('; ')}`
      ).join('\n');

      const prompt = `Jsi datový analytik pro českou PR agenturu. NEPÍŠEŠ tiskové zprávy. Tvoje práce je z dat vytáhnout zjištění a doporučit úhly — PR manažer si text napíše sám.

KLIENT: ${CLIENT.full}
TÉMA BRIEFU: "${topic}"

NÁRODNÍ DATA Z NKIS / ÚZIS ČR:
${nationalSummary || '(žádná národní data nevybrána)'}

${regionalSummary ? `KRAJOVÝ POHLED (snapshot ČR):
${regionalSummary}

` : ''}${regionalTSSummary ? `KRAJOVÝ VÝVOJ V ČASE (multi-year per kraj):
${regionalTSSummary}

` : ''}${intlSummary ? `MEZINÁRODNÍ SROVNÁVACÍ DATA:
${intlSummary}

DŮLEŽITÉ: vždy zmiň rok dat a metodiku. Pokud roky nesedí, uveď orientačnost. NEPOUŽÍVEJ OECD ukazatel "30denní mortalita po AIM" — není srovnatelný (Stolpe et al. 2023).
` : ''}${snapshotSummary ? `SOUHRNNÁ POPISNÁ DATA (stav, ne časová řada — použij jako fakta/čísla do briefu):
${snapshotSummary}

` : ''}${cubeAnomSummary ? `AUTOMATICKY NALEZENÉ ANOMÁLIE V ONKOLOGICKÉ ROZPADOVÉ KOSTCE (silní kandidáti na úhly — ber je jako tipy z dat, ne hotová tvrzení):
${cubeAnomSummary}

POZOR: u položek označených ⚠ zařaď do "cannot_claim" upozornění, že prudký pohyb může být změnou kódování diagnóz v čase, ne reálným vývojem.
` : ''}

PRAVIDLO PRO ZKRATKY V ANALÝZE:
- Při prvním použití termínu, který má v češtině/angličtině zkratku (např. AIM, KVO, FH, ICHS, CMP, NRHZS), napiš plný název a zkratku v závorce: "akutní infarkt myokardu (AIM)". V dalších použitích už používej jen zkratku.
- U mezinárodních termínů totéž: "Eurostat hlth_cd_aro" první výskyt, pak jen "Eurostat".
- Cíl: text musí být srozumitelný pro PR pracovníka, ne kardiologa.

Vrať POUZE platný JSON, žádné markdown, žádný úvod:
{
  "key_findings": [{"number": "+70 %", "label": "...", "explanation": "...", "dataset": "id datasetu (např. 'aim', 'cmp', 'eu_cvd_share') — ne lidský název"}],
  "meta_pattern": "1–2 věty",
  "angles": [{"label": "...", "observation": "1–2 věty pozorování, ne kopie", "key_data": ["..."], "datasets": ["id datasetu/ů, ze kterých úhel vychází"], "risk": "..."}],
  "cannot_claim": [{"claim": "...", "why": "..."}]
}

3–5 key_findings, 3 angles, 2–3 cannot_claim. Vše česky. Žádné hotové copywriting věty.

OVĚŘITELNOST ZDROJŮ (povinné): u každého key_finding (pole "dataset") i u každého úhlu (pole "datasets") MUSÍŠ uvést id datasetu/ů z výše uvedených dat, ze kterých tvrzení vychází — používej přesně id z hranatých závorek [id: ...], ne lidské názvy. Úhel může stát na víc datasetech (vyjmenuj všechna). Tvrzení bez doložitelného zdroje v datech neuváděj.`;

      const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true',
        },
        body: JSON.stringify({
          model: 'claude-sonnet-4-6',
          max_tokens: 8192,
          messages: [{ role: 'user', content: prompt }],
        }),
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Anthropic API: ${response.status} — ${errText.substring(0, 200)}`);
      }

      const data = await response.json();
      text = data.content?.[0]?.text || '';
      const match = text.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('Odpověď neobsahuje JSON');
      const parsed = JSON.parse(match[0]);
      setAnalysis(parsed);
      setStep(3);
    } catch (e) {
      console.error('Raw response length:', text?.length, 'last 200:', text?.substring((text?.length || 0) - 200));
      setError(`${e.message} | Délka: ${text?.length || 0} | Konec: "${text?.substring((text?.length || 0) - 100)}"`);
    } finally {
      setAnalyzing(false);
    }
  };

  const exportToDocx = async () => {
    // Pomocníci pro stručný zápis
    const border = { style: BorderStyle.SINGLE, size: 4, color: 'DDD2E5' };
    const tableBorders = { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border };
    const t = (text, opts = {}) => new TextRun({
      text: String(text ?? ''),
      bold: opts.bold,
      italics: opts.italic,
      size: opts.size,
      color: opts.color,
    });
    const p = (runs, opts = {}) => new Paragraph({
      children: Array.isArray(runs) ? runs : [runs],
      spacing: opts.spacing,
      alignment: opts.alignment,
      shading: opts.shading,
      bullet: opts.bullet,
      heading: opts.heading,
    });
    const cell = (children, opts = {}) => new TableCell({
      children: Array.isArray(children) ? children : [children],
      width: opts.width,
      shading: opts.shading,
    });
    // Zdrojový odkaz pod tezí: název datasetu + ověřitelná URL (z polí dataset/datasets od AI).
    const srcParas = (ids) => {
      const seen = new Set();
      const dss = (ids || []).map(id => findDatasetById(id, selectedDatasets)).filter(d => d && !seen.has(d.id) && seen.add(d.id));
      if (!dss.length) return [];
      const runs = [t('Zdroj: ', { color: '888888', size: 16 })];
      dss.forEach((ds, j) => {
        if (j > 0) runs.push(t('; ', { color: '888888', size: 16 }));
        runs.push(t(ds.human_name || ds.label, { color: '888888', size: 16 }));
        if (ds.source_url) { runs.push(t(' — ', { color: '888888', size: 16 })); runs.push(t(ds.source_url, { color: '702082', size: 16 })); }
      });
      return [p(runs, { spacing: { before: 40 } })];
    };

    const lightPurple = { type: ShadingType.SOLID, color: 'auto', fill: 'F2ECF7' };
    const purpleBox = { type: ShadingType.SOLID, color: 'auto', fill: '702082' };

    const children = [];

    // 1. Hlavička
    children.push(p(
      t(`DATOVÝ PODKLAD • Klient: ${CLIENT.full} • Téma: ${topic} • ${formatDateCS(new Date())}`, { size: 16, color: '666666' }),
      { spacing: { after: 200 } }
    ));

    // 2. Titul
    children.push(p(t(topic, { bold: true, size: 36 }), {
      heading: HeadingLevel.HEADING_1,
      spacing: { after: 300 },
    }));

    // 3. V čem data spočívají — světle fialové pozadí (OZP)
    children.push(p(t('V čem data spočívají', { bold: true, size: 22 }), { spacing: { before: 200, after: 100 } }));
    const sources = [...new Set(selectedDatasets.map(d => d.source).filter(Boolean))];
    const allYears = selectedDatasets.flatMap(d => (d.data || []).map(x => x.year)).filter(Number.isFinite);
    const yearRange = allYears.length ? `${Math.min(...allYears)}–${Math.max(...allYears)}` : '—';
    const datasetSummary = selectedDatasets.map(d => d.human_name || d.label).join(', ');
    children.push(p([t('Zdroj: ', { bold: true }), t(sources.join(', ') || '—')], { shading: lightPurple, spacing: { before: 80, after: 80 } }));
    children.push(p([t('Co data obsahují: ', { bold: true }), t(datasetSummary)], { shading: lightPurple, spacing: { after: 80 } }));
    children.push(p([t('Časové pokrytí: ', { bold: true }), t(yearRange)], { shading: lightPurple, spacing: { after: 200 } }));

    // 4. Co data dohromady říkají — fialové pozadí (OZP), italika, bílý text
    if (analysis.meta_pattern) {
      children.push(p(t('Co data dohromady říkají', { bold: true, size: 22 }), { spacing: { before: 300, after: 100 } }));
      children.push(p(
        t(analysis.meta_pattern, { italic: true, color: 'FFFFFF', size: 22 }),
        { shading: purpleBox, spacing: { before: 100, after: 200 } }
      ));
    }

    // 5. Mezinárodní kontext — jen pokud máme intl datasety
    const intlDs = selectedDatasets.filter(d => d.source_type === 'international');
    if (intlDs.length > 0) {
      children.push(p(t('Mezinárodní kontext', { bold: true, size: 22 }), { spacing: { before: 300, after: 100 } }));
      const intlHeader = new TableRow({
        children: [
          cell(p(t('Metrika', { bold: true }))),
          cell(p(t('Číslo a srovnání', { bold: true }))),
          cell(p(t('Co to říká o ČR', { bold: true }))),
        ],
      });
      const intlRows = intlDs.map(d => {
        const comp = (d.comparison || []).slice(0, 4)
          .map(c => `${c.country}: ${c.value}${typeof c.value === 'number' && Math.abs(c.value) < 200 ? ' %' : ''}`)
          .join('; ');
        return new TableRow({
          children: [
            cell(p(t(d.human_name || d.label))),
            cell(p(t(comp))),
            cell(p(t(d.trend_context || ''))),
          ],
        });
      });
      children.push(new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        borders: tableBorders,
        rows: [intlHeader, ...intlRows],
      }));
    }

    // 6. Klíčová zjištění
    if (analysis.key_findings?.length) {
      children.push(p(t('Klíčová zjištění', { bold: true, size: 22 }), { spacing: { before: 300, after: 100 } }));
      const kfHeader = new TableRow({
        children: [
          cell(p(t('Δ', { bold: true }), { alignment: AlignmentType.CENTER }), { width: { size: 15, type: WidthType.PERCENTAGE } }),
          cell(p(t('Co', { bold: true })), { width: { size: 50, type: WidthType.PERCENTAGE } }),
          cell(p(t('Proč relevantní pro téma', { bold: true })), { width: { size: 35, type: WidthType.PERCENTAGE } }),
        ],
      });
      const kfRows = analysis.key_findings.map(f => {
        const ds = findDatasetById(f.dataset, selectedDatasets);
        const coParas = [
          p([
            t(f.label || '', { bold: true }),
            ...(ds?.code ? [t(' ('), t(ds.code), t(')')] : []),
          ]),
        ];
        if (ds) {
          coParas.push(p([
            t(ds.human_name || ds.label, { bold: true }),
            t(' — '),
            t(ds.description || ''),
          ]));
          if (ds.metric_label && ds.data?.length) {
            if (ds.source_type === 'regional_snapshot') {
              const sorted = [...ds.data].sort((a, b) => b.value - a.value);
              const top3 = sorted.slice(0, 3).map(r => `${r.kraj_nazev}: ${r.value.toLocaleString('cs-CZ')}`).join('; ');
              coParas.push(p(t(
                `${ds.metric_label} — top 3 kraje (${ds.snapshot_year}): ${top3}`,
                { italic: true, color: '888888', size: 16 }
              )));
            } else {
              const fv = ds.data[0]?.value, lv = ds.data[ds.data.length - 1]?.value;
              const fy = ds.data[0]?.year, ly = ds.data[ds.data.length - 1]?.year;
              coParas.push(p(t(
                `${ds.metric_label}: ${fv?.toLocaleString('cs-CZ')} → ${lv?.toLocaleString('cs-CZ')} (období ${fy}–${ly})`,
                { italic: true, color: '888888', size: 16 }
              )));
            }
          }
        }
        coParas.push(...srcParas([f.dataset]));
        return new TableRow({
          children: [
            cell(p(t(f.number || '', { bold: true, color: 'ED8B00', size: 32 }), { alignment: AlignmentType.CENTER })),
            cell(coParas),
            cell(p(t(f.explanation || ''))),
          ],
        });
      });
      children.push(new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        borders: tableBorders,
        rows: [kfHeader, ...kfRows],
      }));
    }

    // 7. Doporučené úhly
    if (analysis.angles?.length) {
      children.push(p(t('Doporučené úhly', { bold: true, size: 22 }), { spacing: { before: 300, after: 80 } }));
      children.push(p(t('Pozorování, ne hotové věty. Text tiskovky napiš sám.', { italic: true, color: '666666' }), { spacing: { after: 100 } }));
      const angHeader = new TableRow({
        children: [
          cell(p(t('', { bold: true })), { width: { size: 8, type: WidthType.PERCENTAGE } }),
          cell(p(t('Úhel', { bold: true })), { width: { size: 25, type: WidthType.PERCENTAGE } }),
          cell(p(t('Pozorování', { bold: true })), { width: { size: 45, type: WidthType.PERCENTAGE } }),
          cell(p(t('Riziko v tezi', { bold: true })), { width: { size: 22, type: WidthType.PERCENTAGE } }),
        ],
      });
      const angRows = analysis.angles.map((a, i) => new TableRow({
        children: [
          cell(p(t(String.fromCharCode(65 + i), { bold: true, size: 22 }), { alignment: AlignmentType.CENTER })),
          cell(p(t(a.label || '', { bold: true }))),
          cell([p(t(a.observation || '')), ...srcParas([...(a.datasets || []), ...(a.dataset ? [a.dataset] : [])])]),
          cell(p(t(a.risk || ''))),
        ],
      }));
      children.push(new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        borders: tableBorders,
        rows: [angHeader, ...angRows],
      }));
    }

    // 8. Co data NEPODPORUJÍ — červený nadpis, bullet list
    if (analysis.cannot_claim?.length) {
      children.push(p(t('Co data NEPODPORUJÍ', { bold: true, color: 'ED8B00', size: 22 }), { spacing: { before: 300, after: 100 } }));
      analysis.cannot_claim.forEach(c => {
        children.push(p(
          [t('„'), t(c.claim || '', { italic: true }), t(`" — ${c.why || ''}`)],
          { bullet: { level: 0 }, spacing: { after: 60 } }
        ));
      });
    }

    // 8b. Datová příloha — holá čísla pro každý vybraný dataset, žádný výklad
    const appendixTables = selectedDatasets.map(d => ({ d, table: datasetTable(d) })).filter(x => x.table);
    if (appendixTables.length) {
      children.push(p(t('Datová příloha', { bold: true, size: 22 }), { spacing: { before: 300, after: 60 } }));
      children.push(p(
        t('Holá čísla bez výkladu, tak jak je dodal zdroj.', { italic: true, color: '666666' }),
        { spacing: { after: 120 } }
      ));
      appendixTables.forEach(({ d, table }) => {
        children.push(p(t(d.human_name || d.label, { bold: true, size: 18 }), { spacing: { before: 180, after: table.note ? 20 : 60 } }));
        if (table.note) children.push(p(t(table.note, { italic: true, color: '888888', size: 16 }), { spacing: { after: 60 } }));
        const headerRow = new TableRow({
          children: table.headers.map((h, i) => cell(
            p(t(h, { bold: true, size: 16 }), { alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.RIGHT }),
            { shading: lightPurple }
          )),
        });
        const bodyRows = table.rows.map(row => new TableRow({
          children: row.map((c, i) => cell(
            p(t(c, { size: 16 }), { alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.RIGHT })
          )),
        }));
        children.push(new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          borders: tableBorders,
          rows: [headerRow, ...bodyRows],
        }));
      });
    }

    // 9. Zdroje + citační formule
    children.push(p(t('Zdroje', { bold: true, size: 22 }), { spacing: { before: 300, after: 100 } }));
    selectedDatasets.forEach(d => {
      const parts = [t(`${d.label} (${d.code}) — ${d.source}`)];
      if (d.source_url) {
        parts.push(t(' · Zdroj dat: '));
        parts.push(t(d.source_url, { color: '702082' }));
      }
      children.push(p(parts, { spacing: { after: 40 } }));
    });
    children.push(p(
      t('Citační formule: „…podle dat ÚZIS ČR / Eurostat (rok vždy uvést) …"', { italic: true, color: '666666' }),
      { spacing: { before: 120 } }
    ));

    // Sestavení dokumentu — Arial 9pt základ
    const doc = new Document({
      styles: { default: { document: { run: { font: 'Arial', size: 18 } } } },
      sections: [{ children }],
    });

    const blob = await Packer.toBlob(doc);
    const filename = `Brief_${CLIENT.id}_${slug(topic)}_${formatDateISO(new Date())}.docx`;
    saveAs(blob, filename);
  };

  if (loadingData) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Loader2 size={32} className="spin" />
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#FFFFFF' }}>
      {/* TOP BAR — fialová lišta OZP: vlevo logo + název nástroje, vpravo autor + API klíč */}
      <div style={{
        background: '#702082', color: '#FFFFFF', padding: '14px 24px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <img src={ozpLogo} alt="OZP" style={{ height: 26, display: 'block' }} />
          <span style={{ width: 1, height: 22, background: 'rgba(255,255,255,0.4)' }} />
          <span style={{ fontSize: 13, letterSpacing: '0.12em', textTransform: 'uppercase', fontWeight: 600 }}>
            Datový brief
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 11, opacity: 0.75 }}>by Omnimedia PR</span>
          <button
            onClick={() => setShowKeyModal(true)}
            style={{
              background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.4)', color: '#FFFFFF',
              padding: '5px 12px', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            <Key size={12} />
            {apiKey ? 'API klíč nastaven' : 'Zadat API klíč'}
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
        {error && (
          <div style={{ background: '#FBE9E6', color: '#5A1812', padding: 12, marginBottom: 16, fontSize: 14, borderRadius: 10 }}>
            Chyba: {error}
          </div>
        )}

        {/* STEP 1: ZADÁNÍ */}
        <section style={{ marginBottom: 48 }}>
          <SectionHeader number="01" title="Zadání briefu" subtitle="Napiš, o čem má být brief" />
          <div style={{ marginTop: 16 }}>
            <div style={{
              background: '#FFFFFF', border: '1.5px solid #E0D6EA', borderRadius: 16,
              boxShadow: '0 2px 14px rgba(112,32,130,0.07)',
            }}>
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                rows={3}
                placeholder="Napiš, o čem má být brief — třeba „trendy v české onkologii“ nebo „prevence srdečních a cévních onemocnění“…"
                style={{
                  width: '100%', resize: 'vertical', minHeight: 88, padding: '16px 18px',
                  fontSize: 16, lineHeight: 1.5, border: 'none', outline: 'none',
                  background: 'transparent', fontFamily: 'inherit', color: '#333', borderRadius: 16,
                }}
              />
            </div>
          </div>

          {/* Volba rozsahu dat — jen ČR vs. i mezinárodní srovnání (bod 3) */}
          <label style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={includeIntl}
              onChange={(e) => setIncludeIntl(e.target.checked)}
              style={{ width: 16, height: 16, cursor: 'pointer' }}
            />
            <span>Zahrnout mezinárodní srovnání (EU/OECD) — jinak nástroj pracuje jen s českými daty</span>
          </label>

          {/* AI doporučení datasetů */}
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button
              onClick={recommendDatasets}
              disabled={recommending || !topic.trim() || loadingData}
              style={{
                background: '#702082', color: '#FFFFFF', padding: '10px 20px',
                border: 'none', fontSize: 14, fontWeight: 600,
                cursor: (recommending || !topic.trim() || loadingData) ? 'not-allowed' : 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 8,
                opacity: (recommending || !topic.trim() || loadingData) ? 0.5 : 1,
              }}
            >
              {recommending ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
              {recommending ? 'Hledám relevantní data…' : 'Najít relevantní data'}
            </button>
            <button
              onClick={() => setBrowseAll(true)}
              disabled={loadingData}
              style={{
                background: 'transparent', border: '1px solid #702082', color: '#702082',
                padding: '10px 16px', fontSize: 13, fontWeight: 600,
                cursor: loadingData ? 'not-allowed' : 'pointer', opacity: loadingData ? 0.5 : 1,
              }}
            >
              Procházet celý katalog ručně
            </button>
            <span style={{ fontSize: 12, color: '#666', flex: 1, minWidth: 180 }}>
              AI projde katalog a vybere datasety k tématu. Výběr pak zúžíš odškrtáním karet níže.
            </span>
          </div>

          {recommendations && (
            <div style={{ marginTop: 16, padding: 16, background: '#F4F1F8', border: '1px solid #E0D6EA', borderRadius: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#702082', marginBottom: 12 }}>
                AI doporučila {recommendations.length} {recommendations.length === 1 ? 'dataset' : recommendations.length < 5 ? 'datasety' : 'datasetů'}
              </div>
              <div style={{ display: 'grid', gap: 8 }}>
                {recommendations.map(r => {
                  const meta = allDatasets.find(d => d.id === r.id);
                  if (!meta) return null;
                  return (
                    <div key={r.id} style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 12, fontSize: 13, alignItems: 'baseline' }}>
                      <div style={{ fontWeight: 600, color: '#702082' }}>{meta.human_name || meta.label || r.id}</div>
                      <div style={{ color: '#444', lineHeight: 1.45 }}>{r.reason}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Klidná hláška, když k tématu nejsou vhodná data (bod 1) — žádná červená lišta */}
          {noResults && (
            <div style={{ marginTop: 16, padding: 16, background: '#FBF6E9', border: '1px solid #E4D8B0', color: '#5A4A12', fontSize: 14, lineHeight: 1.5, borderRadius: 10 }}>
              {noResults}
            </div>
          )}
        </section>

        {/* STEP 2: DATA — zobrazí se až po doporučení nebo otevření katalogu (bod 2) */}
        {showDataSection && (
          <section style={{ marginBottom: 48 }}>
            <SectionHeader number="02" title="Datová opora" subtitle="Šedý badge = česká data, modrý EU/OECD = mezinárodní srovnání. Odškrtnutím karty dataset z briefu vyřadíš." />
            <div style={{ marginTop: 12, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: '#444' }}>
                Vybráno {selectedIds.length} {selectedIds.length === 1 ? 'dataset' : selectedIds.length < 5 ? 'datasety' : 'datasetů'}
                {!browseAll && recommendations ? ` z ${recommendations.length} doporučených` : ''}.
              </span>
              <button
                onClick={() => setBrowseAll(v => !v)}
                style={{
                  background: 'transparent', border: '1px solid #999', color: '#444',
                  padding: '6px 12px', fontSize: 12, cursor: 'pointer',
                }}
              >
                {browseAll ? 'Zobrazit jen doporučené' : `Procházet celý katalog (${allDatasets.length})`}
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16, marginTop: 12 }}>
              {displayedDatasets.map(d => (
                d.kind === 'snapshot' ? (
                  <SnapshotCard
                    key={d.id}
                    d={d}
                    selected={selectedIds.includes(d.id)}
                    onToggle={() => toggleDataset(d.id)}
                  />
                ) : d.kind === 'cube' ? (
                  <CubeCard
                    key={d.id}
                    d={d}
                    selected={selectedIds.includes(d.id)}
                    onToggle={() => toggleDataset(d.id)}
                    filter={cubeFilterOf(d.id)}
                    onFilter={(f) => setCubeFilter(d.id, f)}
                  />
                ) : (
                  <DatasetCard
                    key={d.id}
                    d={d}
                    selected={selectedIds.includes(d.id)}
                    onToggle={() => toggleDataset(d.id)}
                  />
                )
              ))}
            </div>
          </section>
        )}

        {/* STEP 3: ANALÝZA — zobrazí se, až je vybraný aspoň jeden dataset */}
        {(selectedDatasets.length > 0 || analysis) && (
        <section style={{ marginBottom: 48 }}>
          <SectionHeader number="03" title="Analýza" subtitle="Strukturovaná zjištění a doporučené úhly" />
          {!analysis ? (
            <div style={{ marginTop: 16 }}>
              <button
                onClick={runAnalysis}
                disabled={analyzing || selectedDatasets.length === 0 || selectedLoading}
                style={{
                  background: '#702082', color: '#FFFFFF', padding: '12px 24px',
                  border: 'none', fontSize: 15, fontWeight: 600,
                  cursor: (analyzing || selectedDatasets.length === 0 || selectedLoading) ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', gap: 8,
                  opacity: (analyzing || selectedDatasets.length === 0 || selectedLoading) ? 0.5 : 1,
                }}
              >
                {(analyzing || selectedLoading) ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                {analyzing ? 'Analyzuji…' : selectedLoading ? 'Data se načítají…' : `Analyzovat ${selectedDatasets.length} datasety`}
              </button>
            </div>
          ) : (
            <>
              <AnalysisView analysis={analysis} datasets={selectedDatasets} onRerun={() => { setAnalysis(null); runAnalysis(); }} />
              <div style={{ marginTop: 16 }}>
                <button
                  onClick={exportToDocx}
                  style={{
                    background: '#702082', color: '#FFFFFF', padding: '10px 20px',
                    border: 'none', fontSize: 14, fontWeight: 600, cursor: 'pointer',
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                  }}
                >
                  <Download size={16} />
                  Stáhnout .docx onepager
                </button>
              </div>
            </>
          )}
        </section>
        )}
      </div>

      {showKeyModal && (
        <ApiKeyModal
          currentKey={apiKey}
          onSave={(k) => { setApiKey(k); setShowKeyModal(false); }}
          onClose={apiKey ? () => setShowKeyModal(false) : null}
        />
      )}

      <style>{`
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

// ============================================================
// POMOCNÉ KOMPONENTY
// ============================================================

const inputStyle = {
  width: '100%', padding: '10px 12px', fontSize: 15,
  border: '1.5px solid #702082', background: '#FFFFFF', fontFamily: 'inherit',
};

function Label({ children }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
      textTransform: 'uppercase', color: '#555', marginBottom: 6,
    }}>{children}</div>
  );
}

function SectionHeader({ number, title, subtitle }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 8 }}>
      <span className="num serif" style={{ fontSize: 32, fontWeight: 700, color: '#702082' }}>{number}</span>
      <div>
        <h2 className="serif" style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>{title}</h2>
        {subtitle && <div style={{ fontSize: 13, color: '#666', marginTop: 2 }}>{subtitle}</div>}
      </div>
    </div>
  );
}

// Karta souhrnu (snapshot) — popisná čísla o stavu, žádná časová řada ani anomálie.
function SnapshotCard({ d, selected, onToggle }) {
  const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('cs-CZ') : n);
  return (
    <div onClick={onToggle} style={{
      background: '#FFFFFF', border: selected ? '2px solid #702082' : '1px solid #E0D6EA',
      padding: 20, cursor: 'pointer', position: 'relative', borderRadius: 14, gridColumn: '1 / -1',
      boxShadow: selected ? '0 6px 22px rgba(112,32,130,0.18)' : '0 1px 6px rgba(112,32,130,0.06)',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', padding: '2px 6px', background: '#702082', color: '#FFFFFF' }}>Souhrn</span>
        <div style={{ width: 22, height: 22, border: '1.5px solid #702082', display: 'flex', alignItems: 'center', justifyContent: 'center', background: selected ? '#702082' : 'transparent', flexShrink: 0, borderRadius: 6 }}>
          {selected && <Check size={14} color="#FFFFFF" />}
        </div>
      </div>
      <div className="serif" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.2, marginBottom: 4 }}>{d.human_name}</div>
      {d.description && <div style={{ fontSize: 13, color: '#555', lineHeight: 1.45, marginBottom: 12 }}>{d.description}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 10 }}>
        {(d.snapshot || []).map((s, i) => (
          <div key={i} style={{ background: '#F4F1F8', borderRadius: 10, padding: '10px 12px' }}>
            <div className="num" style={{ fontSize: 22, fontWeight: 700, color: '#702082' }}>{fmt(s.value)}</div>
            <div style={{ fontSize: 12, color: '#555', marginTop: 2, lineHeight: 1.3 }}>{s.label}</div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 10, color: '#888', marginTop: 12 }}>
        Data: {d.source}{d.snapshot_date ? ` · stav k ${d.snapshot_date}` : ''}
      </div>
    </div>
  );
}

// Karta rozpadové kostky — zužovátka (diagnóza/věk/pohlaví/stadium), graf řezu a panel anomálií.
function CubeCard({ d, selected, onToggle, filter, onFilter }) {
  const cube = d.cube;
  const series = d.data || [];
  const first = series[0], last = series[series.length - 1];
  const trendColor = d.trend === 'up' ? '#1F6F47' : d.trend === 'down' ? '#9A2A1F' : '#7A6F2A';
  const trendWord = d.trend === 'up' ? 'Růst' : d.trend === 'down' ? 'Pokles' : 'Změna';
  const fmt = (n) => n.toLocaleString('cs-CZ');
  const stop = (e) => e.stopPropagation();
  const set = (key, val) => onFilter({ ...filter, [key]: val });
  const selStyle = { padding: '6px 8px', fontSize: 13, border: '1.5px solid #E0D6EA', background: '#FFFFFF', fontFamily: 'inherit', color: '#333', maxWidth: '100%' };
  const lbl = { fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#702082', marginBottom: 4 };

  const anomLabel = (a) => {
    if (a.type === 'trend') return `${a.pct > 0 ? '▲' : '▼'} ${a.name} ${a.pct > 0 ? '+' : ''}${a.pct} %${a.artifact_risk ? ' ⚠' : ''}`;
    if (a.type === 'vek_posun') return `mladší 50: ${a.name} ${a.diff > 0 ? '+' : ''}${a.diff} b.b.`;
    if (a.type === 'stadium_posun') return `pozdní záchyt: ${a.name} ${a.diff > 0 ? '+' : ''}${a.diff} b.b.`;
    return a.name;
  };

  return (
    <div onClick={onToggle} style={{
      background: '#FFFFFF', border: selected ? '2px solid #702082' : '1px solid #E0D6EA',
      padding: 20, cursor: 'pointer', position: 'relative', borderRadius: 14, gridColumn: '1 / -1',
      boxShadow: selected ? '0 6px 22px rgba(112,32,130,0.18)' : '0 1px 6px rgba(112,32,130,0.06)',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', padding: '2px 6px', background: '#702082', color: '#FFFFFF' }}>Rozpad dat</span>
        <div style={{ width: 22, height: 22, border: '1.5px solid #702082', display: 'flex', alignItems: 'center', justifyContent: 'center', background: selected ? '#702082' : 'transparent', flexShrink: 0, borderRadius: 6 }}>
          {selected && <Check size={14} color="#FFFFFF" />}
        </div>
      </div>

      <div className="serif" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.2, marginBottom: 4 }}>
        {cube?.human_name || d.human_name || 'Onkologie — rozpad'}
      </div>

      {d._loading && (
        <div style={{ background: '#F4F1F8', padding: '10px 12px', margin: '8px 0', fontSize: 12, color: '#666', display: 'flex', alignItems: 'center', gap: 8, borderRadius: 8 }}>
          <Loader2 size={14} className="spin" /> Načítám rozpadovou kostku…
        </div>
      )}
      {d._error && (
        <div style={{ background: '#FBEFEC', padding: '10px 12px', margin: '8px 0', fontSize: 12, color: '#9A2A1F', borderRadius: 8 }}>
          Nelze načíst kostku: {d._error}
        </div>
      )}

      {cube && (
        <>
          {/* Zužovátka — dynamicky podle dimenzí kostky */}
          <div onClick={stop} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, margin: '12px 0' }}>
            {cube.dims.map(dim => {
              if (dim.kind !== 'age' && dim.values.length <= 1) return null; // skryj jednohodnotové
              const hasLate = dim.kind !== 'age' && dim.values.some(v => valKey(v) === 'III') && dim.values.some(v => valKey(v) === 'IV');
              return (
                <div key={dim.key}>
                  <div style={lbl}>{dim.label}</div>
                  <select value={filter[dim.key] || 'vše'} onChange={(e) => set(dim.key, e.target.value)} style={selStyle}>
                    <option value="vše">{dim.primary ? 'všechny sledované' : 'vše'}</option>
                    {dim.kind === 'age'
                      ? ['do 50', '50–64', '65+'].map(o => <option key={o} value={o}>{o === 'do 50' ? 'mladší 50' : o}</option>)
                      : dim.values.map(v => <option key={valKey(v)} value={valKey(v)}>{valName(v)}</option>)}
                    {hasLate && <option value="pozdní (III+IV)">pozdní (III+IV)</option>}
                  </select>
                </div>
              );
            })}
          </div>

          {/* Graf řezu */}
          {first && last ? (
            <>
              <div style={{ fontSize: 13, color: trendColor, fontWeight: 600, marginBottom: 4 }}>
                {trendWord} {d.delta > 0 ? '+' : ''}{d.delta}{' %'} — {fmt(first.value)} ({first.year}) → {fmt(last.value)} ({last.year})
              </div>
              <div style={{ height: 70, margin: '4px -4px 8px' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={series} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                    <Line type="monotone" dataKey="value" stroke={trendColor} strokeWidth={1.8} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <div style={{ fontSize: 13, color: '#888', margin: '8px 0' }}>Pro tento výřez nejsou data.</div>
          )}

          {/* Panel anomálií */}
          {cube.anomalies?.length > 0 && (
            <div onClick={stop} style={{ marginTop: 8, padding: 12, background: '#F4F1F8', borderRadius: 10, border: '1px solid #E0D6EA' }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#702082', marginBottom: 8 }}>
                Nalezené anomálie — klikni a promítne se do grafu i briefu
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {cube.anomalies.slice(0, 8).map((a, i) => (
                  <button key={i} onClick={() => { onFilter(anomalyToFilter(cube, a)); if (!selected) onToggle(); }}
                    title={a.artifact_risk ? 'Pozor: možná změna kódování v čase' : ''}
                    style={{ fontSize: 12, padding: '5px 10px', background: '#FFFFFF', border: '1px solid #D9C9E6', color: '#5a2a6a', cursor: 'pointer', borderRadius: 999 }}>
                    {anomLabel(a)}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 8 }}>⚠ = u této diagnózy hrozí, že skok je změnou kódování, ne reálným trendem — ověř.</div>
            </div>
          )}

          <div style={{ fontSize: 10, color: '#888', marginTop: 12 }}>
            Data: {cube.source || 'ÚZIS ČR'} · {cube.years[0]}–{cube.years[cube.years.length - 1]}
          </div>
        </>
      )}
    </div>
  );
}

function DatasetCard({ d, selected, onToggle }) {
  const isInternational = d.source_type === 'international';
  const isRegional = d.source_type === 'regional_snapshot';
  const isRegionalTS = d.source_type === 'regional_timeseries';
  const isStandardSeries = !isRegional && !isRegionalTS;
  const peakVal = isStandardSeries && d.peakYear ? d.data.find(x => x.year === d.peakYear)?.value : null;
  const first = isStandardSeries ? d.data?.[0] : null;
  const last = isStandardSeries ? d.data?.[d.data.length - 1] : null;
  const trendColor = d.trend === 'up' ? '#1F6F47' : d.trend === 'down' ? '#9A2A1F' : '#7A6F2A';
  const trendWord = d.trend === 'up' ? 'Růst' : d.trend === 'down' ? 'Pokles' : 'Změna';
  const fmtNum = (n) => n.toLocaleString('cs-CZ');
  const title = d.human_name || d.label;
  const showTechLabel = d.label && d.human_name && d.human_name !== d.label;

  return (
    <div onClick={onToggle} style={{
      background: '#FFFFFF', border: selected ? '2px solid #702082' : '1px solid #E0D6EA',
      padding: 20, cursor: 'pointer', position: 'relative', borderRadius: 14,
      boxShadow: selected ? '0 6px 22px rgba(112,32,130,0.18)' : '0 1px 6px rgba(112,32,130,0.06)',
    }}>
      {/* 1. Badge + checkbox */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
          padding: '2px 6px',
          background: isInternational ? '#702082' : '#444', color: '#FFFFFF',
        }}>{isInternational ? 'EU/OECD' : 'Česká data'}</span>
        <div style={{
          width: 22, height: 22, border: '1.5px solid #702082',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: selected ? '#702082' : 'transparent', flexShrink: 0,
        }}>
          {selected && <Check size={14} color="#FFFFFF" />}
        </div>
      </div>

      {/* 2. Velký lidský název (s fallbackem na label, pokud human_name chybí) */}
      {title && (
        <div className="serif" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.2, marginBottom: 2 }}>
          {title}
        </div>
      )}

      {/* 3. Technický název v závorce — jen pokud se liší od lidského */}
      {showTechLabel && (
        <div style={{ fontSize: 12, color: '#888', marginBottom: 10 }}>
          ({d.label})
        </div>
      )}

      {/* 4. Description */}
      {d.description && (
        <div style={{ fontSize: 14, color: '#333', lineHeight: 1.45, marginBottom: 14 }}>
          {d.description}
        </div>
      )}

      {/* 4b. Lazy-fetch stavová zpráva — loading / error / nevybraný */}
      {d._loading && (
        <div style={{
          background: '#F4F1F8', padding: '10px 12px', margin: '4px 0 8px',
          fontSize: 12, color: '#666', display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <Loader2 size={14} className="spin" />
          Načítám data z {d.source || 'zdroje'}…
        </div>
      )}
      {d._error && (
        <div style={{
          background: '#FBEFEC', padding: '10px 12px', margin: '4px 0 8px',
          fontSize: 12, color: '#9A2A1F',
        }}>
          Nelze stáhnout data: {d._error}
        </div>
      )}
      {!d._loading && !d._error && !d._hasData && !selected && (
        <div style={{
          background: '#F4F1F8', padding: '10px 12px', margin: '4px 0 8px',
          fontSize: 12, color: '#888', fontStyle: 'italic',
        }}>
          Vyber kartu pro načtení dat ze zdroje.
        </div>
      )}

      {/* 5a. Pro regional snapshot: geo mapa + bar chart per kraj */}
      {isRegional && d.data?.length > 0 && (
        <div style={{ margin: '4px 0 8px' }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#888', marginBottom: 8 }}>
            {d.metric_label || `Kraje (${d.snapshot_year})`}
          </div>
          <RegionalMap data={d.data} peakRegion={d.peakRegion} />
          <div style={{ marginTop: 8 }}>
            <RegionalBars data={d.data} peakRegion={d.peakRegion} />
          </div>
        </div>
      )}

      {/* 5c. Pro regional_timeseries: heatmap (roky × kraje) */}
      {isRegionalTS && d.data?.length > 0 && (
        <div style={{ margin: '4px 0 8px' }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#888', marginBottom: 8 }}>
            {d.metric_label || `Vývoj per kraj (${d.coverage})`}
          </div>
          <RegionalHeatmap data={d.data} />
        </div>
      )}

      {/* 5b. Pro národní časové řady: metric line + delta line + graf */}
      {!isInternational && !isRegional && !isRegionalTS && first && last && (
        <>
          {d.metric_label && (
            <div style={{ fontSize: 13, color: '#702082', marginBottom: 4 }}>
              {d.metric_label}: <strong className="num">{fmtNum(first.value)} → {fmtNum(last.value)}</strong> případů
            </div>
          )}
          {typeof d.delta === 'number' && (
            <div style={{ fontSize: 13, color: trendColor, fontWeight: 600, marginBottom: 8 }}>
              {trendWord} {d.delta > 0 ? '+' : ''}{d.delta}{'\u202F%'}{d.coverage ? `, období ${d.coverage}` : ''}
            </div>
          )}
          <div style={{ height: 60, margin: '8px -4px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                <Line type="monotone" dataKey="value" stroke={trendColor} strokeWidth={1.8} dot={false} />
                {peakVal && <ReferenceDot x={d.peakYear} y={peakVal} r={4} fill={trendColor} stroke="#FFFFFF" strokeWidth={1.5} />}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {/* 6. Pro mezinárodní: comparison bar chart */}
      {isInternational && d.comparison && (
        <div style={{ margin: '4px 0 8px' }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#888', marginBottom: 8 }}>
            Srovnání zemí ({d.coverage})
          </div>
          <ComparisonBars rows={d.comparison} />
        </div>
      )}

      {/* 7. Šedý box "Užitečné pro:" */}
      {d.relevant_for && d.relevant_for.length > 0 && (
        <div style={{
          background: isInternational ? '#F4F1F8' : '#F4F1F8',
          padding: '10px 12px', marginTop: 12,
        }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#666', marginBottom: 6 }}>
            Užitečné pro:
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {d.relevant_for.map((t, i) => (
              <span key={i} style={{
                fontSize: 11, padding: '2px 8px', background: '#FFFFFF',
                border: '1px solid #E0D6EA', color: '#333',
              }}>{t}</span>
            ))}
          </div>
        </div>
      )}

      {/* 8. Data / kód / aktualizováno — kód je klikatelný link na source_url */}
      <div style={{ fontSize: 10, color: '#888', marginTop: 12, lineHeight: 1.4 }}>
        {isInternational ? 'Data: ' : 'Data: ÚZIS ČR'}
        {isInternational && d.source}
        {d.code && (
          <>
            {' · '}
            {!isInternational && 'diagnostický kód '}
            {d.source_url ? (
              <a
                href={d.source_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                style={{ color: '#702082', textDecoration: 'underline' }}
              >{d.code}</a>
            ) : d.code}
          </>
        )}
        {d.updated && ` · aktualizováno ${d.updated}`}
      </div>
    </div>
  );
}

// Geografické pozice 14 NUTS-3 krajů ČR v 4×6 gridu (orientační rozložení mapy).
const KRAJ_GRID = {
  "CZ041": [0, 0],  // Karlovarský    (severozápad)
  "CZ042": [0, 1],  // Ústecký
  "CZ051": [0, 2],  // Liberecký
  "CZ052": [0, 3],  // Královéhradecký
  "CZ032": [1, 0],  // Plzeňský
  "CZ010": [1, 1],  // Praha
  "CZ020": [1, 2],  // Středočeský
  "CZ053": [1, 3],  // Pardubický
  "CZ080": [1, 5],  // Moravskoslezský (severovýchod)
  "CZ031": [2, 1],  // Jihočeský
  "CZ063": [2, 2],  // Vysočina
  "CZ071": [2, 4],  // Olomoucký
  "CZ072": [2, 5],  // Zlínský
  "CZ064": [3, 3],  // Jihomoravský    (jih)
};

function RegionalMap({ data, peakRegion }) {
  // Zjednodušená geografická "mapa" ČR jako grid — pro PR brief stačí
  // orientační rozložení, ne přesné geografické tvary.
  const maxVal = Math.max(...data.map(r => r.value));
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(6, 1fr)',
      gridTemplateRows: 'repeat(4, 56px)',
      gap: 3,
      marginBottom: 4,
    }}>
      {data.map(r => {
        const pos = KRAJ_GRID[r.kraj_kod];
        if (!pos) return null;
        const [row, col] = pos;
        const intensity = maxVal > 0 ? r.value / maxVal : 0;
        const isPeak = r.kraj_nazev === peakRegion;
        const bgColor = isPeak
          ? '#ed8b00'
          : `rgba(112, 32, 130, ${0.15 + intensity * 0.75})`;
        return (
          <div
            key={r.kraj_kod}
            title={`${r.kraj_nazev}: ${r.value.toLocaleString('cs-CZ')}`}
            style={{
              gridRow: row + 1,
              gridColumn: col + 1,
              background: bgColor,
              color: '#FFFFFF',
              padding: '4px 6px',
              fontSize: 9,
              lineHeight: 1.15,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ fontWeight: 600, opacity: 0.95 }}>
              {r.kraj_nazev.length > 10 ? r.kraj_nazev.slice(0, 9) + '.' : r.kraj_nazev}
            </div>
            <div className="num" style={{ fontSize: 11, fontWeight: 700, textAlign: 'right' }}>
              {r.value.toLocaleString('cs-CZ')}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RegionalHeatmap({ data }) {
  // data je list [{year, kraj_kod, kraj_nazev, value}].
  // Vykreslíme jako matrix: řádky = kraje, sloupce = roky, intenzita = value.
  const years = [...new Set(data.map(r => r.year))].sort((a, b) => a - b);
  const krajeMap = new Map();
  for (const r of data) {
    if (!krajeMap.has(r.kraj_kod)) krajeMap.set(r.kraj_kod, { kraj_kod: r.kraj_kod, kraj_nazev: r.kraj_nazev, total: 0 });
    krajeMap.get(r.kraj_kod).total += r.value;
  }
  const kraje = [...krajeMap.values()].sort((a, b) => b.total - a.total);
  const lookup = {};
  for (const r of data) lookup[`${r.kraj_kod}_${r.year}`] = r.value;
  const allValues = data.map(r => r.value);
  const maxVal = Math.max(...allValues);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: `100px repeat(${years.length}, 1fr)`, gap: 1, fontSize: 9 }}>
      <div></div>
      {years.map(y => <div key={y} style={{ textAlign: 'center', fontWeight: 600, color: '#666' }}>{y}</div>)}
      {kraje.map(k => (
        <React.Fragment key={k.kraj_kod}>
          <div style={{ paddingRight: 4, color: '#444', textAlign: 'right', alignSelf: 'center' }}>
            {k.kraj_nazev.length > 12 ? k.kraj_nazev.slice(0, 11) + '.' : k.kraj_nazev}
          </div>
          {years.map(y => {
            const val = lookup[`${k.kraj_kod}_${y}`] || 0;
            const intensity = maxVal > 0 ? val / maxVal : 0;
            return (
              <div
                key={y}
                title={`${k.kraj_nazev}, ${y}: ${val.toLocaleString('cs-CZ')}`}
                style={{
                  background: `rgba(112, 32, 130, ${0.1 + intensity * 0.85})`,
                  height: 22,
                  color: intensity > 0.5 ? '#FFF' : '#444',
                  fontSize: 9,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 600,
                }}
              >
                {val.toLocaleString('cs-CZ')}
              </div>
            );
          })}
        </React.Fragment>
      ))}
    </div>
  );
}

function RegionalBars({ data, peakRegion }) {
  // Seřadit kraje sestupně podle hodnoty pro lepší čitelnost.
  const sorted = [...data].sort((a, b) => b.value - a.value);
  const maxVal = Math.max(...sorted.map(r => r.value));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {sorted.map((r, i) => {
        const width = maxVal > 0 ? (r.value / maxVal) * 100 : 0;
        const isPeak = r.kraj_nazev === peakRegion;
        const color = isPeak ? '#ed8b00' : '#70208288';
        return (
          <div key={r.kraj_kod} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 60px', gap: 8, alignItems: 'center', fontSize: 11 }}>
            <span style={{ fontWeight: isPeak ? 700 : 400, color: isPeak ? '#702082' : '#444' }}>{r.kraj_nazev}</span>
            <div style={{ height: 12, background: '#F0ECF5', position: 'relative' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${width}%`, background: color }} />
            </div>
            <span className="num" style={{ textAlign: 'right', fontWeight: isPeak ? 700 : 400 }}>
              {r.value.toLocaleString('cs-CZ')}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ComparisonBars({ rows }) {
  const maxVal = Math.max(...rows.map(r => Math.abs(r.value)));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {rows.map((r, i) => {
        const width = (Math.abs(r.value) / maxVal) * 100;
        const color = r.isUs ? '#ed8b00' : (r.hi ? '#9A2A1F88' : '#70208288');
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 50px', gap: 8, alignItems: 'center', fontSize: 11 }}>
            <span style={{ fontWeight: r.isUs ? 700 : 400, color: r.isUs ? '#702082' : '#444' }}>{r.country}</span>
            <div style={{ height: 12, background: '#F0ECF5', position: 'relative' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${width}%`, background: color }}/>
            </div>
            <span className="num" style={{ textAlign: 'right', fontWeight: r.isUs ? 700 : 400 }}>
              {typeof r.value === 'number' && r.value % 1 !== 0 ? r.value.toFixed(1) : r.value}{'\u202F%'}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// Prostá, neinterpretovaná tabulka pro libovolný typ datasetu — jediný zdroj pravdy
// pro datový podklad v appce i v docx, aby se nikdy nerozešly. Vrací { headers, rows, note }
// s už naformátovanými řetězci (cs-CZ), nebo null, když dataset ještě nemá data.
function datasetTable(d) {
  const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('cs-CZ') : String(n ?? ''));

  // 1. Souhrn (snapshot) — ukazatel → hodnota
  if (d.kind === 'snapshot' && Array.isArray(d.snapshot) && d.snapshot.length) {
    return {
      headers: ['Ukazatel', 'Hodnota'],
      rows: d.snapshot.map(s => [s.label, fmt(s.value)]),
      note: d.snapshot_date ? `Stav k ${d.snapshot_date}` : null,
    };
  }

  // 2. Mezinárodní srovnání — země → hodnota (heuristika na %, stejná jako v kartě/docx)
  if (d.source_type === 'international' && Array.isArray(d.comparison) && d.comparison.length) {
    const fmtIntl = (v) => (typeof v === 'number'
      ? `${v.toLocaleString('cs-CZ')}${Math.abs(v) < 200 ? ' %' : ''}`
      : String(v ?? ''));
    return {
      headers: ['Země', 'Hodnota'],
      rows: d.comparison.map(c => [c.country, fmtIntl(c.value)]),
      note: d.coverage ? `Rok / období: ${d.coverage}` : null,
    };
  }

  // 3. Krajský snímek — kraj → hodnota (seřazeno sestupně, jako v kartě)
  if (d.source_type === 'regional_snapshot' && Array.isArray(d.data) && d.data.length) {
    const sorted = [...d.data].sort((a, b) => b.value - a.value);
    return {
      headers: ['Kraj', d.metric_label || 'Hodnota'],
      rows: sorted.map(r => [r.kraj_nazev, fmt(r.value)]),
      note: d.snapshot_year ? `Rok: ${d.snapshot_year}` : null,
    };
  }

  // 4. Krajská časová řada — matice kraj × rok
  if (d.source_type === 'regional_timeseries' && Array.isArray(d.data) && d.data.length) {
    const years = [...new Set(d.data.map(r => r.year))].sort((a, b) => a - b);
    const krajMap = new Map();
    for (const r of d.data) {
      if (!krajMap.has(r.kraj_kod)) krajMap.set(r.kraj_kod, { nazev: r.kraj_nazev, vals: {} });
      krajMap.get(r.kraj_kod).vals[r.year] = r.value;
    }
    return {
      headers: ['Kraj', ...years.map(String)],
      rows: [...krajMap.values()].map(k => [k.nazev, ...years.map(y => (k.vals[y] != null ? fmt(k.vals[y]) : '–'))]),
      note: d.metric_label || null,
    };
  }

  // 5. Národní časová řada nebo řez rozpadovou kostkou — rok → hodnota
  if (Array.isArray(d.data) && d.data.length) {
    return {
      headers: ['Rok', d.metric_label || 'Hodnota'],
      rows: d.data.map(r => [String(r.year), fmt(r.value)]),
      note: d.kind === 'cube' ? 'Aktuální výřez kostky (viz název výše)' : null,
    };
  }

  return null;
}

// Datový podklad pro analýzu — pro každý vybraný dataset prostá tabulka všech čísel,
// bez výkladu. Zrcadlí „Datovou přílohu" v docx.
function DataAppendix({ datasets }) {
  const tables = datasets.map(d => ({ d, table: datasetTable(d) })).filter(x => x.table);
  if (!tables.length) return null;
  return (
    <>
      <h3 className="serif" style={{ fontSize: 20, marginBottom: 4 }}>Datový podklad</h3>
      <div style={{ fontSize: 13, color: '#666', marginBottom: 16 }}>
        Holá čísla bez výkladu — tak, jak je dodal zdroj. Podklad, ze kterého si uděláš vlastní obrázek.
      </div>
      <div style={{ display: 'grid', gap: 20, marginBottom: 24 }}>
        {tables.map(({ d, table }) => (
          <div key={d.id} style={{ padding: 16, background: '#FFFFFF', border: '1px solid #E0D6EA', borderRadius: 12 }}>
            <div className="serif" style={{ fontSize: 16, fontWeight: 600, marginBottom: 2 }}>{d.human_name || d.label}</div>
            {table.note && <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{table.note}</div>}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: 13, minWidth: '100%' }}>
                <thead>
                  <tr>
                    {table.headers.map((h, i) => (
                      <th key={i} style={{
                        textAlign: i === 0 ? 'left' : 'right', padding: '5px 10px',
                        borderBottom: '2px solid #702082', color: '#702082', fontWeight: 700, whiteSpace: 'nowrap',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, ri) => (
                    <tr key={ri} style={{ background: ri % 2 ? '#F8F5FB' : '#FFFFFF' }}>
                      {row.map((c, ci) => (
                        <td key={ci} className={ci === 0 ? '' : 'num'} style={{
                          textAlign: ci === 0 ? 'left' : 'right', padding: '3px 10px', whiteSpace: 'nowrap', color: '#333',
                        }}>{c}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ fontSize: 11, color: '#888', marginTop: 8 }}>
              Zdroj: {d.source_url
                ? <a href={d.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#702082' }}>{d.source || d.source_url}</a>
                : (d.source || 'ÚZIS ČR')}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

// Najde dataset podle id v seznamu — prompt instruuje AI vracet id v poli `dataset`,
// fallback na human_name/label pro robustnost, kdyby AI instrukci nedodržela.
function findDatasetById(idOrName, datasets) {
  if (!idOrName || !datasets) return null;
  return datasets.find(d =>
    d.id === idOrName || d.human_name === idOrName || d.label === idOrName
  ) || null;
}

function AnalysisView({ analysis, datasets, onRerun }) {
  return (
    <div style={{ marginTop: 16 }}>
      {analysis.meta_pattern && (
        <div style={{ background: '#702082', color: '#FFFFFF', padding: 20, marginBottom: 24, borderRadius: 14 }}>
          <div style={{ fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8, opacity: 0.7 }}>
            Co data dohromady říkají
          </div>
          <div className="serif" style={{ fontSize: 18, lineHeight: 1.5, fontStyle: 'italic' }}>
            {analysis.meta_pattern}
          </div>
        </div>
      )}

      <h3 className="serif" style={{ fontSize: 20, marginBottom: 12 }}>Klíčová zjištění</h3>
      <div style={{ display: 'grid', gap: 8, marginBottom: 24 }}>
        {analysis.key_findings?.map((f, i) => {
          const ds = findDatasetById(f.dataset, datasets);
          const dsName = ds ? (ds.human_name || ds.label) : null;
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '100px 1fr', gap: 12, padding: 12, background: '#FFFFFF', border: '1px solid #E0D6EA', borderRadius: 12 }}>
              <div className="num serif" style={{ fontSize: 24, fontWeight: 700, color: '#ed8b00' }}>{f.number}</div>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 13, color: '#555' }}>{f.explanation}</div>
                {dsName && (
                  <div style={{ fontSize: 11, color: '#888', marginTop: 6 }}>
                    Zdroj: {ds.source_url ? (
                      <a href={ds.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#702082' }}>{dsName}</a>
                    ) : dsName}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <h3 className="serif" style={{ fontSize: 20, marginBottom: 12 }}>Doporučené úhly</h3>
      <div style={{ display: 'grid', gap: 12, marginBottom: 24 }}>
        {analysis.angles?.map((a, i) => {
          const srcIds = [...(a.datasets || []), ...(a.dataset ? [a.dataset] : [])];
          const seen = new Set();
          const uniq = srcIds.map(id => findDatasetById(id, datasets)).filter(d => d && !seen.has(d.id) && seen.add(d.id));
          return (
          <div key={i} style={{ padding: 16, background: '#FFFFFF', border: '1px solid #E0D6EA', borderRadius: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#666', marginBottom: 4 }}>
              Úhel {String.fromCharCode(65 + i)}
            </div>
            <div className="serif" style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{a.label}</div>
            <div style={{ fontSize: 14, color: '#333', lineHeight: 1.5, marginBottom: 8 }}>{a.observation}</div>
            {uniq.length > 0 && (
              <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                Zdroj: {uniq.map((ds, j) => (
                  <span key={ds.id}>{j > 0 ? ', ' : ''}{ds.source_url
                    ? <a href={ds.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#702082' }}>{ds.human_name || ds.label}</a>
                    : (ds.human_name || ds.label)}</span>
                ))}
              </div>
            )}
            {a.risk && (
              <div style={{ fontSize: 12, color: '#5A1812', background: '#FBE9E6', padding: 8, marginTop: 8, borderRadius: 8 }}>
                <strong>Riziko v tezi:</strong> {a.risk}
              </div>
            )}
          </div>
          );
        })}
      </div>

      {analysis.cannot_claim?.length > 0 && (
        <>
          <h3 className="serif" style={{ fontSize: 20, marginBottom: 12, color: '#ed8b00' }}>Co data NEPODPORUJÍ</h3>
          <div style={{ display: 'grid', gap: 8, marginBottom: 24 }}>
            {analysis.cannot_claim.map((c, i) => (
              <div key={i} style={{ padding: 12, background: '#FBE9E6', borderRadius: 10 }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>„{c.claim}"</div>
                <div style={{ fontSize: 13, color: '#5A1812' }}>{c.why}</div>
              </div>
            ))}
          </div>
        </>
      )}

      <DataAppendix datasets={datasets} />

      <button
        onClick={onRerun}
        style={{
          background: 'transparent', color: '#702082', padding: '8px 16px',
          border: '1.5px solid #702082', fontSize: 14, cursor: 'pointer',
        }}
      >
        Znovu analyzovat
      </button>
    </div>
  );
}
