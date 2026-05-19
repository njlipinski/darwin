import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { Search, Grid3x3, Table2, SlidersHorizontal, Telescope, ChevronUp, ChevronDown, X, Sparkles, AlertCircle, Activity } from 'lucide-react';

// ============================================================
// API CLIENT — talks to the DARWIN FastAPI backend
// ============================================================
// Backend repo: darwin-api/ (FastAPI + SQLite)
// Run locally:   uvicorn darwin.api.app:app --reload
// Docs:          http://localhost:8000/docs
//
// CORS is wide-open in dev (app.py adds `allow_origins=["*"]`),
// so the frontend can call this directly. Tighten before deploy.
// ============================================================

const API_BASE = 'http://localhost:8000';

async function apiGet(path, params = {}) {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');
  const url = `${API_BASE}${path}${qs ? '?' + qs : ''}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}: ${text || path}`);
  }
  return res.json();
}

// Endpoint wrappers — names match the FastAPI routes 1:1
const api = {
  // GET /planets?habitable=&rocky=&has_spectrum=&min_score=&limit=&offset=
  listPlanets: (params) => apiGet('/planets', params),
  // GET /planets/{name}
  getPlanet: (name) => apiGet(`/planets/${encodeURIComponent(name)}`),
  // GET /planets/{name}/spectra
  listSpectra: (name) => apiGet(`/planets/${encodeURIComponent(name)}/spectra`),
  // GET /spectra/{id}
  getSpectrum: (id) => apiGet(`/spectra/${id}`),
  // GET /classifications/{name}  (may 404 — that's expected for most planets)
  getClassification: (name) => apiGet(`/classifications/${encodeURIComponent(name)}`),
};

// ============================================================
// FILTER CONFIG
// ============================================================
// Two tiers of filters:
//   - SERVER filters: sent as query params, trigger a refetch.
//     Match the FastAPI endpoint's accepted params exactly.
//   - CLIENT filters: range sliders applied to the in-memory result set.
//     Operate on backend column names (pl_eqt, pl_rade, sy_dist).
//
// The min_score values map to the backend's coarse 3-bucket score
// (see darwin/ingest/planets.py::score_habitability):
//   1.0 = in_hz AND rocky, 0.5 = one of them, 0.0 = neither.

const SCORE_STOPS = [
  { value: 0,    label: 'all',     hint: 'any planet, including unscored' },
  { value: 0.5,  label: 'partial', hint: 'in HZ or rocky candidate' },
  { value: 1.0,  label: 'strong',  hint: 'in HZ AND rocky candidate' },
];

const CLIENT_FILTERS = [
  { key: 'pl_eqt',   label: 'Equilibrium Temp', unit: 'K',  min: 150, max: 400, defaultRange: [150, 400], step: 1   },
  { key: 'pl_rade',  label: 'Radius',           unit: 'R⊕', min: 0,   max: 5,   defaultRange: [0, 5],     step: 0.05 },
  { key: 'sy_dist',  label: 'Distance',         unit: 'pc', min: 0,   max: 500, defaultRange: [0, 500],   step: 1    },
];

// ============================================================
// DUAL-HANDLE RANGE SLIDER
// ============================================================
function RangeSlider({ filter, value, onChange }) {
  const { min, max, step, label, unit } = filter;
  const [lo, hi] = value;
  const pct = (v) => ((v - min) / (max - min)) * 100;

  return (
    <div className="filter-row">
      <div className="filter-header">
        <span className="filter-label">{label}</span>
        <span className="filter-value">
          {step < 1 ? lo.toFixed(2) : lo} – {step < 1 ? hi.toFixed(2) : hi} <span className="filter-unit">{unit}</span>
        </span>
      </div>
      <div className="slider-track-wrap">
        <div className="slider-track" />
        <div className="slider-range" style={{ left: `${pct(lo)}%`, width: `${pct(hi) - pct(lo)}%` }} />
        <input type="range" min={min} max={max} step={step} value={lo}
          onChange={(e) => onChange([Math.min(parseFloat(e.target.value), hi - step), hi])}
          className="slider-input" />
        <input type="range" min={min} max={max} step={step} value={hi}
          onChange={(e) => onChange([lo, Math.max(parseFloat(e.target.value), lo + step)])}
          className="slider-input" />
      </div>
    </div>
  );
}

// ============================================================
// HABITABILITY SCORE STEPPER
// ============================================================
function ScoreStepper({ value, onChange }) {
  return (
    <div className="filter-row">
      <div className="filter-header">
        <span className="filter-label">Min Habitability</span>
        <span className="filter-value">
          {SCORE_STOPS.find(s => s.value === value)?.label}
        </span>
      </div>
      <div className="score-stepper">
        {SCORE_STOPS.map((s) => (
          <button
            key={s.value}
            className={`score-stop ${value === s.value ? 'active' : ''}`}
            onClick={() => onChange(s.value)}
            title={s.hint}
          >
            <div className="score-stop-dots">
              {[1, 2, 3].map(i => (
                <span key={i} className={`stop-dot ${
                  (s.value === 0 && i <= 1) ||
                  (s.value === 0.5 && i <= 2) ||
                  (s.value === 1.0 && i <= 3) ? 'filled' : ''
                }`} />
              ))}
            </div>
            <span className="score-stop-label">{s.label}</span>
          </button>
        ))}
      </div>
      <div className="filter-hint">
        {SCORE_STOPS.find(s => s.value === value)?.hint}
      </div>
    </div>
  );
}

