import React, { useState, useEffect, createContext, useContext } from 'react';
import axios from 'axios';

// --- API setup ---
const API_BASE = process.env.REACT_APP_API_URL || '';

const api = axios.create({ baseURL: `${API_BASE}/api` });

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Token ${token}`;
  return config;
});

// --- Auth context ---
const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      api.get('/auth/me/')
        .then(r => { setUser(r.data.user); setOrg(r.data.organisation); })
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (username, password) => {
    const r = await api.post('/auth/login/', { username, password });
    localStorage.setItem('token', r.data.token);
    setUser(r.data.user);
    setOrg(r.data.organisation);
    return r.data;
  };

  const logout = async () => {
    try { await api.post('/auth/logout/'); } catch(e) {}
    localStorage.removeItem('token');
    setUser(null); setOrg(null);
  };

  return (
    <AuthContext.Provider value={{ user, org, loading, login, logout, api }}>
      {children}
    </AuthContext.Provider>
  );
}

// --- Simple router using hash ---
function useRoute() {
  const [path, setPath] = useState(window.location.hash || '#dashboard');
  useEffect(() => {
    const handler = () => setPath(window.location.hash || '#dashboard');
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  return path;
}

export { api };
export default function App() {
  return (
    <AuthProvider>
      <AppInner />
    </AuthProvider>
  );
}

function AppInner() {
  const { user, loading } = useAuth();
  const path = useRoute();

  if (loading) return <FullPageSpinner />;
  if (!user) return <LoginPage />;

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: '"DM Sans", system-ui, sans-serif', background: '#0e1117', color: '#e2e8f0' }}>
      <Sidebar path={path} />
      <main style={{ flex: 1, overflow: 'auto', padding: '32px' }}>
        {path === '#dashboard' && <DashboardPage />}
        {path === '#records' && <RecordsPage />}
        {path === '#upload' && <UploadPage />}
        {path === '#batches' && <BatchesPage />}
        {path === '#audit' && <AuditPage />}
      </main>
    </div>
  );
}

function FullPageSpinner() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#0e1117', color: '#94a3b8' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ width: 40, height: 40, border: '3px solid #1e293b', borderTop: '3px solid #22d3ee', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 16px' }} />
        <div style={{ fontFamily: 'monospace', fontSize: 13 }}>Loading…</div>
      </div>
    </div>
  );
}

// =================== LOGIN ===================
function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('analyst');
  const [password, setPassword] = useState('demo1234');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      await login(username, password);
    } catch(e) {
      setError('Invalid credentials');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#0e1117', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0e1117; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity:0; transform: translateY(8px); } to { opacity:1; transform:none; } }
      `}</style>
      <div style={{ width: 400, animation: 'fadeIn .4s ease' }}>
        <div style={{ marginBottom: 32, textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.5px', color: '#f1f5f9', fontFamily: '"DM Sans", sans-serif' }}>
            <span style={{ color: '#22d3ee' }}>Breathe</span> ESG
          </div>
          <div style={{ color: '#64748b', fontSize: 13, marginTop: 6, fontFamily: '"DM Mono", monospace' }}>
            Emissions ingestion & review
          </div>
        </div>
        <div style={{ background: '#1a2035', border: '1px solid #1e293b', borderRadius: 12, padding: 32 }}>
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 12, color: '#64748b', marginBottom: 6, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 1 }}>Username</label>
              <input value={username} onChange={e=>setUsername(e.target.value)}
                style={{ width: '100%', background: '#0e1117', border: '1px solid #334155', borderRadius: 8, padding: '10px 14px', color: '#e2e8f0', fontSize: 14, outline: 'none' }} />
            </div>
            <div style={{ marginBottom: 24 }}>
              <label style={{ display: 'block', fontSize: 12, color: '#64748b', marginBottom: 6, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 1 }}>Password</label>
              <input type="password" value={password} onChange={e=>setPassword(e.target.value)}
                style={{ width: '100%', background: '#0e1117', border: '1px solid #334155', borderRadius: 8, padding: '10px 14px', color: '#e2e8f0', fontSize: 14, outline: 'none' }} />
            </div>
            {error && <div style={{ color: '#f87171', fontSize: 13, marginBottom: 16 }}>{error}</div>}
            <button type="submit" disabled={loading}
              style={{ width: '100%', background: '#22d3ee', color: '#0e1117', border: 'none', borderRadius: 8, padding: '12px', fontSize: 14, fontWeight: 600, cursor: 'pointer', opacity: loading ? 0.7 : 1 }}>
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          <div style={{ marginTop: 20, padding: '12px 14px', background: '#0e1117', borderRadius: 8, fontSize: 12, fontFamily: '"DM Mono", monospace', color: '#64748b' }}>
            Demo: analyst / demo1234 &nbsp;·&nbsp; admin / admin1234
          </div>
        </div>
      </div>
    </div>
  );
}

