import React, { useState, useEffect, useMemo } from 'react';
import { LineChart, Line, ResponsiveContainer, ReferenceDot } from 'recharts';
import { ChevronRight, Check, Loader2, Sparkles, Key, X } from 'lucide-react';

// ============================================================
// KONSTANTY
// ============================================================

const CLIENTS = [
  { id: 'ozp', name: 'OZP', full: 'Oborová zdravotní pojišťovna', sector: 'Zdravotní pojištění' },
  { id: 'demo', name: 'Demo klient', full: 'Pro účely ukázky', sector: '—' },
];

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
    id: 'fh_detection',
    label: 'Detekce FH — mezinárodní srovnání programů',
    human_name: 'Dědičně vysoký cholesterol — diagnostika',
    description: 'Procento osob s dědičnou hypercholesterolemií, které jsou v zemi diagnostikovány.',
    code: 'MedPed / NL FH',
    source: 'Vrablík et al. / PLOS GPH', source_type: 'international', updated: '2016 / 2023', coverage: 'různé roky',
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
        background: '#FAFAF7', padding: 32, maxWidth: 540, width: '90%',
        border: '2px solid #1A1A1A', boxShadow: '8px 8px 0 #1A1A1A',
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
          Klíč si vygeneruj v <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" style={{ color: '#C9302C' }}>console.anthropic.com/settings/keys</a>.
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
              fontFamily: 'monospace', border: '1.5px solid #1A1A1A',
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
              padding: '10px 20px', background: '#1A1A1A', color: '#FAFAF7',
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
  const [client, setClient] = useState(CLIENTS[0]);
  const [topic, setTopic] = useState('Moderní léčba a genetika: proč se cholesterol týká i mladých');
  const [step, setStep] = useState(1);
  const [nationalDatasets, setNationalDatasets] = useState([]);
  const [loadingData, setLoadingData] = useState(true);
  const [selectedIds, setSelectedIds] = useState(['aim', 'cmp', 'eu_cvd_share', 'fh_detection']);
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);

  // Načti národní datasety ze static JSON souborů (generované GitHub Actions).
  // JSON už nese všechna pole včetně human_name, description, relevant_for, trend_context —
  // viz sync_nkis.py. Frontend nepřidává nic, jen prochází fetch.
  useEffect(() => {
    async function loadData() {
      const ids = ['aim', 'cmp', 'hyp', 'hf', 'kvo'];
      const loaded = [];

      for (const id of ids) {
        try {
          const response = await fetch(`${DATA_BASE}nkis/${id}.json`);
          if (response.ok) {
            loaded.push(await response.json());
          }
        } catch (e) {
          console.warn(`Nelze načíst dataset ${id}:`, e);
        }
      }

      setNationalDatasets(loaded);
      setLoadingData(false);

      // Pokud nemáme klíč, zobraz modal
      if (!apiKey) setShowKeyModal(true);
    }
    loadData();
  }, []);

  const allDatasets = useMemo(() => [...nationalDatasets, ...INTL_DATASETS], [nationalDatasets]);
  const selectedDatasets = allDatasets.filter(d => selectedIds.includes(d.id));

  const toggleDataset = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
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

    try {
      const nationalDs = selectedDatasets.filter(d => d.source_type !== 'international');
      const intlDs = selectedDatasets.filter(d => d.source_type === 'international');

      const nationalSummary = nationalDs.map(d => {
        const first = d.data[0], last = d.data[d.data.length - 1];
        return `- ${d.label} (MKN ${d.code}): ${first.value.toLocaleString('cs-CZ')} v ${first.year} → ${last.value.toLocaleString('cs-CZ')} v ${last.year} (Δ ${d.delta > 0 ? '+' : ''}${d.delta} %). Trend: ${d.trend === 'up' ? 'rostoucí' : d.trend === 'down' ? 'klesající' : 'plateau'}, peak ${d.peakYear}. Kontext: ${d.trend_context || ''}`;
      }).join('\n');

      const intlSummary = intlDs.map(d => {
        const comp = d.comparison ? d.comparison.map(c => `${c.country}: ${c.value}${typeof c.value === 'number' && Math.abs(c.value) < 200 ? ' %' : ''}`).join('; ') : '';
        return `- ${d.label} (zdroj: ${d.source} ${d.code}, ${d.coverage}): ${comp}. Pozn. ke srovnatelnosti: ${d.trend_context || ''}`;
      }).join('\n');

      const prompt = `Jsi datový analytik pro českou PR agenturu. NEPÍŠEŠ tiskové zprávy. Tvoje práce je z dat vytáhnout zjištění a doporučit úhly — PR manažer si text napíše sám.

KLIENT: ${client.full}
TÉMA BRIEFU: "${topic}"

NÁRODNÍ DATA Z NKIS / ÚZIS ČR:
${nationalSummary || '(žádná národní data nevybrána)'}

${intlSummary ? `MEZINÁRODNÍ SROVNÁVACÍ DATA:
${intlSummary}

DŮLEŽITÉ: vždy zmiň rok dat a metodiku. Pokud roky nesedí, uveď orientačnost. NEPOUŽÍVEJ OECD ukazatel "30denní mortalita po AIM" — není srovnatelný (Stolpe et al. 2023).
` : ''}

Vrať POUZE platný JSON, žádné markdown, žádný úvod:
{
  "key_findings": [{"number": "+70 %", "label": "...", "explanation": "...", "dataset": "..."}],
  "meta_pattern": "1–2 věty",
  "angles": [{"label": "...", "observation": "1–2 věty pozorování, ne kopie", "key_data": ["..."], "risk": "..."}],
  "cannot_claim": [{"claim": "...", "why": "..."}]
}

3–5 key_findings, 3 angles, 2–3 cannot_claim. Vše česky. Žádné hotové copywriting věty.`;

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
          max_tokens: 1500,
          messages: [{ role: 'user', content: prompt }],
        }),
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Anthropic API: ${response.status} — ${errText.substring(0, 200)}`);
      }

      const data = await response.json();
      const text = data.content?.[0]?.text || '';
      const cleaned = text.replace(/```json|```/g, '').trim();
      const parsed = JSON.parse(cleaned);
      setAnalysis(parsed);
      setStep(3);
    } catch (e) {
      console.error(e);
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  if (loadingData) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Loader2 size={32} className="spin" />
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#FAFAF7' }}>
      {/* TOP BAR */}
      <div style={{
        background: '#1A1A1A', color: '#FAFAF7', padding: '14px 24px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ fontSize: 12, letterSpacing: '0.12em', textTransform: 'uppercase', fontWeight: 600 }}>
          Datový brief · Omnimedia PR · v0.3
        </div>
        <button
          onClick={() => setShowKeyModal(true)}
          style={{
            background: 'transparent', border: '1px solid #555', color: '#FAFAF7',
            padding: '4px 10px', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          <Key size={12} />
          {apiKey ? 'API klíč nastaven' : 'Zadat API klíč'}
        </button>
      </div>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
        {error && (
          <div style={{ background: '#FBE9E6', color: '#5A1812', padding: 12, marginBottom: 16, fontSize: 14 }}>
            Chyba: {error}
          </div>
        )}

        {/* STEP 1: ZADÁNÍ */}
        <section style={{ marginBottom: 48 }}>
          <SectionHeader number="01" title="Zadání briefu" subtitle="Co tvoříme a pro koho" />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 24, marginTop: 16 }}>
            <div>
              <Label>Klient</Label>
              <select
                value={client.id}
                onChange={(e) => setClient(CLIENTS.find(c => c.id === e.target.value))}
                style={inputStyle}
              >
                {CLIENTS.map(c => <option key={c.id} value={c.id}>{c.name} — {c.full}</option>)}
              </select>
            </div>
            <div>
              <Label>Téma briefu</Label>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                style={inputStyle}
              />
            </div>
          </div>
        </section>

        {/* STEP 2: DATA */}
        <section style={{ marginBottom: 48 }}>
          <SectionHeader number="02" title="Datová opora" subtitle="Šedý badge NKIS = národní data, modrý EU/OECD = mezinárodní srovnání" />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16, marginTop: 16 }}>
            {allDatasets.map(d => (
              <DatasetCard
                key={d.id}
                d={d}
                selected={selectedIds.includes(d.id)}
                onToggle={() => toggleDataset(d.id)}
              />
            ))}
          </div>
        </section>

        {/* STEP 3: ANALÝZA */}
        <section style={{ marginBottom: 48 }}>
          <SectionHeader number="03" title="Analýza" subtitle="Strukturovaná zjištění a doporučené úhly" />
          {!analysis ? (
            <div style={{ marginTop: 16 }}>
              <button
                onClick={runAnalysis}
                disabled={analyzing || selectedDatasets.length === 0}
                style={{
                  background: '#1A1A1A', color: '#FAFAF7', padding: '12px 24px',
                  border: 'none', fontSize: 15, fontWeight: 600, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 8,
                  opacity: (analyzing || selectedDatasets.length === 0) ? 0.5 : 1,
                }}
              >
                {analyzing ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                {analyzing ? 'Analyzuji...' : `Analyzovat ${selectedDatasets.length} datasety`}
              </button>
            </div>
          ) : (
            <AnalysisView analysis={analysis} onRerun={() => { setAnalysis(null); runAnalysis(); }} />
          )}
        </section>
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
  border: '1.5px solid #1A1A1A', background: '#FFFFFF', fontFamily: 'inherit',
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
      <span className="num serif" style={{ fontSize: 32, fontWeight: 700, color: '#1A1A1A' }}>{number}</span>
      <div>
        <h2 className="serif" style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>{title}</h2>
        {subtitle && <div style={{ fontSize: 13, color: '#666', marginTop: 2 }}>{subtitle}</div>}
      </div>
    </div>
  );
}

function DatasetCard({ d, selected, onToggle }) {
  const isInternational = d.source_type === 'international';
  const peakVal = d.peakYear ? d.data.find(x => x.year === d.peakYear)?.value : null;
  const first = d.data?.[0];
  const last = d.data?.[d.data.length - 1];
  const trendColor = d.trend === 'up' ? '#1F6F47' : d.trend === 'down' ? '#9A2A1F' : '#7A6F2A';
  const trendWord = d.trend === 'up' ? 'Růst' : d.trend === 'down' ? 'Pokles' : 'Změna';
  const fmtNum = (n) => n.toLocaleString('cs-CZ');
  const title = d.human_name || d.label;
  const showTechLabel = d.label && d.human_name && d.human_name !== d.label;

  return (
    <div onClick={onToggle} style={{
      background: '#FFFFFF', border: selected ? '2px solid #1A1A1A' : '1px solid #DDD8C8',
      padding: 20, cursor: 'pointer', position: 'relative',
      boxShadow: selected ? '4px 4px 0 #1A1A1A' : 'none',
    }}>
      {/* 1. Badge + checkbox */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
          padding: '2px 6px',
          background: isInternational ? '#1F4E8C' : '#444', color: '#FFFFFF',
        }}>{isInternational ? 'EU/OECD' : 'Česká data'}</span>
        <div style={{
          width: 22, height: 22, border: '1.5px solid #1A1A1A',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: selected ? '#1A1A1A' : 'transparent', flexShrink: 0,
        }}>
          {selected && <Check size={14} color="#FAFAF7" />}
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

      {/* 5. Pro národní: metric line + delta line + graf */}
      {!isInternational && first && last && (
        <>
          {d.metric_label && (
            <div style={{ fontSize: 13, color: '#1A1A1A', marginBottom: 4 }}>
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
          background: isInternational ? '#EFF4F8' : '#F2F0EA',
          padding: '10px 12px', marginTop: 12,
        }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#666', marginBottom: 6 }}>
            Užitečné pro:
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {d.relevant_for.map((t, i) => (
              <span key={i} style={{
                fontSize: 11, padding: '2px 8px', background: '#FFFFFF',
                border: '1px solid #DDD8C8', color: '#333',
              }}>{t}</span>
            ))}
          </div>
        </div>
      )}

      {/* 8. Data / kód / aktualizováno */}
      <div style={{ fontSize: 10, color: '#888', marginTop: 12, lineHeight: 1.4 }}>
        {isInternational
          ? <>Data: {d.source}{d.code && ` · ${d.code}`}{d.updated && ` · aktualizováno ${d.updated}`}</>
          : <>Data: ÚZIS ČR{d.code && ` · diagnostický kód ${d.code}`}{d.updated && ` · aktualizováno ${d.updated}`}</>
        }
      </div>
    </div>
  );
}

function ComparisonBars({ rows }) {
  const maxVal = Math.max(...rows.map(r => Math.abs(r.value)));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {rows.map((r, i) => {
        const width = (Math.abs(r.value) / maxVal) * 100;
        const color = r.isUs ? '#C9302C' : (r.hi ? '#9A2A1F88' : '#1F4E8C88');
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 50px', gap: 8, alignItems: 'center', fontSize: 11 }}>
            <span style={{ fontWeight: r.isUs ? 700 : 400, color: r.isUs ? '#1A1A1A' : '#444' }}>{r.country}</span>
            <div style={{ height: 12, background: '#F0EEE6', position: 'relative' }}>
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

function AnalysisView({ analysis, onRerun }) {
  return (
    <div style={{ marginTop: 16 }}>
      {analysis.meta_pattern && (
        <div style={{ background: '#1A1A1A', color: '#FAFAF7', padding: 20, marginBottom: 24 }}>
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
        {analysis.key_findings?.map((f, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '100px 1fr', gap: 12, padding: 12, background: '#FFFFFF', border: '1px solid #DDD8C8' }}>
            <div className="num serif" style={{ fontSize: 24, fontWeight: 700, color: '#C9302C' }}>{f.number}</div>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>{f.label}</div>
              <div style={{ fontSize: 13, color: '#555' }}>{f.explanation}</div>
            </div>
          </div>
        ))}
      </div>

      <h3 className="serif" style={{ fontSize: 20, marginBottom: 12 }}>Doporučené úhly</h3>
      <div style={{ display: 'grid', gap: 12, marginBottom: 24 }}>
        {analysis.angles?.map((a, i) => (
          <div key={i} style={{ padding: 16, background: '#FFFFFF', border: '1px solid #DDD8C8' }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#666', marginBottom: 4 }}>
              Úhel {String.fromCharCode(65 + i)}
            </div>
            <div className="serif" style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{a.label}</div>
            <div style={{ fontSize: 14, color: '#333', lineHeight: 1.5, marginBottom: 8 }}>{a.observation}</div>
            {a.risk && (
              <div style={{ fontSize: 12, color: '#5A1812', background: '#FBE9E6', padding: 8, marginTop: 8 }}>
                <strong>Riziko v tezi:</strong> {a.risk}
              </div>
            )}
          </div>
        ))}
      </div>

      {analysis.cannot_claim?.length > 0 && (
        <>
          <h3 className="serif" style={{ fontSize: 20, marginBottom: 12, color: '#C9302C' }}>Co data NEPODPORUJÍ</h3>
          <div style={{ display: 'grid', gap: 8, marginBottom: 24 }}>
            {analysis.cannot_claim.map((c, i) => (
              <div key={i} style={{ padding: 12, background: '#FBE9E6' }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>„{c.claim}"</div>
                <div style={{ fontSize: 13, color: '#5A1812' }}>{c.why}</div>
              </div>
            ))}
          </div>
        </>
      )}

      <button
        onClick={onRerun}
        style={{
          background: 'transparent', color: '#1A1A1A', padding: '8px 16px',
          border: '1.5px solid #1A1A1A', fontSize: 14, cursor: 'pointer',
        }}
      >
        Znovu analyzovat
      </button>
    </div>
  );
}