// ============================================================
// SPECTRUM PLOT
// ============================================================
// Renders wavelength vs flux from /spectra/{id}.
// Pure SVG — no chart library needed for this shape.
function SpectrumPlot({ spectrum }) {
  if (!spectrum || !spectrum.wavelength_um?.length) return null;
  const W = 440, H = 160, PAD = { l: 38, r: 12, t: 10, b: 28 };
  const wl = spectrum.wavelength_um;
  const fl = spectrum.flux;
  const err = spectrum.flux_err;

  const xMin = Math.min(...wl), xMax = Math.max(...wl);
  const yMin = Math.min(...fl), yMax = Math.max(...fl);
  const yPad = (yMax - yMin) * 0.1 || 1;
  const yLo = yMin - yPad, yHi = yMax + yPad;

  const sx = (v) => PAD.l + ((v - xMin) / (xMax - xMin)) * (W - PAD.l - PAD.r);
  const sy = (v) => H - PAD.b - ((v - yLo) / (yHi - yLo)) * (H - PAD.t - PAD.b);

  const path = wl.map((x, i) => `${i === 0 ? 'M' : 'L'}${sx(x).toFixed(1)},${sy(fl[i]).toFixed(1)}`).join('');

  return (
    <div className="spectrum-plot">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%">
        {/* axes */}
        <line x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b} stroke="rgba(255,255,255,0.2)" />
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} stroke="rgba(255,255,255,0.2)" />
        {/* error bars */}
        {err && wl.map((x, i) => (
          <line key={i} x1={sx(x)} x2={sx(x)}
            y1={sy(fl[i] - err[i])} y2={sy(fl[i] + err[i])}
            stroke="rgba(255, 181, 71, 0.3)" strokeWidth="1" />
        ))}
        {/* main line */}
        <path d={path} fill="none" stroke="#ffb547" strokeWidth="1.5" />
        {/* points */}
        {wl.map((x, i) => <circle key={i} cx={sx(x)} cy={sy(fl[i])} r="2" fill="#ffb547" />)}
        {/* labels */}
        <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="9" fill="#8a93a8" fontFamily="JetBrains Mono">
          wavelength (μm)
        </text>
        <text x={10} y={H / 2} textAnchor="middle" fontSize="9" fill="#8a93a8" fontFamily="JetBrains Mono"
          transform={`rotate(-90, 10, ${H / 2})`}>
          flux
        </text>
        <text x={PAD.l} y={H - PAD.b + 13} fontSize="8" fill="#8a93a8" fontFamily="JetBrains Mono">{xMin.toFixed(2)}</text>
        <text x={W - PAD.r} y={H - PAD.b + 13} textAnchor="end" fontSize="8" fill="#8a93a8" fontFamily="JetBrains Mono">{xMax.toFixed(2)}</text>
      </svg>
      <div className="spectrum-caption">
        {spectrum.instrument} · {spectrum.spectrum_type} · {wl.length} points · {spectrum.source}
      </div>
    </div>
  );
}