// =================== SIDEBAR ===================
function Sidebar({ path }) {
  const { user, org, logout } = useAuth();
  const nav = [
    { id: '#dashboard', label: 'Dashboard', icon: '⬡' },
    { id: '#records', label: 'Records', icon: '≡' },
    { id: '#upload', label: 'Upload', icon: '↑' },
    { id: '#batches', label: 'Batches', icon: '⊞' },
    { id: '#audit', label: 'Audit Log', icon: '⊙' },
  ];

  return (
    <nav style={{ width: 220, background: '#111827', borderRight: '1px solid #1e293b', display: 'flex', flexDirection: 'column', padding: '24px 0' }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');
        * { box-sizing: border-box; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity:0; transform: translateY(8px); } to { opacity:1; transform:none; } }
        @keyframes slideIn { from { opacity:0; transform: translateX(-8px); } to { opacity:1; transform:none; } }
        ::-webkit-scrollbar { width: 4px; } ::-webkit-scrollbar-track { background: #0e1117; } ::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
      `}</style>
      <div style={{ padding: '0 20px 24px', borderBottom: '1px solid #1e293b' }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#f1f5f9' }}>
          <span style={{ color: '#22d3ee' }}>Breathe</span> ESG
        </div>
        <div style={{ fontSize: 11, color: '#64748b', marginTop: 4, fontFamily: '"DM Mono", monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {org?.name || 'No org'}
        </div>
      </div>
      <div style={{ flex: 1, padding: '16px 12px' }}>
        {nav.map(item => (
          <a key={item.id} href={item.id}
            style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
              borderRadius: 8, textDecoration: 'none', marginBottom: 2,
              color: path === item.id ? '#22d3ee' : '#94a3b8',
              background: path === item.id ? 'rgba(34,211,238,0.08)' : 'transparent',
              fontSize: 14, fontWeight: path === item.id ? 500 : 400,
              transition: 'all .15s',
            }}>
            <span style={{ fontSize: 12, opacity: 0.8 }}>{item.icon}</span>
            {item.label}
          </a>
        ))}
      </div>
      <div style={{ padding: '16px 20px', borderTop: '1px solid #1e293b' }}>
        <div style={{ fontSize: 12, color: '#475569', marginBottom: 8, fontFamily: '"DM Mono", monospace', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {user?.username}
        </div>
        <button onClick={logout}
          style={{ fontSize: 12, color: '#64748b', background: 'none', border: '1px solid #334155', borderRadius: 6, padding: '5px 10px', cursor: 'pointer' }}>
          Sign out
        </button>
      </div>
    </nav>
  );
}

// =================== DASHBOARD ===================
function DashboardPage() {
  const { api } = useAuth();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/dashboard/').then(r => setStats(r.data)).finally(() => setLoading(false));
  }, []);

  if (loading) return <PageLoader />;

  const scopeColors = { scope_1: '#f97316', scope_2: '#22d3ee', scope_3: '#a78bfa' };

  return (
    <div style={{ animation: 'fadeIn .3s ease' }}>
      <PageHeader title="Dashboard" subtitle="Emissions overview and review status" />

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        <KpiCard label="Total Records" value={stats.total_records} color="#22d3ee" />
        <KpiCard label="Pending Review" value={stats.pending_count} color="#fbbf24" badge="action" />
        <KpiCard label="Flagged" value={stats.flagged_count} color="#f87171" badge="warn" />
        <KpiCard label="Approved" value={stats.approved_count} color="#34d399" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 24 }}>
        <KpiCard label="Total tCO₂e" value={(stats.total_co2e_kg / 1000).toFixed(1)} unit="tCO₂e" color="#94a3b8" />
        <KpiCard label="Approved tCO₂e" value={(stats.approved_co2e_kg / 1000).toFixed(1)} unit="tCO₂e" color="#34d399" />
        <KpiCard label="Completion" value={stats.total_records > 0 ? Math.round(stats.approved_count / stats.total_records * 100) : 0} unit="%" color="#22d3ee" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
        {/* Scope breakdown */}
        <Card title="Scope Breakdown (kgCO₂e)">
          {Object.entries(stats.scope_breakdown).map(([key, val]) => {
            const scopeNum = key.replace('scope_', '');
            const total_all = Object.values(stats.scope_breakdown).reduce((s, v) => s + v.co2e_kg, 0);
            const pct = total_all > 0 ? (val.co2e_kg / total_all * 100) : 0;
            return (
              <div key={key} style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, color: scopeColors[key] || '#94a3b8' }}>
                    Scope {scopeNum}
                  </span>
                  <span style={{ fontSize: 13, fontFamily: '"DM Mono", monospace', color: '#e2e8f0' }}>
                    {(val.co2e_kg / 1000).toFixed(2)} tCO₂e
                  </span>
                </div>
                <div style={{ height: 6, background: '#1e293b', borderRadius: 3 }}>
                  <div style={{ height: '100%', borderRadius: 3, background: scopeColors[key] || '#94a3b8', width: `${pct}%`, transition: 'width .6s ease' }} />
                </div>
                <div style={{ fontSize: 11, color: '#475569', marginTop: 3, fontFamily: '"DM Mono", monospace' }}>{val.count} records · {pct.toFixed(1)}%</div>
              </div>
            );
          })}
        </Card>

        {/* Category breakdown */}
        <Card title="Top Categories">
          {stats.category_breakdown.slice(0, 6).map((c, i) => {
            const maxCo2e = stats.category_breakdown[0]?.co2e_kg || 1;
            return (
              <div key={c.category} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <div style={{ width: 180, fontSize: 12, color: '#94a3b8', flexShrink: 0 }}>
                  {CATEGORY_LABELS[c.category] || c.category}
                </div>
                <div style={{ flex: 1, height: 6, background: '#1e293b', borderRadius: 3 }}>
                  <div style={{ height: '100%', borderRadius: 3, background: '#22d3ee', width: `${c.co2e_kg / maxCo2e * 100}%`, opacity: 1 - i * 0.12 }} />
                </div>
                <div style={{ fontSize: 11, color: '#64748b', fontFamily: '"DM Mono", monospace', minWidth: 80, textAlign: 'right' }}>
                  {(c.co2e_kg / 1000).toFixed(2)}t
                </div>
              </div>
            );
          })}
        </Card>
      </div>

      {/* Review status progress */}
      <Card title="Review Progress" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {[
            { label: 'Approved', count: stats.approved_count, color: '#34d399' },
            { label: 'Pending', count: stats.pending_count, color: '#fbbf24' },
            { label: 'Flagged', count: stats.flagged_count, color: '#f87171' },
            { label: 'Rejected', count: stats.rejected_count, color: '#475569' },
          ].map(s => {
            const pct = stats.total_records > 0 ? s.count / stats.total_records * 100 : 0;
            return pct > 0 ? (
              <div key={s.label} style={{ height: 32, background: s.color, borderRadius: 6, flex: pct, display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: 40, transition: 'flex .6s ease' }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#0e1117' }}>{s.count}</span>
              </div>
            ) : null;
          })}
        </div>
        <div style={{ display: 'flex', gap: 20, marginTop: 10 }}>
          {[
            { label: 'Approved', color: '#34d399' }, { label: 'Pending', color: '#fbbf24' },
            { label: 'Flagged', color: '#f87171' }, { label: 'Rejected', color: '#475569' }
          ].map(l => (
            <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#64748b' }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: l.color }} />
              {l.label}
            </div>
          ))}
        </div>
      </Card>

      {/* Recent batches */}
      <Card title="Recent Uploads">
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1e293b' }}>
              {['Source', 'File', 'Status', 'Rows OK / Total', 'Date'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#475569', fontWeight: 500, fontSize: 11, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stats.recent_batches.map(b => (
              <tr key={b.id} style={{ borderBottom: '1px solid #0f172a' }}>
                <td style={{ padding: '10px 12px' }}><SourceBadge type={b.source_type} /></td>
                <td style={{ padding: '10px 12px', color: '#94a3b8', fontFamily: '"DM Mono", monospace', fontSize: 11 }}>{b.original_filename}</td>
                <td style={{ padding: '10px 12px' }}><StatusBadge status={b.status} /></td>
                <td style={{ padding: '10px 12px', fontFamily: '"DM Mono", monospace', color: '#94a3b8', fontSize: 12 }}>{b.row_count_ok} / {b.row_count_total}</td>
                <td style={{ padding: '10px 12px', color: '#475569', fontSize: 11, fontFamily: '"DM Mono", monospace' }}>{new Date(b.uploaded_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// =================== RECORDS ===================
function RecordsPage() {
  const { api } = useAuth();
  const [records, setRecords] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());
  const [detail, setDetail] = useState(null);
  const [filters, setFilters] = useState({ review_status: '', scope: '', is_flagged: '', search: '' });
  const [page, setPage] = useState(1);
  const [actionLoading, setActionLoading] = useState(false);
  const [note, setNote] = useState('');

  const fetchRecords = () => {
    setLoading(true);
    const params = new URLSearchParams({ page, page_size: 50 });
    if (filters.review_status) params.set('review_status', filters.review_status);
    if (filters.scope) params.set('scope', filters.scope);
    if (filters.is_flagged === 'true') params.set('is_flagged', 'true');
    if (filters.search) params.set('search', filters.search);
    api.get(`/records/?${params}`).then(r => {
      setRecords(r.data.results);
      setCount(r.data.count);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { fetchRecords(); }, [filters, page]);

  const bulkAction = async (action) => {
    if (selected.size === 0) return;
    setActionLoading(true);
    try {
      await api.post('/records/bulk-review/', {
        record_ids: Array.from(selected),
        action, note,
      });
      setSelected(new Set());
      setNote('');
      fetchRecords();
    } finally { setActionLoading(false); }
  };

  const openDetail = async (id) => {
    const r = await api.get(`/records/${id}/`);
    setDetail(r.data);
  };

  const singleAction = async (id, action, actionNote) => {
    setActionLoading(true);
    try {
      await api.post(`/records/${id}/review/`, { action, note: actionNote || '' });
      fetchRecords();
      if (detail?.id === id) {
        const r = await api.get(`/records/${id}/`);
        setDetail(r.data);
      }
    } finally { setActionLoading(false); }
  };

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === records.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(records.map(r => r.id)));
    }
  };

  return (
    <div style={{ animation: 'fadeIn .3s ease' }}>
      <PageHeader title="Emission Records" subtitle={`${count} total records`} />

      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          placeholder="Search description, facility, supplier..."
          value={filters.search}
          onChange={e => { setFilters(f => ({ ...f, search: e.target.value })); setPage(1); }}
          style={{ background: '#1a2035', border: '1px solid #1e293b', borderRadius: 8, padding: '8px 12px', color: '#e2e8f0', fontSize: 13, width: 280, outline: 'none' }}
        />
        <FilterSelect label="Status" value={filters.review_status} onChange={v => { setFilters(f => ({ ...f, review_status: v })); setPage(1); }}
          options={[['', 'All statuses'], ['pending', 'Pending'], ['flagged', 'Flagged'], ['approved', 'Approved'], ['rejected', 'Rejected']]} />
        <FilterSelect label="Scope" value={filters.scope} onChange={v => { setFilters(f => ({ ...f, scope: v })); setPage(1); }}
          options={[['', 'All scopes'], ['1', 'Scope 1'], ['2', 'Scope 2'], ['3', 'Scope 3']]} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#94a3b8', cursor: 'pointer' }}>
          <input type="checkbox" checked={filters.is_flagged === 'true'} onChange={e => { setFilters(f => ({ ...f, is_flagged: e.target.checked ? 'true' : '' })); setPage(1); }} />
          Flagged only
        </label>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16, padding: '12px 16px', background: 'rgba(34,211,238,0.06)', border: '1px solid rgba(34,211,238,0.2)', borderRadius: 8, animation: 'fadeIn .2s ease' }}>
          <span style={{ fontSize: 13, color: '#22d3ee', fontFamily: '"DM Mono", monospace' }}>{selected.size} selected</span>
          <input placeholder="Note (optional)" value={note} onChange={e=>setNote(e.target.value)}
            style={{ flex: 1, background: '#0e1117', border: '1px solid #334155', borderRadius: 6, padding: '6px 10px', color: '#e2e8f0', fontSize: 12, outline: 'none' }} />
          <ActionButton color="#34d399" onClick={() => bulkAction('approve')} disabled={actionLoading}>✓ Approve</ActionButton>
          <ActionButton color="#f87171" onClick={() => bulkAction('reject')} disabled={actionLoading}>✕ Reject</ActionButton>
          <ActionButton color="#fbbf24" onClick={() => bulkAction('flag')} disabled={actionLoading}>⚑ Flag</ActionButton>
          <ActionButton color="#475569" onClick={() => setSelected(new Set())} disabled={false}>Clear</ActionButton>
        </div>
      )}

      {/* Table */}
      <Card>
        {loading ? <PageLoader /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                <th style={{ width: 32, padding: '8px 12px' }}>
                  <input type="checkbox" checked={selected.size === records.length && records.length > 0} onChange={selectAll} style={{ accentColor: '#22d3ee' }} />
                </th>
                {['Date', 'Scope', 'Category', 'Facility', 'CO₂e (kg)', 'Status', ''].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#475569', fontWeight: 500, fontSize: 11, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map(rec => (
                <tr key={rec.id} style={{ borderBottom: '1px solid #0f172a', cursor: 'pointer', background: selected.has(rec.id) ? 'rgba(34,211,238,0.04)' : 'transparent' }}
                  onMouseEnter={e => e.currentTarget.style.background = selected.has(rec.id) ? 'rgba(34,211,238,0.06)' : '#111827'}
                  onMouseLeave={e => e.currentTarget.style.background = selected.has(rec.id) ? 'rgba(34,211,238,0.04)' : 'transparent'}>
                  <td style={{ padding: '10px 12px' }} onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(rec.id)} onChange={() => toggleSelect(rec.id)} style={{ accentColor: '#22d3ee' }} />
                  </td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontFamily: '"DM Mono", monospace', fontSize: 12 }} onClick={() => openDetail(rec.id)}>{rec.activity_date}</td>
                  <td style={{ padding: '10px 12px' }} onClick={() => openDetail(rec.id)}><ScopeBadge scope={rec.scope} /></td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }} onClick={() => openDetail(rec.id)}>{CATEGORY_LABELS[rec.category] || rec.category}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} onClick={() => openDetail(rec.id)}>{rec.facility_name || '—'}</td>
                  <td style={{ padding: '10px 12px', fontFamily: '"DM Mono", monospace', color: '#e2e8f0', fontWeight: 500 }} onClick={() => openDetail(rec.id)}>
                    {parseFloat(rec.co2e_kg).toFixed(1)}
                    {rec.is_flagged && <span style={{ marginLeft: 6, color: '#fbbf24', fontSize: 11 }}>⚑</span>}
                    {rec.is_edited && <span style={{ marginLeft: 4, color: '#a78bfa', fontSize: 10 }}>edited</span>}
                  </td>
                  <td style={{ padding: '10px 12px' }} onClick={() => openDetail(rec.id)}><ReviewBadge status={rec.review_status} /></td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {rec.review_status !== 'approved' && rec.review_status !== 'locked' && (
                        <MiniBtn color="#34d399" onClick={e => { e.stopPropagation(); singleAction(rec.id, 'approve', ''); }}>✓</MiniBtn>
                      )}
                      {rec.review_status !== 'rejected' && rec.review_status !== 'locked' && (
                        <MiniBtn color="#f87171" onClick={e => { e.stopPropagation(); singleAction(rec.id, 'reject', ''); }}>✕</MiniBtn>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {/* Pagination */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 16, paddingTop: 16, borderTop: '1px solid #1e293b' }}>
          <span style={{ fontSize: 12, color: '#475569', fontFamily: '"DM Mono", monospace' }}>
            Page {page} · {count} records
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}
              style={{ background: '#1a2035', border: '1px solid #1e293b', color: '#94a3b8', borderRadius: 6, padding: '5px 12px', cursor: page === 1 ? 'default' : 'pointer', fontSize: 13, opacity: page === 1 ? 0.4 : 1 }}>←</button>
            <button onClick={() => setPage(p => p+1)} disabled={page * 50 >= count}
              style={{ background: '#1a2035', border: '1px solid #1e293b', color: '#94a3b8', borderRadius: 6, padding: '5px 12px', cursor: page * 50 >= count ? 'default' : 'pointer', fontSize: 13, opacity: page * 50 >= count ? 0.4 : 1 }}>→</button>
          </div>
        </div>
      </Card>

      {/* Detail drawer */}
      {detail && <RecordDetailDrawer record={detail} onClose={() => setDetail(null)} onAction={singleAction} />}
    </div>
  );
}

// =================== UPLOAD ===================
function UploadPage() {
  const { api } = useAuth();
  const [sourceType, setSourceType] = useState('sap_fuel');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const handleUpload = async () => {
    if (!file) { setError('Please select a file'); return; }
    setUploading(true); setError(''); setResult(null);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('source_type', sourceType);
    try {
      const r = await api.post('/upload/', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setResult(r.data);
      setFile(null);
    } catch(e) {
      setError(e.response?.data?.error || 'Upload failed');
    } finally { setUploading(false); }
  };

  const sourceTypes = [
    { id: 'sap_fuel', label: 'SAP Fuel & Procurement', desc: 'ME2N/ME2L tab-separated export (.txt, .csv)', accept: '.csv,.txt,.tsv' },
    { id: 'utility_elec', label: 'Utility Electricity', desc: 'Portal CSV export from EDF, Octopus, etc.', accept: '.csv' },
    { id: 'travel_concur', label: 'Travel – Concur/Navan', desc: 'JSON export from Concur v3 API or Navan', accept: '.json' },
  ];

  return (
    <div style={{ animation: 'fadeIn .3s ease', maxWidth: 640 }}>
      <PageHeader title="Upload Data" subtitle="Ingest emissions data from source systems" />

      <Card style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>Source Type</label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
            {sourceTypes.map(st => (
              <div key={st.id} onClick={() => setSourceType(st.id)}
                style={{
                  padding: '14px', borderRadius: 8, cursor: 'pointer',
                  border: `1px solid ${sourceType === st.id ? '#22d3ee' : '#1e293b'}`,
                  background: sourceType === st.id ? 'rgba(34,211,238,0.06)' : '#111827',
                  transition: 'all .15s',
                }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: sourceType === st.id ? '#22d3ee' : '#e2e8f0', marginBottom: 4 }}>{st.label}</div>
                <div style={{ fontSize: 11, color: '#475569' }}>{st.desc}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>File</label>
          <div
            style={{
              border: `2px dashed ${file ? '#22d3ee' : '#1e293b'}`, borderRadius: 10,
              padding: '32px', textAlign: 'center', cursor: 'pointer',
              background: file ? 'rgba(34,211,238,0.04)' : '#111827',
              transition: 'all .2s',
            }}
            onClick={() => document.getElementById('file-input').click()}
            onDragOver={e => { e.preventDefault(); }}
            onDrop={e => { e.preventDefault(); setFile(e.dataTransfer.files[0]); }}
          >
            {file ? (
              <div>
                <div style={{ fontSize: 14, color: '#22d3ee', marginBottom: 4 }}>{file.name}</div>
                <div style={{ fontSize: 12, color: '#64748b' }}>{(file.size / 1024).toFixed(1)} KB</div>
              </div>
            ) : (
              <div>
                <div style={{ fontSize: 32, marginBottom: 8 }}>↑</div>
                <div style={{ fontSize: 13, color: '#64748b' }}>Drop file here or click to browse</div>
                <div style={{ fontSize: 11, color: '#334155', marginTop: 4 }}>
                  {sourceTypes.find(s => s.id === sourceType)?.accept}
                </div>
              </div>
            )}
          </div>
          <input id="file-input" type="file" style={{ display: 'none' }}
            accept={sourceTypes.find(s => s.id === sourceType)?.accept}
            onChange={e => setFile(e.target.files[0])} />
        </div>

        {error && <div style={{ color: '#f87171', fontSize: 13, marginBottom: 16 }}>{error}</div>}

        <button onClick={handleUpload} disabled={uploading || !file}
          style={{ background: '#22d3ee', color: '#0e1117', border: 'none', borderRadius: 8, padding: '12px 24px', fontSize: 14, fontWeight: 600, cursor: uploading || !file ? 'default' : 'pointer', opacity: uploading || !file ? 0.6 : 1 }}>
          {uploading ? 'Processing…' : 'Upload & Ingest'}
        </button>
      </Card>

      {result && (
        <Card style={{ animation: 'fadeIn .3s ease', borderColor: result.status === 'complete' ? 'rgba(52,211,153,0.3)' : 'rgba(251,191,36,0.3)' }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <div style={{ fontSize: 28 }}>{result.status === 'complete' ? '✓' : result.status === 'partial' ? '⚠' : '✕'}</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 500, color: '#e2e8f0', marginBottom: 8 }}>
                {result.status === 'complete' ? 'Ingestion complete' : result.status === 'partial' ? 'Partial ingestion' : 'Ingestion failed'}
              </div>
              <div style={{ fontSize: 13, color: '#94a3b8', fontFamily: '"DM Mono", monospace' }}>
                {result.row_count_ok} rows OK · {result.row_count_failed} failed · {result.row_count_total} total
              </div>
              {result.processing_notes && (
                <div style={{ marginTop: 10, padding: '10px', background: '#0e1117', borderRadius: 6, fontSize: 12, color: '#64748b', fontFamily: '"DM Mono", monospace', whiteSpace: 'pre-wrap' }}>
                  {result.processing_notes}
                </div>
              )}
              <a href="#records" style={{ display: 'inline-block', marginTop: 12, fontSize: 13, color: '#22d3ee', textDecoration: 'none' }}>View records →</a>
            </div>
          </div>
        </Card>
      )}

      {/* Sample file notes */}
      <Card title="Expected Formats" style={{ marginTop: 24 }}>
        <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.8 }}>
          <strong style={{ color: '#94a3b8' }}>SAP:</strong> Tab-separated ME2N/ME2L export. Expects columns: BLDAT or Belegdatum, WERKS, KOSTL, MENGE, MEINS, MATKL, TXZ01, EBELN. German and English headers both accepted.<br />
          <strong style={{ color: '#94a3b8' }}>Utility:</strong> CSV from portal. Expects: period_start/end (or Bill From/To), consumption_kwh (or kWh/Usage), meter_id, site_name. Estimated reads flagged.<br />
          <strong style={{ color: '#94a3b8' }}>Travel:</strong> JSON array of expense entries. Concur v3 (Items wrapper) or Navan format. Fields: ExpenseTypeName, TransactionDate, origin_iata, destination_iata, nights, distance_km.
        </div>
      </Card>
    </div>
  );
}

// =================== BATCHES ===================
function BatchesPage() {
  const { api } = useAuth();
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/batches/').then(r => setBatches(r.data.results || r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ animation: 'fadeIn .3s ease' }}>
      <PageHeader title="Upload Batches" subtitle="All ingestion runs" />
      {loading ? <PageLoader /> : (
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Source', 'Filename', 'Status', 'OK / Total', 'Uploaded', 'Notes'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#475569', fontWeight: 500, fontSize: 11, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {batches.map(b => (
                <tr key={b.id} style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px' }}><SourceBadge type={b.source_type} /></td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontFamily: '"DM Mono", monospace', fontSize: 11 }}>{b.original_filename}</td>
                  <td style={{ padding: '10px 12px' }}><StatusBadge status={b.status} /></td>
                  <td style={{ padding: '10px 12px', fontFamily: '"DM Mono", monospace', color: '#94a3b8', fontSize: 12 }}>{b.row_count_ok} / {b.row_count_total}</td>
                  <td style={{ padding: '10px 12px', color: '#475569', fontSize: 11, fontFamily: '"DM Mono", monospace' }}>{new Date(b.uploaded_at).toLocaleString()}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.processing_notes || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// =================== AUDIT LOG ===================
function AuditPage() {
  const { api } = useAuth();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/audit-log/').then(r => setLogs(r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ animation: 'fadeIn .3s ease' }}>
      <PageHeader title="Audit Log" subtitle="Append-only record of all state changes" />
      {loading ? <PageLoader /> : (
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Timestamp', 'Action', 'Actor', 'Record', 'Note'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#475569', fontWeight: 500, fontSize: 11, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <tr key={log.id} style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', color: '#475569', fontSize: 11, fontFamily: '"DM Mono", monospace', whiteSpace: 'nowrap' }}>{new Date(log.timestamp).toLocaleString()}</td>
                  <td style={{ padding: '10px 12px' }}><ActionBadge action={log.action} /></td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{log.actor_name}</td>
                  <td style={{ padding: '10px 12px', color: '#475569', fontSize: 11, fontFamily: '"DM Mono", monospace' }}>{String(log.record).slice(0, 8)}…</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{log.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

// =================== DETAIL DRAWER ===================
function RecordDetailDrawer({ record, onClose, onAction }) {
  const [note, setNote] = useState('');
  const [acting, setActing] = useState(false);

  const doAction = async (action) => {
    setActing(true);
    await onAction(record.id, action, note);
    setActing(false);
  };

  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 520, background: '#111827', borderLeft: '1px solid #1e293b', zIndex: 100, overflow: 'auto', boxShadow: '-8px 0 32px rgba(0,0,0,.4)', animation: 'slideIn .2s ease' }}>
      <div style={{ padding: '20px 24px', borderBottom: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 500, color: '#e2e8f0' }}>Record Detail</div>
          <div style={{ fontSize: 11, color: '#475569', fontFamily: '"DM Mono", monospace', marginTop: 2 }}>{record.id}</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: '1px solid #334155', color: '#94a3b8', borderRadius: 6, padding: '5px 10px', cursor: 'pointer', fontSize: 13 }}>✕</button>
      </div>

      <div style={{ padding: '20px 24px' }}>
        {/* Key metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 20 }}>
          <MetricCard label="CO₂e" value={`${parseFloat(record.co2e_kg).toFixed(2)} kg`} />
          <MetricCard label="Scope" value={`Scope ${record.scope}`} />
          <MetricCard label="Status" value={<ReviewBadge status={record.review_status} />} />
        </div>

        {/* Details */}
        <div style={{ marginBottom: 20 }}>
          <SectionLabel>Activity</SectionLabel>
          <DetailRow label="Date" value={record.activity_date} />
          {record.period_start && <DetailRow label="Period" value={`${record.period_start} → ${record.period_end}`} />}
          <DetailRow label="Category" value={CATEGORY_LABELS[record.category] || record.category} />
          <DetailRow label="Facility" value={record.facility_name || '—'} />
          <DetailRow label="Cost Centre" value={record.cost_centre || '—'} />
          <DetailRow label="Supplier" value={record.supplier_name || '—'} />
          <DetailRow label="Description" value={record.description || '—'} />
          <DetailRow label="Reference" value={record.reference_id || '—'} />
        </div>

        <div style={{ marginBottom: 20 }}>
          <SectionLabel>Computation</SectionLabel>
          <DetailRow label="Original" value={`${record.quantity_original} ${record.unit_original}`} />
          <DetailRow label="Normalized" value={`${record.quantity_normalized} ${record.unit_normalized}`} />
          <DetailRow label="Emission Factor" value={`${record.emission_factor} kgCO₂e/${record.unit_normalized}`} />
          <DetailRow label="Factor Source" value={record.emission_factor_source} />
          {record.is_edited && <DetailRow label="Original CO₂e" value={`${record.original_co2e_kg} kg (before edit)`} color="#a78bfa" />}
        </div>

        {/* Flags */}
        {record.flag_reasons?.length > 0 && (
          <div style={{ marginBottom: 20, padding: '12px 14px', background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.2)', borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: '#fbbf24', marginBottom: 8 }}>⚑ Flags</div>
            {record.flag_reasons.map((f, i) => (
              <div key={i} style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>• {f}</div>
            ))}
          </div>
        )}

        {/* Source row */}
        {record.source_row_data && (
          <div style={{ marginBottom: 20 }}>
            <SectionLabel>Raw Source Data (row {record.source_row_data.row_index})</SectionLabel>
            <div style={{ background: '#0e1117', borderRadius: 8, padding: '12px', fontSize: 11, fontFamily: '"DM Mono", monospace', color: '#64748b', maxHeight: 160, overflow: 'auto', lineHeight: 1.8 }}>
              {Object.entries(record.source_row_data.raw_data).filter(([k,v]) => v).map(([k,v]) => (
                <div key={k}><span style={{ color: '#475569' }}>{k}:</span> <span style={{ color: '#94a3b8' }}>{String(v)}</span></div>
              ))}
            </div>
          </div>
        )}

        {/* Audit trail */}
        {record.audit_trail?.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <SectionLabel>Audit Trail</SectionLabel>
            {record.audit_trail.map((log, i) => (
              <div key={i} style={{ display: 'flex', gap: 10, marginBottom: 8 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#334155', marginTop: 6, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>
                    <span style={{ color: '#64748b' }}>{new Date(log.timestamp).toLocaleString()}</span>
                    {' · '}<ActionBadge action={log.action} small />
                    {' · '}{log.actor}
                  </div>
                  {log.note && <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{log.note}</div>}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        {record.review_status !== 'locked' && (
          <div style={{ marginTop: 24, paddingTop: 20, borderTop: '1px solid #1e293b' }}>
            <SectionLabel>Review Action</SectionLabel>
            <textarea
              placeholder="Add a note (optional)…"
              value={note} onChange={e => setNote(e.target.value)}
              style={{ width: '100%', background: '#0e1117', border: '1px solid #334155', borderRadius: 8, padding: '10px 12px', color: '#e2e8f0', fontSize: 13, resize: 'vertical', minHeight: 72, outline: 'none', marginBottom: 12, fontFamily: 'inherit' }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              {record.review_status !== 'approved' && <ActionButton color="#34d399" onClick={() => doAction('approve')} disabled={acting}>✓ Approve</ActionButton>}
              {record.review_status !== 'rejected' && <ActionButton color="#f87171" onClick={() => doAction('reject')} disabled={acting}>✕ Reject</ActionButton>}
              <ActionButton color="#fbbf24" onClick={() => doAction('flag')} disabled={acting}>⚑ Flag</ActionButton>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// =================== SHARED COMPONENTS ===================
const labelStyle = { display: 'block', fontSize: 11, color: '#475569', marginBottom: 8, fontFamily: '"DM Mono", monospace', textTransform: 'uppercase', letterSpacing: 1 };

function PageHeader({ title, subtitle }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, color: '#f1f5f9', marginBottom: 4 }}>{title}</h1>
      <div style={{ fontSize: 13, color: '#475569' }}>{subtitle}</div>
    </div>
  );
}

function Card({ title, children, style }) {
  return (
    <div style={{ background: '#1a2035', border: '1px solid #1e293b', borderRadius: 12, padding: '20px', marginBottom: 0, ...style }}>
      {title && <div style={{ fontSize: 13, fontWeight: 500, color: '#64748b', marginBottom: 16, textTransform: 'uppercase', letterSpacing: 1, fontFamily: '"DM Mono", monospace', fontSize: 11 }}>{title}</div>}
      {children}
    </div>
  );
}

function KpiCard({ label, value, unit, color, badge }) {
  return (
    <div style={{ background: '#1a2035', border: '1px solid #1e293b', borderRadius: 12, padding: '18px 20px' }}>
      <div style={{ fontSize: 11, color: '#475569', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1, fontFamily: '"DM Mono", monospace' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, color, fontFamily: '"DM Mono", monospace', letterSpacing: '-1px' }}>
        {value}
        {unit && <span style={{ fontSize: 13, fontWeight: 400, color: '#475569', marginLeft: 4 }}>{unit}</span>}
      </div>
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      style={{ background: '#1a2035', border: '1px solid #1e293b', borderRadius: 8, padding: '8px 12px', color: '#e2e8f0', fontSize: 13, outline: 'none', cursor: 'pointer' }}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

function ActionButton({ color, onClick, disabled, children }) {
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ background: `${color}18`, border: `1px solid ${color}40`, color, borderRadius: 6, padding: '7px 14px', fontSize: 12, fontWeight: 500, cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.5 : 1, transition: 'all .15s' }}>
      {children}
    </button>
  );
}

function MiniBtn({ color, onClick, children }) {
  return (
    <button onClick={onClick}
      style={{ background: 'transparent', border: `1px solid ${color}40`, color, borderRadius: 4, padding: '3px 7px', fontSize: 11, cursor: 'pointer', transition: 'all .1s' }}
      onMouseEnter={e => e.currentTarget.style.background = `${color}18`}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
      {children}
    </button>
  );
}

function ScopeBadge({ scope }) {
  const colors = { 1: '#f97316', 2: '#22d3ee', 3: '#a78bfa' };
  return <span style={{ background: `${colors[scope]}18`, color: colors[scope], border: `1px solid ${colors[scope]}30`, borderRadius: 4, padding: '2px 7px', fontSize: 11, fontWeight: 500, fontFamily: '"DM Mono", monospace' }}>S{scope}</span>;
}

function ReviewBadge({ status }) {
  const map = {
    pending: ['#fbbf24', 'Pending'],
    flagged: ['#f87171', 'Flagged'],
    approved: ['#34d399', 'Approved'],
    rejected: ['#64748b', 'Rejected'],
    locked: ['#22d3ee', 'Locked'],
  };
  const [color, label] = map[status] || ['#64748b', status];
  return <span style={{ background: `${color}18`, color, border: `1px solid ${color}30`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 500 }}>{label}</span>;
}

function SourceBadge({ type }) {
  const map = {
    sap_fuel: ['#f97316', 'SAP'],
    utility_elec: ['#22d3ee', 'Utility'],
    travel_concur: ['#a78bfa', 'Travel'],
  };
  const [color, label] = map[type] || ['#64748b', type];
  return <span style={{ background: `${color}18`, color, border: `1px solid ${color}30`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 500, fontFamily: '"DM Mono", monospace' }}>{label}</span>;
}

function StatusBadge({ status }) {
  const map = {
    complete: ['#34d399', 'Complete'],
    partial: ['#fbbf24', 'Partial'],
    failed: ['#f87171', 'Failed'],
    processing: ['#22d3ee', 'Processing'],
    pending: ['#64748b', 'Pending'],
  };
  const [color, label] = map[status] || ['#64748b', status];
  return <span style={{ background: `${color}18`, color, border: `1px solid ${color}30`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 500 }}>{label}</span>;
}

function ActionBadge({ action, small }) {
  const map = {
    created: ['#64748b', 'Created'],
    approved: ['#34d399', 'Approved'],
    rejected: ['#f87171', 'Rejected'],
    flagged: ['#fbbf24', 'Flagged'],
    edited: ['#a78bfa', 'Edited'],
    locked: ['#22d3ee', 'Locked'],
  };
  const [color, label] = map[action] || ['#64748b', action];
  if (small) return <span style={{ color, fontSize: 11 }}>{label}</span>;
  return <span style={{ background: `${color}18`, color, border: `1px solid ${color}30`, borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 500 }}>{label}</span>;
}

function PageLoader() {
  return <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
    <div style={{ width: 24, height: 24, border: '2px solid #1e293b', borderTop: '2px solid #22d3ee', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
  </div>;
}

function SectionLabel({ children }) {
  return <div style={{ fontSize: 10, color: '#334155', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1.5, fontFamily: '"DM Mono", monospace', fontWeight: 600 }}>{children}</div>;
}

function DetailRow({ label, value, color }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid #0f172a' }}>
    <span style={{ fontSize: 12, color: '#475569' }}>{label}</span>
    <span style={{ fontSize: 12, color: color || '#94a3b8', fontFamily: '"DM Mono", monospace', maxWidth: 280, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</span>
  </div>;
}

function MetricCard({ label, value }) {
  return <div style={{ background: '#0e1117', borderRadius: 8, padding: '12px', textAlign: 'center' }}>
    <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1, fontFamily: '"DM Mono", monospace' }}>{label}</div>
    <div style={{ fontSize: 14, fontWeight: 500, color: '#e2e8f0' }}>{value}</div>
  </div>;
}

const CATEGORY_LABELS = {
  fuel_diesel: 'Diesel',
  fuel_petrol: 'Petrol',
  fuel_natural_gas: 'Natural Gas',
  fuel_lpg: 'LPG',
  fuel_other: 'Other Fuel',
  electricity: 'Electricity',
  travel_flight: 'Flight',
  travel_rail: 'Rail',
  travel_hotel: 'Hotel',
  travel_taxi: 'Taxi',
  travel_rental_car: 'Rental Car',
  procurement_goods: 'Procurement',
};
