import React, { useState, useEffect, useMemo } from 'react';
import { LineChart, Line, ResponsiveContainer, ReferenceDot } from 'recharts';
import { ChevronRight, Check, Loader2, Sparkles, Key, X, Download } from 'lucide-react';
import {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, ShadingType, BorderStyle, WidthType,
} from 'docx';
import { saveAs } from 'file-saver';

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
  // viz sync_nkis.py / sync_nor.py. Frontend nepřidává nic, jen prochází fetch.
  // folder = která složka v data/: 'nkis' (kardio z NKIS), 'nor' (onko z NOR).
  useEffect(() => {
    async function loadData() {
      const sources = [
        { id: 'aim', folder: 'nkis' },
        { id: 'cmp', folder: 'nkis' },
        { id: 'hyp', folder: 'nkis' },
        { id: 'hf', folder: 'nkis' },
        { id: 'kvo', folder: 'nkis' },
        { id: 'prsa_incidence', folder: 'nor' },
        { id: 'plice_incidence', folder: 'nor' },
        { id: 'prostata_incidence', folder: 'nor' },
        { id: 'kolorektum_incidence', folder: 'nor' },
        { id: 'melanom_incidence', folder: 'nor' },
        { id: 'zaludek_incidence', folder: 'nor' },
        { id: 'slinivka_incidence', folder: 'nor' },
        { id: 'mozek_incidence', folder: 'nor' },
        { id: 'leukemie_incidence', folder: 'nor' },
        { id: 'lymfomy_incidence', folder: 'nor' },
        { id: 'ledvina_incidence', folder: 'nor' },
        { id: 'mocovy_mechyr_incidence', folder: 'nor' },
        { id: 'stitna_zlaza_incidence', folder: 'nor' },
        { id: 'jicen_incidence', folder: 'nor' },
        { id: 'varlata_incidence', folder: 'nor' },
        { id: 'vajecnik_incidence', folder: 'nor' },
        { id: 'cipek_incidence', folder: 'nor' },
        { id: 'deloha_incidence', folder: 'nor' },
        { id: 'kosti_incidence', folder: 'nor' },
        { id: 'ustni_dutina_incidence', folder: 'nor' },
        { id: 'stitna_zlaza_deti_incidence', folder: 'nor' },
        { id: 'vzacne_nadory_incidence', folder: 'nor' },
        { id: 'stitna_zlaza_dospeli_incidence', folder: 'nor' },
        { id: 'myelom_incidence', folder: 'nor' },
        { id: 'hrtan_incidence', folder: 'nor' },
        { id: 'kuze_nemelanomove_incidence', folder: 'nor' },
        { id: 'hodgkin_lymfom_incidence', folder: 'nor' },
        { id: 'lymfomy_b_bunecne_incidence', folder: 'nor' },
        { id: 'lymfomy_t_bunecne_incidence', folder: 'nor' },
        { id: 'kolorektum_mladi_incidence', folder: 'nor' },
        { id: 'kolorektum_starsi_incidence', folder: 'nor' },
        { id: 'prsa_mladi_incidence', folder: 'nor' },
        { id: 'prsa_starsi_incidence', folder: 'nor' },
        { id: 'plice_mladi_incidence', folder: 'nor' },
        { id: 'plice_starsi_incidence', folder: 'nor' },
        { id: 'melanom_mladi_incidence', folder: 'nor' },
        { id: 'melanom_starsi_incidence', folder: 'nor' },
        { id: 'varlata_mladi_incidence', folder: 'nor' },
        { id: 'varlata_starsi_incidence', folder: 'nor' },
        { id: 'leukemie_deti_incidence', folder: 'nor' },
        { id: 'leukemie_dospeli_incidence', folder: 'nor' },
        { id: 'kolorektum_velmi_mladi_incidence', folder: 'nor' },
        { id: 'kolorektum_stredni_incidence', folder: 'nor' },
        { id: 'prsa_mortalita', folder: 'nor' },
        { id: 'plice_mortalita', folder: 'nor' },
        { id: 'prostata_mortalita', folder: 'nor' },
        { id: 'kolorektum_mortalita', folder: 'nor' },
        { id: 'melanom_mortalita', folder: 'nor' },
        { id: 'zaludek_mortalita', folder: 'nor' },
        { id: 'slinivka_mortalita', folder: 'nor' },
        { id: 'jicen_mortalita', folder: 'nor' },
        { id: 'cipek_mortalita', folder: 'nor' },
        { id: 'leukemie_mortalita', folder: 'nor' },
        { id: 'lymfomy_mortalita', folder: 'nor' },
        { id: 'mozek_mortalita', folder: 'nor' },
        { id: 'ledvina_mortalita', folder: 'nor' },
        { id: 'mocovy_mechyr_mortalita', folder: 'nor' },
        { id: 'stitna_zlaza_mortalita', folder: 'nor' },
        { id: 'hrtan_mortalita', folder: 'nor' },
        { id: 'varlata_mortalita', folder: 'nor' },
        { id: 'vajecnik_mortalita', folder: 'nor' },
        { id: 'deloha_mortalita', folder: 'nor' },
        { id: 'kosti_mortalita', folder: 'nor' },
        { id: 'ustni_dutina_mortalita', folder: 'nor' },
        { id: 'myelom_mortalita', folder: 'nor' },
        { id: 'kuze_nemelanomove_mortalita', folder: 'nor' },
        { id: 'hodgkin_lymfom_mortalita', folder: 'nor' },
        { id: 'lymfomy_b_bunecne_mortalita', folder: 'nor' },
        { id: 'lymfomy_t_bunecne_mortalita', folder: 'nor' },
        { id: 'vzacne_nadory_mortalita', folder: 'nor' },
        { id: 'prsa_mortalita_kraje_2022', folder: 'nor' },
        { id: 'plice_mortalita_kraje_2022', folder: 'nor' },
        { id: 'prostata_mortalita_kraje_2022', folder: 'nor' },
        { id: 'kolorektum_mortalita_kraje_2022', folder: 'nor' },
        { id: 'melanom_mortalita_kraje_2022', folder: 'nor' },
        { id: 'plice_muzi_mortalita', folder: 'nor' },
        { id: 'plice_zeny_mortalita', folder: 'nor' },
        { id: 'kolorektum_muzi_mortalita', folder: 'nor' },
        { id: 'kolorektum_zeny_mortalita', folder: 'nor' },
        { id: 'prsa_mladi_mortalita', folder: 'nor' },
        { id: 'prsa_starsi_mortalita', folder: 'nor' },
        { id: 'kolorektum_mladi_mortalita', folder: 'nor' },
        { id: 'kolorektum_starsi_mortalita', folder: 'nor' },
        { id: 'prsa_mladi_preziti_5y', folder: 'nor' },
        { id: 'prsa_starsi_preziti_5y', folder: 'nor' },
        { id: 'kolorektum_mladi_preziti_5y', folder: 'nor' },
        { id: 'kolorektum_starsi_preziti_5y', folder: 'nor' },
        { id: 'prsa_preziti_5y', folder: 'nor' },
        { id: 'plice_preziti_5y', folder: 'nor' },
        { id: 'prostata_preziti_5y', folder: 'nor' },
        { id: 'kolorektum_preziti_5y', folder: 'nor' },
        { id: 'melanom_preziti_5y', folder: 'nor' },
        { id: 'zaludek_preziti_5y', folder: 'nor' },
        { id: 'slinivka_preziti_5y', folder: 'nor' },
        { id: 'cipek_preziti_5y', folder: 'nor' },
        { id: 'hodgkin_preziti_5y', folder: 'nor' },
        { id: 'lymfomy_b_bunecne_preziti_5y', folder: 'nor' },
        { id: 'leukemie_preziti_5y', folder: 'nor' },
        { id: 'mozek_preziti_5y', folder: 'nor' },
        { id: 'ustni_dutina_preziti_5y', folder: 'nor' },
        { id: 'jicen_preziti_5y', folder: 'nor' },
        { id: 'hrtan_preziti_5y', folder: 'nor' },
        { id: 'kuze_nemelanomove_preziti_5y', folder: 'nor' },
        { id: 'deloha_preziti_5y', folder: 'nor' },
        { id: 'vajecnik_preziti_5y', folder: 'nor' },
        { id: 'varlata_preziti_5y', folder: 'nor' },
        { id: 'ledvina_preziti_5y', folder: 'nor' },
        { id: 'mocovy_mechyr_preziti_5y', folder: 'nor' },
        { id: 'stitna_zlaza_preziti_5y', folder: 'nor' },
        { id: 'myelom_preziti_5y', folder: 'nor' },
        { id: 'prsa_stadium_1_share', folder: 'nor' },
        { id: 'prsa_stadium_4_share', folder: 'nor' },
        { id: 'kolorektum_stadium_1_share', folder: 'nor' },
        { id: 'kolorektum_stadium_4_share', folder: 'nor' },
        { id: 'plice_stadium_1_share', folder: 'nor' },
        { id: 'plice_stadium_4_share', folder: 'nor' },
        { id: 'prostata_stadium_1_share', folder: 'nor' },
        { id: 'prostata_stadium_4_share', folder: 'nor' },
        { id: 'melanom_stadium_1_share', folder: 'nor' },
        { id: 'melanom_stadium_4_share', folder: 'nor' },
        { id: 'zaludek_stadium_1_share', folder: 'nor' },
        { id: 'zaludek_stadium_4_share', folder: 'nor' },
        { id: 'slinivka_stadium_1_share', folder: 'nor' },
        { id: 'slinivka_stadium_4_share', folder: 'nor' },
        { id: 'jicen_stadium_1_share', folder: 'nor' },
        { id: 'jicen_stadium_4_share', folder: 'nor' },
        { id: 'ledvina_stadium_1_share', folder: 'nor' },
        { id: 'ledvina_stadium_4_share', folder: 'nor' },
        { id: 'mocovy_mechyr_stadium_1_share', folder: 'nor' },
        { id: 'mocovy_mechyr_stadium_4_share', folder: 'nor' },
        { id: 'stitna_zlaza_stadium_1_share', folder: 'nor' },
        { id: 'stitna_zlaza_stadium_4_share', folder: 'nor' },
        { id: 'vajecnik_stadium_1_share', folder: 'nor' },
        { id: 'vajecnik_stadium_4_share', folder: 'nor' },
        { id: 'plice_muzi_incidence', folder: 'nor' },
        { id: 'plice_zeny_incidence', folder: 'nor' },
        { id: 'kolorektum_muzi_incidence', folder: 'nor' },
        { id: 'kolorektum_zeny_incidence', folder: 'nor' },
        { id: 'zaludek_muzi_incidence', folder: 'nor' },
        { id: 'zaludek_zeny_incidence', folder: 'nor' },
        { id: 'hrtan_muzi_incidence', folder: 'nor' },
        { id: 'hrtan_zeny_incidence', folder: 'nor' },
        { id: 'melanom_muzi_incidence', folder: 'nor' },
        { id: 'melanom_zeny_incidence', folder: 'nor' },
        { id: 'mocovy_mechyr_muzi_incidence', folder: 'nor' },
        { id: 'mocovy_mechyr_zeny_incidence', folder: 'nor' },
        { id: 'slinivka_mladi_incidence', folder: 'nor' },
        { id: 'slinivka_starsi_incidence', folder: 'nor' },
        { id: 'mozek_mladi_incidence', folder: 'nor' },
        { id: 'mozek_starsi_incidence', folder: 'nor' },
        { id: 'jicen_mladi_incidence', folder: 'nor' },
        { id: 'jicen_starsi_incidence', folder: 'nor' },
        { id: 'stitna_zlaza_male_deti_incidence', folder: 'nor' },
        { id: 'tuberkuloza_incidence', folder: 'nzip_curated' },
        { id: 'sebevrazdy_hospitalizace', folder: 'nzip_curated' },
        { id: 'autismus_deti_incidence', folder: 'nzip_curated' },
        { id: 'pohlavni_nemoci_incidence', folder: 'nzip_curated' },
        { id: 'astma_dispenzarizovani', folder: 'nzip_curated' },
        { id: 'preventivni_prohlidky_pokryti', folder: 'nzip_curated' },
        { id: 'kolorektum_screening_pokryti', folder: 'nzip_curated' },
        { id: 'prostata_psa_pokryti', folder: 'nzip_curated' },
        { id: 'autismus_vcasny_zachyt_pokryti', folder: 'nzip_curated' },
        { id: 'kycle_screening_pokryti', folder: 'nzip_curated' },
        { id: 'ocekavatelna_umrti', folder: 'nzip_curated' },
        { id: 'alergicka_ryma_dispenzarizovani', folder: 'nzip_curated' },
        { id: 'vrozene_vady', folder: 'nzip_curated' },
        { id: 'lazenska_pece_pacienti', folder: 'nzip_curated' },
        { id: 'paliativni_pece_pacienti', folder: 'nzip_curated' },
        { id: 'mamografie_screening_pokryti', folder: 'nzip_curated' },
        { id: 'cervix_screening_pokryti', folder: 'nzip_curated' },
        { id: 'umrti_mkn10_celkem', folder: 'nzip_curated' },
        { id: 'atopicka_dermatitida', folder: 'nzip_curated' },
        { id: 'cdz_pacienti', folder: 'nzip_curated' },
        { id: 'umrti_doma_ocekavatelne', folder: 'nzip_curated' },
        { id: 'dialyza_nefrolog_pokryti', folder: 'nzip_curated' },
        { id: 'toks_pozitivni_podil', folder: 'nzip_curated' },
      ];
      const loaded = [];

      for (const { id, folder } of sources) {
        try {
          const response = await fetch(`${DATA_BASE}${folder}/${id}.json`);
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

    let text = '';
    try {
      const nationalDs = selectedDatasets.filter(d => d.source_type !== 'international' && d.source_type !== 'regional_snapshot');
      const regionalDs = selectedDatasets.filter(d => d.source_type === 'regional_snapshot');
      const intlDs = selectedDatasets.filter(d => d.source_type === 'international');

      const nationalSummary = nationalDs.map(d => {
        const first = d.data[0], last = d.data[d.data.length - 1];
        return `- [id: ${d.id}] ${d.label} (MKN ${d.code}): ${first.value.toLocaleString('cs-CZ')} v ${first.year} → ${last.value.toLocaleString('cs-CZ')} v ${last.year} (Δ ${d.delta > 0 ? '+' : ''}${d.delta} %). Trend: ${d.trend === 'up' ? 'rostoucí' : d.trend === 'down' ? 'klesající' : 'plateau'}, peak ${d.peakYear}. Kontext: ${d.trend_context || ''}`;
      }).join('\n');

      const regionalSummary = regionalDs.map(d => {
        const sorted = [...d.data].sort((a, b) => b.value - a.value);
        const breakdown = sorted.map(r => `${r.kraj_nazev}: ${r.value.toLocaleString('cs-CZ')}`).join('; ');
        return `- [id: ${d.id}] ${d.label} (MKN ${d.code}, rok ${d.snapshot_year}): ${breakdown}. Peak kraj: ${d.peakRegion}. Kontext: ${d.trend_context || ''}`;
      }).join('\n');

      const intlSummary = intlDs.map(d => {
        const comp = d.comparison ? d.comparison.map(c => `${c.country}: ${c.value}${typeof c.value === 'number' && Math.abs(c.value) < 200 ? ' %' : ''}`).join('; ') : '';
        return `- [id: ${d.id}] ${d.label} (zdroj: ${d.source} ${d.code}, ${d.coverage}): ${comp}. Pozn. ke srovnatelnosti: ${d.trend_context || ''}`;
      }).join('\n');

      const prompt = `Jsi datový analytik pro českou PR agenturu. NEPÍŠEŠ tiskové zprávy. Tvoje práce je z dat vytáhnout zjištění a doporučit úhly — PR manažer si text napíše sám.

KLIENT: ${client.full}
TÉMA BRIEFU: "${topic}"

NÁRODNÍ DATA Z NKIS / ÚZIS ČR:
${nationalSummary || '(žádná národní data nevybrána)'}

${regionalSummary ? `KRAJOVÝ POHLED (snapshot ČR):
${regionalSummary}

` : ''}${intlSummary ? `MEZINÁRODNÍ SROVNÁVACÍ DATA:
${intlSummary}

DŮLEŽITÉ: vždy zmiň rok dat a metodiku. Pokud roky nesedí, uveď orientačnost. NEPOUŽÍVEJ OECD ukazatel "30denní mortalita po AIM" — není srovnatelný (Stolpe et al. 2023).
` : ''}

PRAVIDLO PRO ZKRATKY V ANALÝZE:
- Při prvním použití termínu, který má v češtině/angličtině zkratku (např. AIM, KVO, FH, ICHS, CMP, NRHZS), napiš plný název a zkratku v závorce: "akutní infarkt myokardu (AIM)". V dalších použitích už používej jen zkratku.
- U mezinárodních termínů totéž: "Eurostat hlth_cd_aro" první výskyt, pak jen "Eurostat".
- Cíl: text musí být srozumitelný pro PR pracovníka, ne kardiologa.

Vrať POUZE platný JSON, žádné markdown, žádný úvod:
{
  "key_findings": [{"number": "+70 %", "label": "...", "explanation": "...", "dataset": "id datasetu (např. 'aim', 'cmp', 'eu_cvd_share') — ne lidský název"}],
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
    const border = { style: BorderStyle.SINGLE, size: 4, color: 'C0C0C0' };
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

    const lightBlue = { type: ShadingType.SOLID, color: 'auto', fill: 'EFF4F8' };
    const dark = { type: ShadingType.SOLID, color: 'auto', fill: '1A1A1A' };

    const children = [];

    // 1. Hlavička
    children.push(p(
      t(`DATOVÝ PODKLAD • Klient: ${client.full} • Téma: ${topic} • ${formatDateCS(new Date())}`, { size: 16, color: '666666' }),
      { spacing: { after: 200 } }
    ));

    // 2. Titul
    children.push(p(t(topic, { bold: true, size: 36 }), {
      heading: HeadingLevel.HEADING_1,
      spacing: { after: 300 },
    }));

    // 3. V čem data spočívají — světle modré pozadí
    children.push(p(t('V čem data spočívají', { bold: true, size: 22 }), { spacing: { before: 200, after: 100 } }));
    const sources = [...new Set(selectedDatasets.map(d => d.source).filter(Boolean))];
    const allYears = selectedDatasets.flatMap(d => (d.data || []).map(x => x.year)).filter(Number.isFinite);
    const yearRange = allYears.length ? `${Math.min(...allYears)}–${Math.max(...allYears)}` : '—';
    const datasetSummary = selectedDatasets.map(d => d.human_name || d.label).join(', ');
    children.push(p([t('Zdroj: ', { bold: true }), t(sources.join(', ') || '—')], { shading: lightBlue, spacing: { before: 80, after: 80 } }));
    children.push(p([t('Co data obsahují: ', { bold: true }), t(datasetSummary)], { shading: lightBlue, spacing: { after: 80 } }));
    children.push(p([t('Časové pokrytí: ', { bold: true }), t(yearRange)], { shading: lightBlue, spacing: { after: 200 } }));

    // 4. Co data dohromady říkají — tmavé pozadí, italika, bílý text
    if (analysis.meta_pattern) {
      children.push(p(t('Co data dohromady říkají', { bold: true, size: 22 }), { spacing: { before: 300, after: 100 } }));
      children.push(p(
        t(analysis.meta_pattern, { italic: true, color: 'FFFFFF', size: 22 }),
        { shading: dark, spacing: { before: 100, after: 200 } }
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
        return new TableRow({
          children: [
            cell(p(t(f.number || '', { bold: true, color: 'C9302C', size: 32 }), { alignment: AlignmentType.CENTER })),
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
          cell(p(t(a.observation || ''))),
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
      children.push(p(t('Co data NEPODPORUJÍ', { bold: true, color: 'C9302C', size: 22 }), { spacing: { before: 300, after: 100 } }));
      analysis.cannot_claim.forEach(c => {
        children.push(p(
          [t('„'), t(c.claim || '', { italic: true }), t(`" — ${c.why || ''}`)],
          { bullet: { level: 0 }, spacing: { after: 60 } }
        ));
      });
    }

    // 9. Zdroje + citační formule
    children.push(p(t('Zdroje', { bold: true, size: 22 }), { spacing: { before: 300, after: 100 } }));
    selectedDatasets.forEach(d => {
      const parts = [t(`${d.label} (${d.code}) — ${d.source}`)];
      if (d.source_url) {
        parts.push(t(' · Zdroj dat: '));
        parts.push(t(d.source_url, { color: '1F4E8C' }));
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
    const filename = `Brief_${client.id}_${slug(topic)}_${formatDateISO(new Date())}.docx`;
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
            <>
              <AnalysisView analysis={analysis} datasets={selectedDatasets} onRerun={() => { setAnalysis(null); runAnalysis(); }} />
              <div style={{ marginTop: 16 }}>
                <button
                  onClick={exportToDocx}
                  style={{
                    background: '#1F4E8C', color: '#FAFAF7', padding: '10px 20px',
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
  const isRegional = d.source_type === 'regional_snapshot';
  const peakVal = !isRegional && d.peakYear ? d.data.find(x => x.year === d.peakYear)?.value : null;
  const first = !isRegional ? d.data?.[0] : null;
  const last = !isRegional ? d.data?.[d.data.length - 1] : null;
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

      {/* 5a. Pro regional snapshot: bar chart per kraj */}
      {isRegional && d.data?.length > 0 && (
        <div style={{ margin: '4px 0 8px' }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#888', marginBottom: 8 }}>
            {d.metric_label || `Kraje (${d.snapshot_year})`}
          </div>
          <RegionalBars data={d.data} peakRegion={d.peakRegion} />
        </div>
      )}

      {/* 5b. Pro národní časové řady: metric line + delta line + graf */}
      {!isInternational && !isRegional && first && last && (
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
                style={{ color: '#1F4E8C', textDecoration: 'underline' }}
              >{d.code}</a>
            ) : d.code}
          </>
        )}
        {d.updated && ` · aktualizováno ${d.updated}`}
      </div>
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
        const color = isPeak ? '#C9302C' : '#1F4E8C88';
        return (
          <div key={r.kraj_kod} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 60px', gap: 8, alignItems: 'center', fontSize: 11 }}>
            <span style={{ fontWeight: isPeak ? 700 : 400, color: isPeak ? '#1A1A1A' : '#444' }}>{r.kraj_nazev}</span>
            <div style={{ height: 12, background: '#F0EEE6', position: 'relative' }}>
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
        {analysis.key_findings?.map((f, i) => {
          const ds = findDatasetById(f.dataset, datasets);
          const dsName = ds ? (ds.human_name || ds.label) : null;
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '100px 1fr', gap: 12, padding: 12, background: '#FFFFFF', border: '1px solid #DDD8C8' }}>
              <div className="num serif" style={{ fontSize: 24, fontWeight: 700, color: '#C9302C' }}>{f.number}</div>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 13, color: '#555' }}>{f.explanation}</div>
                {dsName && (
                  <div style={{ fontSize: 11, color: '#888', marginTop: 6 }}>
                    Zdroj: {ds.source_url ? (
                      <a href={ds.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#1F4E8C' }}>{dsName}</a>
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