// ============================================================
// PLANET CARD
// ============================================================
function PlanetCard({ planet, onClick }) {
  const seed = planet.pl_name.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  const hue = (seed * 37) % 360;
  const tilt = ((seed * 13) % 20) - 10;
  const score = planet.habitability_score;

  return (
    <div className="planet-card" onClick={() => onClick(planet)}>
      <div className="planet-card-visual">
        <div className="planet-orb" style={{
          background: `radial-gradient(circle at 30% 30%,
            hsl(${hue}, 70%, 65%),
            hsl(${(hue + 40) % 360}, 60%, 35%) 60%,
            hsl(${(hue + 80) % 360}, 50%, 15%) 100%)`,
          transform: `rotate(${tilt}deg)`,
        }} />
        {planet.has_spectrum && (
          <div className="jwst-badge"><Sparkles size={10}/> {planet.n_spectra} spec</div>
        )}
      </div>
      <div className="planet-card-body">
        <div className="planet-name">{planet.pl_name}</div>
        <div className="planet-host">{planet.hostname ?? '—'}</div>
        <div className="planet-stats">
          <div className="stat"><span className="stat-key">score</span>
            <span className="stat-val">{score != null ? score.toFixed(1) : '—'}</span></div>
          <div className="stat"><span className="stat-key">T<sub>eq</sub></span>
            <span className="stat-val">{planet.pl_eqt != null ? Math.round(planet.pl_eqt) : '—'}<span className="stat-unit">K</span></span></div>
          <div className="stat"><span className="stat-key">R</span>
            <span className="stat-val">{planet.pl_rade != null ? planet.pl_rade.toFixed(2) : '—'}<span className="stat-unit">R⊕</span></span></div>
          <div className="stat"><span className="stat-key">d</span>
            <span className="stat-val">{planet.sy_dist != null ? planet.sy_dist.toFixed(1) : '—'}<span className="stat-unit">pc</span></span></div>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// DETAIL DRAWER — fetches full detail + spectra + classification
// ============================================================
function DetailDrawer({ planetName, onClose }) {
  const [detail, setDetail]               = useState(null);
  const [spectraList, setSpectraList]     = useState([]);
  const [activeSpectrum, setActiveSpectrum] = useState(null);
  const [classification, setClassification] = useState(null);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState(null);

  useEffect(() => {
    if (!planetName) return;
    setLoading(true); setError(null);
    setDetail(null); setSpectraList([]); setActiveSpectrum(null); setClassification(null);

    // Parallel fetches. Classification commonly 404s — swallow that case.
    Promise.all([
      api.getPlanet(planetName),
      api.listSpectra(planetName),
      api.getClassification(planetName).catch(() => null),
    ])
      .then(([d, specs, cls]) => {
        setDetail(d);
        setSpectraList(specs);
        setClassification(cls);
        // Auto-load the first spectrum if available
        if (specs.length > 0) {
          return api.getSpectrum(specs[0].id).then(setActiveSpectrum);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [planetName]);

  if (!planetName) return null;

  const seed = planetName.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  const hue = (seed * 37) % 360;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close" onClick={onClose}><X size={18}/></button>

        <div className="drawer-hero">
          <div className="drawer-orb" style={{
            background: `radial-gradient(circle at 30% 30%,
              hsl(${hue}, 70%, 65%),
              hsl(${(hue + 40) % 360}, 60%, 35%) 60%,
              hsl(${(hue + 80) % 360}, 50%, 15%) 100%)`,
          }} />
          <div>
            <div className="drawer-eyebrow">DARWIN RECORD</div>
            <h2 className="drawer-title">{planetName}</h2>
            {detail && (
              <div className="drawer-host">
                orbiting {detail.hostname ?? '—'}
                {detail.sy_dist != null && ` · ${detail.sy_dist.toFixed(2)} pc`}
              </div>
            )}
          </div>
        </div>

        {loading && <div className="loading-mini">Fetching record<span className="dots">...</span></div>}
        {error && <div className="error-mini"><AlertCircle size={14}/> {error}</div>}

        {detail && (
          <>
            <div className="drawer-grid">
              {[
                ['Equilibrium Temp', detail.pl_eqt, 'K', 0],
                ['Radius',           detail.pl_rade, 'R⊕', 2],
                ['Mass',             detail.pl_masse, 'M⊕', 2],
                ['Insolation',       detail.pl_insol, 'S⊕', 2],
                ['Orbital Period',   detail.pl_orbper, 'd', 2],
                ['Semi-Major Axis',  detail.pl_orbsmax, 'AU', 3],
                ['Stellar T_eff',    detail.st_teff, 'K', 0],
                ['Discovered',       detail.disc_year, '', 0],
              ].map(([k, v, u, p]) => (
                <div key={k} className="drawer-stat">
                  <div className="drawer-stat-key">{k}</div>
                  <div className="drawer-stat-val">
                    {v != null ? (typeof v === 'number' ? v.toFixed(p) : v) : '—'}
                    {v != null && u && <span className="drawer-stat-unit"> {u}</span>}
                  </div>
                </div>
              ))}
            </div>

            <div className="drawer-flags">
              <div className={`flag ${detail.in_hz ? 'on' : ''}`}>
                {detail.in_hz ? '✓' : '·'} habitable zone
              </div>
              <div className={`flag ${detail.is_rocky_candidate ? 'on' : ''}`}>
                {detail.is_rocky_candidate ? '✓' : '·'} rocky candidate
              </div>
              <div className="flag score">
                score: {detail.habitability_score != null ? detail.habitability_score.toFixed(1) : '—'}
              </div>
            </div>

            {classification && (
              <div className="drawer-section">
                <div className="drawer-section-title"><Activity size={11}/> ANALYSIS</div>
                <div className="classification-badges">
                  {classification.habitability_label && (
                    <span className={`cls-badge cls-${classification.habitability_label}`}>
                      {classification.habitability_label}
                    </span>
                  )}
                  {classification.biosignature_label && (
                    <span className="cls-badge cls-bio">
                      biosignature: {classification.biosignature_label}
                    </span>
                  )}
                  {classification.confidence != null && (
                    <span className="cls-confidence">
                      {(classification.confidence * 100).toFixed(0)}% confidence
                    </span>
                  )}
                </div>
                {classification.reasoning && (
                  <div className="cls-prose">{classification.reasoning}</div>
                )}
                {classification.caveats && (
                  <div className="cls-caveats"><AlertCircle size={11}/> {classification.caveats}</div>
                )}
              </div>
            )}

            {spectraList.length > 0 && (
              <div className="drawer-section">
                <div className="drawer-section-title"><Sparkles size={11}/> SPECTRA</div>
                <div className="spectra-tabs">
                  {spectraList.map((s) => (
                    <button
                      key={s.id}
                      className={`spectra-tab ${activeSpectrum?.id === s.id ? 'active' : ''}`}
                      onClick={() => api.getSpectrum(s.id).then(setActiveSpectrum)}
                    >
                      {s.instrument}
                      <span className="spectra-tab-meta">
                        {s.wavelength_min_um.toFixed(1)}–{s.wavelength_max_um.toFixed(1)} μm
                      </span>
                    </button>
                  ))}
                </div>
                <SpectrumPlot spectrum={activeSpectrum} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ============================================================
// MAIN APP
// ============================================================
export default function HabitablePlanetCatalog() {
  const [planets, setPlanets]       = useState([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [view, setView]             = useState('cards');
  const [search, setSearch]         = useState('');
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [selectedName, setSelectedName] = useState(null);

  // Server-side filters (trigger refetch)
  const [minScore, setMinScore]     = useState(0.5);
  const [hasSpectrum, setHasSpectrum] = useState(false);
  const [rocky, setRocky]           = useState(false);

  // Client-side filters (operate on current result set)
  const [ranges, setRanges] = useState(
    Object.fromEntries(CLIENT_FILTERS.map(f => [f.key, f.defaultRange]))
  );

  const [sortKey, setSortKey] = useState('habitability_score');
  const [sortDir, setSortDir] = useState('desc');

  // Fetch whenever server-side params change
  const loadPlanets = useCallback(() => {
    setLoading(true); setError(null);
    api.listPlanets({
      min_score: minScore > 0 ? minScore : undefined,
      has_spectrum: hasSpectrum ? true : undefined,
      rocky: rocky ? true : undefined,
      limit: 1000,
    })
      .then(setPlanets)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [minScore, hasSpectrum, rocky]);

  useEffect(() => { loadPlanets(); }, [loadPlanets]);

  // Client-side filtering + sorting on top of server response
  const filtered = useMemo(() => {
    let r = planets.filter((p) => {
      if (search) {
        const q = search.toLowerCase();
        if (!p.pl_name.toLowerCase().includes(q) &&
            !(p.hostname || '').toLowerCase().includes(q)) return false;
      }
      for (const f of CLIENT_FILTERS) {
        const v = p[f.key];
        if (v == null) continue; // don't exclude unknowns
        const [lo, hi] = ranges[f.key];
        if (v < lo || v > hi) return false;
      }
      return true;
    });
    r.sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === 'asc' ? av - bv : bv - av;
    });
    return r;
  }, [planets, search, ranges, sortKey, sortDir]);

  const resetFilters = () => {
    setRanges(Object.fromEntries(CLIENT_FILTERS.map(f => [f.key, f.defaultRange])));
    setSearch(''); setRocky(false); setHasSpectrum(false); setMinScore(0.5);
  };

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  return (
    <div className="app">
      <style>{STYLES}</style>

      {/* HEADER */}
      <header className="header">
        <div className="header-left">
          <Telescope size={20} className="logo-icon" />
          <div>
            <div className="brand">DARWIN</div>
            <div className="brand-sub">Atmospheric Readings · Worlds · Infrared Analysis</div>
          </div>
        </div>
        <div className="header-right">
          <div className="header-stat">
            <div className="header-stat-num">{filtered.length}</div>
            <div className="header-stat-label">shown</div>
          </div>
          <div className="header-stat">
            <div className="header-stat-num">{planets.length}</div>
            <div className="header-stat-label">indexed</div>
          </div>
        </div>
      </header>

      <div className="main">
        {/* SIDEBAR */}
        <aside className={`sidebar ${filtersOpen ? 'open' : 'closed'}`}>
          <div className="sidebar-header">
            <div className="sidebar-title"><SlidersHorizontal size={14}/> FILTERS</div>
            <button className="reset-btn" onClick={resetFilters}>reset</button>
          </div>

          <div className="search-wrap">
            <Search size={14} className="search-icon" />
            <input type="text" placeholder="search planet or host..." value={search}
              onChange={(e) => setSearch(e.target.value)} className="search-input" />
          </div>

          <div className="server-section">
            <div className="server-section-title">SERVER · DARWIN scoring</div>
            <ScoreStepper value={minScore} onChange={setMinScore} />
            <label className="toggle-row">
              <input type="checkbox" checked={rocky} onChange={(e) => setRocky(e.target.checked)} />
              <span>rocky candidates only</span>
            </label>
            <label className="toggle-row">
              <input type="checkbox" checked={hasSpectrum} onChange={(e) => setHasSpectrum(e.target.checked)} />
              <span>JWST spectrum available</span>
            </label>
          </div>

          <div className="server-section">
            <div className="server-section-title">CLIENT · refine view</div>
            <div className="filters">
              {CLIENT_FILTERS.map((f) => (
                <RangeSlider key={f.key} filter={f} value={ranges[f.key]}
                  onChange={(v) => setRanges({ ...ranges, [f.key]: v })} />
              ))}
            </div>
          </div>
        </aside>

        {/* CONTENT */}
        <main className="content">
          <div className="toolbar">
            <button className="sidebar-toggle" onClick={() => setFiltersOpen(!filtersOpen)}>
              <SlidersHorizontal size={14}/> {filtersOpen ? 'hide' : 'show'} filters
            </button>
            <div className="view-toggle">
              <button className={view === 'cards' ? 'active' : ''} onClick={() => setView('cards')}>
                <Grid3x3 size={14}/> cards
              </button>
              <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>
                <Table2 size={14}/> table
              </button>
            </div>
          </div>

          {error && (
            <div className="error-banner">
              <AlertCircle size={16} />
              <div>
                <strong>Couldn't reach the API at {API_BASE}.</strong>
                <div className="error-detail">{error}</div>
                <div className="error-hint">
                  Make sure the backend is running: <code>uvicorn darwin.api.app:app --reload</code>
                </div>
              </div>
            </div>
          )}

          {loading ? (
            <div className="loading">Querying DARWIN<span className="dots">...</span></div>
          ) : filtered.length === 0 && !error ? (
            <div className="empty">
              <div className="empty-title">No planets match.</div>
              <div className="empty-sub">Widen your filters or reduce min habitability.</div>
            </div>
          ) : view === 'cards' ? (
            <div className="cards-grid">
              {filtered.map((p) => <PlanetCard key={p.pl_name} planet={p} onClick={() => setSelectedName(p.pl_name)} />)}
            </div>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {[
                      ['pl_name', 'Planet'],
                      ['hostname', 'Host'],
                      ['habitability_score', 'Score'],
                      ['pl_eqt', 'T_eq (K)'],
                      ['pl_rade', 'R (R⊕)'],
                      ['sy_dist', 'd (pc)'],
                    ].map(([key, label]) => (
                      <th key={key} onClick={() => toggleSort(key)}>
                        {label}
                        {sortKey === key && (sortDir === 'asc' ? <ChevronUp size={12}/> : <ChevronDown size={12}/>)}
                      </th>
                    ))}
                    <th>Spectra</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p) => (
                    <tr key={p.pl_name} onClick={() => setSelectedName(p.pl_name)}>
                      <td className="td-name">{p.pl_name}</td>
                      <td>{p.hostname ?? '—'}</td>
                      <td className="td-score">
                        <span className="score-bar" style={{
                          width: `${(p.habitability_score ?? 0) * 100}%`
                        }}/>
                        {p.habitability_score != null ? p.habitability_score.toFixed(1) : '—'}
                      </td>
                      <td>{p.pl_eqt != null ? Math.round(p.pl_eqt) : '—'}</td>
                      <td>{p.pl_rade != null ? p.pl_rade.toFixed(2) : '—'}</td>
                      <td>{p.sy_dist != null ? p.sy_dist.toFixed(1) : '—'}</td>
                      <td>{p.has_spectrum
                        ? <span className="jwst-pill">{p.n_spectra}</span>
                        : <span className="dot-no"/>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </main>
      </div>

      <DetailDrawer planetName={selectedName} onClose={() => setSelectedName(null)} />
    </div>
  );
}

// ============================================================
// STYLES
// ============================================================
const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;600&display=swap');

  :root {
    --bg: #0a0e17;
    --bg-2: #111722;
    --bg-3: #161e2c;
    --line: rgba(255, 255, 255, 0.06);
    --line-2: rgba(255, 255, 255, 0.12);
    --text: #e8eaf0;
    --text-dim: #8a93a8;
    --text-dimmer: #525c73;
    --accent: #ffb547;
    --accent-2: #ff7a59;
    --jwst: #d4a574;
    --good: #6fcf97;
    --warn: #f2994a;
    --bad: #eb5757;
    --serif: 'Fraunces', Georgia, serif;
    --mono: 'JetBrains Mono', 'SF Mono', monospace;
  }
  * { box-sizing: border-box; }

  .app {
    min-height: 100vh;
    background: var(--bg);
    background-image:
      radial-gradient(ellipse at 20% 10%, rgba(255, 181, 71, 0.06), transparent 50%),
      radial-gradient(ellipse at 80% 80%, rgba(255, 122, 89, 0.05), transparent 50%);
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
  }

  /* HEADER */
  .header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 20px 32px;
    border-bottom: 1px solid var(--line);
    background: rgba(10, 14, 23, 0.7);
    backdrop-filter: blur(10px);
    position: sticky; top: 0; z-index: 10;
  }
  .header-left { display: flex; align-items: center; gap: 14px; }
  .logo-icon { color: var(--accent); }
  .brand { font-family: var(--serif); font-size: 22px; font-weight: 600; letter-spacing: 0.02em; line-height: 1; }
  .brand-sub { font-size: 10px; color: var(--text-dim); letter-spacing: 0.08em; text-transform: uppercase; margin-top: 4px; }
  .header-right { display: flex; gap: 28px; }
  .header-stat { text-align: right; }
  .header-stat-num { font-family: var(--serif); font-size: 24px; font-weight: 500; line-height: 1; color: var(--accent); }
  .header-stat-label { font-size: 9px; color: var(--text-dim); letter-spacing: 0.1em; text-transform: uppercase; margin-top: 4px; }

  .main { display: flex; min-height: calc(100vh - 78px); }

  /* SIDEBAR */
  .sidebar {
    width: 320px;
    border-right: 1px solid var(--line);
    padding: 24px 22px;
    overflow-y: auto;
    transition: width 0.3s ease, padding 0.3s ease;
    flex-shrink: 0;
  }
  .sidebar.closed { width: 0; padding: 24px 0; overflow: hidden; }
  .sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
  .sidebar-title { display: flex; align-items: center; gap: 8px; font-size: 10px; letter-spacing: 0.12em; color: var(--text-dim); }
  .reset-btn { background: none; border: none; color: var(--accent); font-family: var(--mono); font-size: 11px; cursor: pointer; padding: 0; }
  .reset-btn:hover { color: var(--accent-2); }

  .search-wrap { position: relative; margin-bottom: 18px; }
  .search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-dim); }
  .search-input {
    width: 100%; background: var(--bg-2); border: 1px solid var(--line);
    color: var(--text); padding: 9px 10px 9px 30px;
    font-family: var(--mono); font-size: 12px; border-radius: 2px;
  }
  .search-input:focus { outline: none; border-color: var(--accent); }

  .server-section { padding-top: 14px; margin-top: 14px; border-top: 1px dashed var(--line); }
  .server-section:first-of-type { padding-top: 0; margin-top: 0; border-top: none; }
  .server-section-title {
    font-size: 9px; letter-spacing: 0.12em; color: var(--text-dimmer);
    margin-bottom: 14px;
  }

  .toggle-row { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-dim); padding: 6px 0; cursor: pointer; }
  .toggle-row input { accent-color: var(--accent); }

  /* SCORE STEPPER */
  .score-stepper {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px;
    margin-bottom: 8px;
  }
  .score-stop {
    background: var(--bg-2); border: 1px solid var(--line);
    color: var(--text-dim); font-family: var(--mono); font-size: 10px;
    padding: 8px 6px; cursor: pointer; border-radius: 2px;
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    transition: all 0.15s;
  }
  .score-stop:hover { border-color: var(--line-2); color: var(--text); }
  .score-stop.active { background: rgba(255, 181, 71, 0.08); border-color: var(--accent); color: var(--accent); }
  .score-stop-dots { display: flex; gap: 3px; }
  .stop-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--text-dimmer); }
  .score-stop.active .stop-dot.filled { background: var(--accent); }
  .stop-dot.filled { background: var(--text-dim); }
  .score-stop-label { letter-spacing: 0.04em; }
  .filter-hint { font-size: 10px; color: var(--text-dimmer); margin-bottom: 12px; line-height: 1.4; font-style: italic; }

  /* SLIDERS */
  .filters { display: flex; flex-direction: column; gap: 18px; }
  .filter-row { }
  .filter-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
  .filter-label { font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text); }
  .filter-value { font-size: 11px; color: var(--accent); }
  .filter-unit { color: var(--text-dim); }
  .slider-track-wrap { position: relative; height: 24px; }
  .slider-track { position: absolute; top: 11px; left: 0; right: 0; height: 2px; background: var(--line-2); }
  .slider-range { position: absolute; top: 11px; height: 2px; background: var(--accent); }
  .slider-input {
    position: absolute; top: 0; left: 0; width: 100%; height: 24px;
    background: transparent; pointer-events: none;
    -webkit-appearance: none; appearance: none;
  }
  .slider-input::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none;
    width: 14px; height: 14px; background: var(--bg); border: 2px solid var(--accent);
    border-radius: 50%; pointer-events: auto; cursor: grab; margin-top: 0;
  }
  .slider-input::-moz-range-thumb {
    width: 14px; height: 14px; background: var(--bg); border: 2px solid var(--accent);
    border-radius: 50%; pointer-events: auto; cursor: grab;
  }

  /* CONTENT */
  .content { flex: 1; padding: 24px 32px; overflow-y: auto; min-width: 0; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 22px; }
  .sidebar-toggle, .view-toggle button {
    display: flex; align-items: center; gap: 6px;
    background: var(--bg-2); border: 1px solid var(--line);
    color: var(--text-dim); font-family: var(--mono); font-size: 11px;
    padding: 7px 12px; cursor: pointer; border-radius: 2px; text-transform: lowercase;
  }
  .sidebar-toggle:hover { color: var(--text); border-color: var(--line-2); }
  .view-toggle { display: flex; gap: 0; }
  .view-toggle button { border-radius: 0; border-right: none; }
  .view-toggle button:first-child { border-radius: 2px 0 0 2px; }
  .view-toggle button:last-child { border-radius: 0 2px 2px 0; border-right: 1px solid var(--line); }
  .view-toggle button.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }

  /* ERROR BANNER */
  .error-banner {
    background: rgba(235, 87, 87, 0.08);
    border: 1px solid rgba(235, 87, 87, 0.3);
    border-left: 3px solid var(--bad);
    padding: 14px 18px;
    margin-bottom: 18px;
    border-radius: 2px;
    display: flex; gap: 12px; align-items: flex-start;
    color: var(--text);
  }
  .error-banner > svg { color: var(--bad); margin-top: 2px; flex-shrink: 0; }
  .error-detail { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
  .error-hint { font-size: 11px; color: var(--text-dim); margin-top: 8px; }
  .error-hint code { background: var(--bg-3); padding: 2px 6px; border-radius: 2px; color: var(--accent); }

  /* CARDS */
  .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
  .planet-card {
    background: var(--bg-2); border: 1px solid var(--line);
    cursor: pointer; transition: border-color 0.2s, transform 0.2s;
    overflow: hidden; display: flex; flex-direction: column;
  }
  .planet-card:hover { border-color: var(--accent); transform: translateY(-2px); }
  .planet-card-visual {
    height: 130px; position: relative;
    display: flex; align-items: center; justify-content: center;
    background: radial-gradient(circle at 50% 50%, rgba(255, 181, 71, 0.04), transparent 60%), var(--bg-3);
    overflow: hidden;
  }
  .planet-card-visual::before {
    content: ''; position: absolute; inset: 0;
    background-image:
      radial-gradient(1px 1px at 20% 30%, white, transparent),
      radial-gradient(1px 1px at 70% 60%, white, transparent),
      radial-gradient(1px 1px at 40% 80%, white, transparent),
      radial-gradient(1px 1px at 85% 20%, white, transparent),
      radial-gradient(1px 1px at 15% 75%, white, transparent);
    opacity: 0.4;
  }
  .planet-orb {
    width: 90px; height: 90px; border-radius: 50%;
    box-shadow: 0 0 40px rgba(0,0,0,0.5), inset -10px -10px 20px rgba(0,0,0,0.3);
    position: relative; z-index: 1;
  }
  .jwst-badge {
    position: absolute; top: 10px; right: 10px;
    display: flex; align-items: center; gap: 4px;
    background: rgba(212, 165, 116, 0.15); border: 1px solid var(--jwst);
    color: var(--jwst); font-size: 9px; padding: 3px 7px;
    letter-spacing: 0.08em; border-radius: 2px;
  }
  .planet-card-body { padding: 14px 16px 16px; }
  .planet-name { font-family: var(--serif); font-size: 17px; font-weight: 500; color: var(--text); }
  .planet-host { font-size: 10px; color: var(--text-dim); letter-spacing: 0.05em; margin-top: 3px; margin-bottom: 12px; }
  .planet-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 14px; border-top: 1px solid var(--line); padding-top: 12px; }
  .stat { display: flex; justify-content: space-between; align-items: baseline; }
  .stat-key { color: var(--text-dimmer); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; }
  .stat-val { color: var(--text); font-size: 12px; }
  .stat-unit { color: var(--text-dim); font-size: 9px; margin-left: 2px; }

  /* TABLE */
  .table-wrap { background: var(--bg-2); border: 1px solid var(--line); overflow-x: auto; }
  .data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .data-table th {
    background: var(--bg-3); color: var(--text-dim); text-align: left;
    padding: 11px 14px; font-weight: 500; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.08em;
    cursor: pointer; border-bottom: 1px solid var(--line); white-space: nowrap;
  }
  .data-table th:hover { color: var(--text); }
  .data-table td { padding: 11px 14px; border-bottom: 1px solid var(--line); }
  .data-table tr { cursor: pointer; }
  .data-table tr:hover td { background: rgba(255, 181, 71, 0.04); }
  .td-name { font-family: var(--serif); font-size: 14px; color: var(--text); }
  .td-score { position: relative; }
  .score-bar {
    position: absolute; left: 0; top: 0; bottom: 0;
    background: linear-gradient(90deg, transparent, rgba(111, 207, 151, 0.15));
    pointer-events: none;
  }
  .jwst-pill {
    display: inline-block; background: rgba(212, 165, 116, 0.15);
    border: 1px solid var(--jwst); color: var(--jwst);
    font-size: 10px; padding: 1px 7px; border-radius: 2px;
  }
  .dot-no { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--text-dimmer); }

  /* EMPTY / LOADING */
  .loading, .empty { text-align: center; padding: 80px 20px; color: var(--text-dim); }
  .loading-mini { padding: 18px 0; color: var(--text-dim); font-size: 12px; }
  .error-mini { color: var(--bad); padding: 12px; background: rgba(235,87,87,0.05); border-radius: 2px; display: flex; gap: 8px; align-items: center; font-size: 12px; }
  .empty-title { font-family: var(--serif); font-size: 18px; color: var(--text); margin-bottom: 6px; }
  .empty-sub { font-size: 12px; }
  .dots { animation: dots 1.4s infinite; }
  @keyframes dots { 0%, 20% { opacity: 0; } 50% { opacity: 1; } 100% { opacity: 0; } }

  /* DRAWER */
  .drawer-backdrop {
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px); z-index: 100;
    animation: fadein 0.2s ease;
  }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }
  .drawer {
    position: fixed; right: 0; top: 0; bottom: 0;
    width: 520px; max-width: 92vw;
    background: var(--bg-2); border-left: 1px solid var(--line-2);
    padding: 36px 32px; overflow-y: auto;
    animation: slidein 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes slidein { from { transform: translateX(100%); } to { transform: translateX(0); } }
  .drawer-close { position: absolute; top: 18px; right: 18px; background: none; border: none; color: var(--text-dim); cursor: pointer; padding: 6px; }
  .drawer-close:hover { color: var(--text); }
  .drawer-hero { display: flex; gap: 18px; align-items: center; margin-bottom: 24px; }
  .drawer-orb { width: 80px; height: 80px; border-radius: 50%; box-shadow: 0 0 40px rgba(0,0,0,0.5), inset -10px -10px 20px rgba(0,0,0,0.3); flex-shrink: 0; }
  .drawer-eyebrow { font-size: 9px; letter-spacing: 0.12em; color: var(--accent); margin-bottom: 6px; }
  .drawer-title { font-family: var(--serif); font-size: 28px; font-weight: 500; margin: 0 0 4px; line-height: 1.1; }
  .drawer-host { font-size: 11px; color: var(--text-dim); letter-spacing: 0.03em; }
  .drawer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
  .drawer-stat { background: var(--bg-3); padding: 10px 12px; border-left: 2px solid var(--accent); }
  .drawer-stat-key { font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-dim); margin-bottom: 4px; }
  .drawer-stat-val { font-family: var(--serif); font-size: 15px; color: var(--text); }
  .drawer-stat-unit { font-size: 10px; color: var(--text-dim); font-family: var(--mono); }
  .drawer-flags { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 24px; }
  .flag {
    font-size: 10px; padding: 5px 10px; border-radius: 2px;
    border: 1px solid var(--line-2); color: var(--text-dim);
    letter-spacing: 0.04em;
  }
  .flag.on { background: rgba(111, 207, 151, 0.08); border-color: var(--good); color: var(--good); }
  .flag.score { background: var(--bg-3); }
  .drawer-section { margin-bottom: 24px; padding-top: 18px; border-top: 1px solid var(--line); }
  .drawer-section-title { display: flex; align-items: center; gap: 6px; font-size: 10px; letter-spacing: 0.12em; color: var(--text-dim); margin-bottom: 14px; }

  /* CLASSIFICATION */
  .classification-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
  .cls-badge { font-size: 10px; padding: 4px 9px; border-radius: 2px; letter-spacing: 0.04em; }
  .cls-habitable { background: rgba(111, 207, 151, 0.12); color: var(--good); border: 1px solid rgba(111, 207, 151, 0.3); }
  .cls-marginal { background: rgba(242, 153, 74, 0.12); color: var(--warn); border: 1px solid rgba(242, 153, 74, 0.3); }
  .cls-uninhabitable { background: rgba(235, 87, 87, 0.08); color: var(--bad); border: 1px solid rgba(235, 87, 87, 0.3); }
  .cls-bio { background: rgba(255, 181, 71, 0.08); color: var(--accent); border: 1px solid rgba(255, 181, 71, 0.3); }
  .cls-confidence { font-size: 10px; color: var(--text-dim); }
  .cls-prose { font-family: var(--serif); font-size: 13px; line-height: 1.55; color: var(--text); margin: 10px 0; }
  .cls-caveats { font-size: 11px; color: var(--warn); display: flex; gap: 6px; align-items: flex-start; padding-top: 6px; border-top: 1px dashed var(--line); }

  /* SPECTRA */
  .spectra-tabs { display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }
  .spectra-tab {
    background: var(--bg-3); border: 1px solid var(--line);
    color: var(--text-dim); padding: 6px 10px; font-family: var(--mono);
    font-size: 10px; cursor: pointer; border-radius: 2px;
    display: flex; flex-direction: column; gap: 2px; text-align: left;
  }
  .spectra-tab:hover { color: var(--text); border-color: var(--line-2); }
  .spectra-tab.active { background: rgba(255, 181, 71, 0.08); border-color: var(--accent); color: var(--accent); }
  .spectra-tab-meta { font-size: 9px; opacity: 0.7; }
  .spectrum-plot { background: var(--bg-3); padding: 8px; border: 1px solid var(--line); border-radius: 2px; }
  .spectrum-caption { font-size: 9px; color: var(--text-dim); text-align: center; margin-top: 4px; letter-spacing: 0.05em; }

  /* Responsive */
  @media (max-width: 900px) {
    .header { padding: 16px 18px; }
    .content { padding: 18px; }
    .sidebar { position: fixed; left: 0; top: 78px; bottom: 0; z-index: 50; background: var(--bg); }
    .sidebar.closed { transform: translateX(-100%); width: 320px; padding: 24px 22px; }
  }
`;
