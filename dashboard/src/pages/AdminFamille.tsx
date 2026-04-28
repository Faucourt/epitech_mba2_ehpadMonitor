import { useState, useEffect } from 'react';

const BACKEND_HTTP = `${window.location.protocol}//${window.location.hostname}:8001`;

interface FamilleAccount {
  username: string;
  resident_id: string;
  resident_name?: string;
  created_at?: string;
}

export function AdminFamille() {
  const [token, setToken] = useState(() => localStorage.getItem('ehpad_admin_token') ?? '');
  const [adminInput, setAdminInput] = useState('');
  const [accounts, setAccounts] = useState<FamilleAccount[]>([]);
  const [form, setForm] = useState({ username: '', password: '', resident_id: '' });
  const [status, setStatus] = useState('');
  const [loggedIn, setLoggedIn] = useState(false);

  async function login() {
    const res = await fetch(`${BACKEND_HTTP}/api/admin/famille/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: adminInput }),
    });
    if (res.ok) {
      localStorage.setItem('ehpad_admin_token', adminInput);
      setToken(adminInput);
      setLoggedIn(true);
      loadAccounts(adminInput);
    } else {
      setStatus('Token invalide');
    }
  }

  async function loadAccounts(tk = token) {
    if (!tk) return;
    const res = await fetch(`${BACKEND_HTTP}/api/admin/famille/accounts`, {
      headers: { Authorization: `Bearer ${tk}` },
    });
    if (res.ok) {
      const data = await res.json();
      setAccounts(data.accounts ?? []);
      setLoggedIn(true);
    } else {
      setLoggedIn(false);
    }
  }

  useEffect(() => { if (token) loadAccounts(); }, []);

  async function createAccount() {
    const res = await fetch(`${BACKEND_HTTP}/api/admin/famille/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(form),
    });
    if (res.ok) { setStatus('Compte créé'); setForm({ username: '', password: '', resident_id: '' }); loadAccounts(); }
    else { const e = await res.json(); setStatus(`Erreur: ${e.detail ?? 'inconnue'}`); }
  }

  async function deleteAccount(username: string) {
    if (!confirm(`Supprimer le compte ${username} ?`)) return;
    const res = await fetch(`${BACKEND_HTTP}/api/admin/famille/accounts/${username}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) { setStatus('Compte supprimé'); loadAccounts(); }
  }

  if (!loggedIn) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f1117', color: '#e2e8f0' }}>
        <div style={{ background: '#1a1d2e', border: '1px solid #2d3748', borderRadius: 14, padding: 28, width: 360 }}>
          <h1 style={{ margin: '0 0 16px', fontSize: 20 }}>Admin Famille</h1>
          <input
            value={adminInput} onChange={e => setAdminInput(e.target.value)}
            placeholder="Token admin (ADMIN_EHPAD_2024)"
            type="password"
            style={{ width: '100%', background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: 8, padding: 10, marginBottom: 10, font: 'inherit' }}
          />
          <button onClick={login} style={{ width: '100%', background: '#2563eb', color: '#fff', border: 0, borderRadius: 8, padding: 10, fontWeight: 700, cursor: 'pointer' }}>
            Connexion
          </button>
          {status && <p style={{ color: '#ef4444', marginTop: 8, textAlign: 'center' }}>{status}</p>}
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif', padding: 24 }}>
      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h1 style={{ margin: 0 }}>Gestion comptes famille</h1>
          <a href="/" style={{ background: '#242840', color: '#94a3b8', borderRadius: 8, padding: '7px 14px', textDecoration: 'none', fontSize: 13 }}>← Dashboard</a>
        </div>

        {/* Create form */}
        <div style={{ background: '#1a1d2e', border: '1px solid #2d3748', borderRadius: 12, padding: 20, marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 14 }}>Créer un compte</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 10 }}>
            {[
              { key: 'username', placeholder: 'famille_dupont', label: 'Identifiant' },
              { key: 'password', placeholder: 'MotDePasse123!', label: 'Mot de passe' },
              { key: 'resident_id', placeholder: 'R005', label: 'ID résident' },
            ].map(f => (
              <label key={f.key} style={{ display: 'grid', gap: 4, fontSize: 12, color: '#94a3b8', fontWeight: 700 }}>
                {f.label}
                <input
                  value={form[f.key as keyof typeof form]}
                  onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  style={{ background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: 8, padding: '8px 10px', font: 'inherit' }}
                />
              </label>
            ))}
          </div>
          <button onClick={createAccount} style={{ background: '#059669', color: '#fff', border: 0, borderRadius: 8, padding: '9px 20px', fontWeight: 700, cursor: 'pointer' }}>
            Créer le compte
          </button>
          {status && <span style={{ marginLeft: 12, fontSize: 12, color: status.startsWith('Erreur') ? '#ef4444' : '#10b981' }}>{status}</span>}
        </div>

        {/* Accounts list */}
        <div style={{ background: '#1a1d2e', border: '1px solid #2d3748', borderRadius: 12, padding: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 14 }}>
            Comptes actifs ({accounts.length})
          </div>
          {accounts.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: 13, textAlign: 'center', padding: 20 }}>Aucun compte</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2d3748' }}>
                  {['Identifiant', 'Résident', 'ID', 'Créé le', ''].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: '#64748b', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {accounts.map(acc => (
                  <tr key={acc.username} style={{ borderBottom: '1px solid #1a1d2e' }}>
                    <td style={{ padding: '10px 10px' }}><code style={{ background: '#0f1117', borderRadius: 6, padding: '3px 8px', color: '#60a5fa' }}>{acc.username}</code></td>
                    <td style={{ padding: '10px 10px' }}>{acc.resident_name ?? '—'}</td>
                    <td style={{ padding: '10px 10px', color: '#64748b' }}>{acc.resident_id}</td>
                    <td style={{ padding: '10px 10px', color: '#64748b' }}>{acc.created_at ? new Date(acc.created_at).toLocaleDateString('fr-FR') : '—'}</td>
                    <td style={{ padding: '10px 10px' }}>
                      <button onClick={() => deleteAccount(acc.username)} style={{ background: '#dc2626', color: '#fff', border: 0, borderRadius: 6, padding: '5px 10px', fontWeight: 700, cursor: 'pointer', fontSize: 11 }}>
                        Supprimer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
