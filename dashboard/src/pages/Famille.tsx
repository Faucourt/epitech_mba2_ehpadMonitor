import { useState } from 'react';

const BACKEND_HTTP = `${window.location.protocol}//${window.location.hostname}:8001`;

const DEMO_ACCOUNTS = [
  { username: 'famille_curie', password: 'Famille2024!', resident: 'Marie Curie' },
  { username: 'famille_pasteur', password: 'Famille2024!', resident: 'Louis Pasteur' },
  { username: 'famille_gabin', password: 'Famille2024!', resident: 'Jean Gabin' },
];

interface ResidentData {
  id: string; name: string; room: string; age?: number;
  admission_date?: string; referring_physician?: string;
  emergency_contacts?: Array<{ name: string; relation: string; phone: string }>;
  pathologies?: string[];
  week_schedule?: Array<{ day: string; activities: string }>;
  general_status?: string; last_seen?: string;
}

type Tab = 'infos' | 'agenda' | 'photos' | 'contacts' | 'vie_privee';

export function Famille() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [token, setToken] = useState('');
  const [resident, setResident] = useState<ResidentData | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('infos');

  async function login() {
    setError('');
    try {
      const res = await fetch(`${BACKEND_HTTP}/api/famille/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) throw new Error('Identifiants incorrects');
      const data = await res.json();
      setToken(data.token);
      // load resident data
      const rRes = await fetch(`${BACKEND_HTTP}/api/famille/resident`, {
        headers: { Authorization: `Bearer ${data.token}` },
      });
      if (rRes.ok) setResident(await rRes.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
    }
  }

  function logout() { setToken(''); setResident(null); }

  const statusClass = resident?.general_status === 'surveillance' ? 'surveillance' : resident?.general_status === 'renforce' ? 'renforce' : '';

  // Login screen
  if (!token || !resident) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: '#edf3f7', fontFamily: 'Segoe UI, sans-serif' }}>
        <div style={{ width: '100%', maxWidth: 410, background: '#fff', borderRadius: 16, padding: 34, boxShadow: '0 18px 45px rgba(31,45,61,.14)', display: 'grid', gap: 16 }}>
          <h1 style={{ textAlign: 'center', color: '#1a5276', fontSize: '1.45rem', margin: 0 }}>Espace Famille</h1>
          <p style={{ textAlign: 'center', color: '#64748b', lineHeight: 1.5, fontSize: '.92rem', margin: 0 }}>Accédez aux informations de votre proche en toute confidentialité.</p>

          {['Identifiant', 'Mot de passe'].map((label, i) => (
            <label key={label} style={{ display: 'grid', gap: 6, color: '#475569', fontSize: '.85rem', fontWeight: 700 }}>
              {label}
              <input
                type={i === 1 ? 'password' : 'text'}
                value={i === 0 ? username : password}
                onChange={e => i === 0 ? setUsername(e.target.value) : setPassword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && login()}
                style={{ border: '1px solid #d7e1ec', borderRadius: 9, padding: '12px 13px', font: 'inherit', width: '100%' }}
              />
            </label>
          ))}

          <div style={{ border: '1px solid #d7e1ec', background: '#f8fafc', borderRadius: 12, padding: 12, display: 'grid', gap: 8, fontSize: '.8rem' }}>
            <b style={{ color: '#1a5276' }}>Comptes démo</b>
            <div style={{ display: 'grid', gap: 6 }}>
              {DEMO_ACCOUNTS.map(a => (
                <div key={a.username} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 6, alignItems: 'center', color: '#64748b' }}>
                  <code style={{ background: '#fff', border: '1px solid #d7e1ec', color: '#1a5276', borderRadius: 8, padding: '7px 8px', fontFamily: 'Consolas, monospace', fontSize: '.75rem' }}>{a.username}</code>
                  <code style={{ background: '#fff', border: '1px solid #d7e1ec', color: '#1a5276', borderRadius: 8, padding: '7px 8px', fontFamily: 'Consolas, monospace', fontSize: '.75rem' }}>{a.password}</code>
                  <button onClick={() => { setUsername(a.username); setPassword(a.password); }} style={{ background: '#eaf4fb', color: '#1a5276', border: '1px solid #bdd8e8', borderRadius: 8, padding: '7px 9px', fontWeight: 700, cursor: 'pointer', fontSize: '.75rem', whiteSpace: 'nowrap' }}>
                    Remplir
                  </button>
                </div>
              ))}
            </div>
          </div>

          <button onClick={login} style={{ background: '#1a5276', color: '#fff', border: 0, borderRadius: 9, padding: '10px 14px', fontWeight: 800, cursor: 'pointer', fontSize: 14 }}>
            Connexion
          </button>
          {error && <p style={{ color: '#dc2626', textAlign: 'center', fontSize: '.85rem', margin: 0 }}>{error}</p>}
        </div>
      </div>
    );
  }

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: 'infos', label: '📋 Infos' },
    { id: 'agenda', label: '📅 Agenda' },
    { id: 'photos', label: '📷 Photos' },
    { id: 'contacts', label: '👨‍👩‍👧 Contacts' },
    { id: 'vie_privee', label: '🔒 Vie privée' },
  ];

  return (
    <div style={{ minHeight: '100vh', fontFamily: 'Segoe UI, sans-serif', background: '#edf3f7', color: '#1d2a38', display: 'flex', flexDirection: 'column' }}>
      <header style={{ background: '#1a5276', color: '#fff', padding: '14px 22px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ margin: 0, fontSize: '1.1rem' }}>EPicare Palace — Espace Famille</h1>
        <button onClick={logout} style={{ background: 'rgba(255,255,255,.16)', color: '#fff', border: 0, borderRadius: 9, padding: '7px 12px', cursor: 'pointer', fontSize: '.82rem', fontWeight: 600 }}>Déconnexion</button>
      </header>

      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: '30px 18px' }}>
        <div style={{ width: '100%', maxWidth: 1060 }}>
          <div style={{ background: '#fdf8ed', border: `1px solid ${statusClass === 'renforce' ? '#eaa19b' : statusClass === 'surveillance' ? '#edc970' : '#e4d7c4'}`, borderRadius: 20, boxShadow: '0 26px 70px rgba(51,63,79,.18)' }}>
            {/* Cover */}
            <div style={{ padding: '24px 28px 18px', borderBottom: '1px solid #eadfcd', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{ width: 74, height: 74, borderRadius: 16, background: '#e8eef6', border: '1px solid #d7e1ec', display: 'grid', placeItems: 'center', color: '#1a5276', fontWeight: 900, fontSize: '1.2rem', flexShrink: 0 }}>
                  {resident.name.split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <div style={{ fontSize: '1.45rem', fontWeight: 800, color: '#182536' }}>{resident.name}</div>
                  <div style={{ marginTop: 4, color: '#6b7280', fontSize: '.9rem' }}>Chambre {resident.room} · {resident.age ? `${resident.age} ans` : ''}</div>
                </div>
              </div>
              <span style={{
                whiteSpace: 'nowrap', borderRadius: 999, padding: '7px 13px',
                background: statusClass === 'renforce' ? '#fff1f1' : statusClass === 'surveillance' ? '#fff7db' : '#eafaf1',
                color: statusClass === 'renforce' ? '#cf2e2e' : statusClass === 'surveillance' ? '#b46a00' : '#18864b',
                fontSize: '.82rem', fontWeight: 900,
              }}>
                {statusClass === 'renforce' ? 'Suivi renforcé' : statusClass === 'surveillance' ? 'Sous surveillance' : 'Bien portant'}
              </span>
            </div>

            {/* Tabs */}
            <div style={{ display: 'flex', gap: 8, padding: '0 28px', transform: 'translateY(-1px)', flexWrap: 'wrap' }}>
              {TABS.map(t => (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  style={{
                    borderRadius: '0 0 11px 11px', minWidth: 108, padding: '10px 13px 12px',
                    fontSize: '.86rem', border: 0, cursor: 'pointer',
                    background: activeTab === t.id ? '#1a5276' : '#d9e8f0',
                    color: activeTab === t.id ? '#fff' : '#1a5276',
                    fontWeight: 600,
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Pages */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', minHeight: 470 }}>
              <div style={{ padding: 28, background: 'linear-gradient(90deg, #fffdf8, #fbf4e9)' }}>
                {activeTab === 'infos' && (
                  <>
                    <h2 style={{ color: '#1a5276', fontSize: '1.08rem', marginBottom: 14 }}>Informations générales</h2>
                    <div style={{ display: 'grid', gap: 9 }}>
                      {[
                        { icon: '🏥', text: `Admission: ${resident.admission_date ?? 'N/A'}` },
                        { icon: '👨‍⚕️', text: `Médecin: ${resident.referring_physician ?? 'N/A'}` },
                        { icon: '🎂', text: `Âge: ${resident.age ?? 'N/A'} ans` },
                      ].map((item, i) => (
                        <div key={i} style={{ background: '#f8fafc', border: '1px solid #e5edf5', borderRadius: 10, padding: '11px 12px', fontSize: '.9rem', lineHeight: 1.45, display: 'flex', gap: 10, alignItems: 'center' }}>
                          <span style={{ width: 24, textAlign: 'center', color: '#1a5276', fontWeight: 900 }}>{item.icon}</span>
                          {item.text}
                        </div>
                      ))}
                      {(resident.pathologies ?? []).length > 0 && (
                        <div style={{ background: '#f8fafc', border: '1px solid #e5edf5', borderRadius: 10, padding: '11px 12px' }}>
                          <div style={{ fontWeight: 700, color: '#1a5276', marginBottom: 8 }}>Antécédents suivis</div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                            {resident.pathologies!.map(p => (
                              <span key={p} style={{ background: '#eaf4fb', color: '#1a5276', borderRadius: 999, padding: '6px 10px', fontSize: '.82rem', fontWeight: 800 }}>{p}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}

                {activeTab === 'agenda' && (
                  <>
                    <h2 style={{ color: '#1a5276', fontSize: '1.08rem', marginBottom: 14 }}>Programme de la semaine</h2>
                    <div style={{ display: 'grid', gap: 9 }}>
                      {(resident.week_schedule ?? [{ day: 'Lundi', activities: 'Théâtre' }, { day: 'Mercredi', activities: 'Jardin' }, { day: 'Vendredi', activities: 'Chorale' }]).map((d, i) => (
                        <div key={i} style={{ background: '#f8fafc', border: '1px solid #e5edf5', borderRadius: 10, padding: '11px 12px', display: 'grid', gridTemplateColumns: '86px 1fr', gap: 8, fontSize: '.9rem' }}>
                          <strong style={{ display: 'block', color: '#1a5276', marginBottom: 4 }}>{d.day}</strong>
                          <span>{d.activities}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {activeTab === 'photos' && (
                  <>
                    <h2 style={{ color: '#1a5276', fontSize: '1.08rem', marginBottom: 14 }}>Photos des activités</h2>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                      {[
                        { src: '/activites/01_theatre_scene.png', label: 'Théâtre', fallback: '🎭' },
                        { src: '/activites/02_dominos_scene.png', label: 'Dominos', fallback: '🁣' },
                        { src: '/activites/05_jardin_scene.png', label: 'Jardin', fallback: '🌿' },
                        { src: '/activites/06_chorale_scene.png', label: 'Chorale', fallback: '🎵' },
                      ].map((photo, i) => (
                        <PhotoCard key={i} {...photo} angle={i % 2 === 0 ? -1 : 1} />
                      ))}
                    </div>
                    <a
                      href={`/album-activites?resident=${encodeURIComponent(resident.name)}`}
                      style={{ display: 'block', marginTop: 16, textAlign: 'center', background: '#b8870b', color: '#fff', borderRadius: 10, padding: '10px 16px', fontWeight: 700, textDecoration: 'none', fontFamily: 'Georgia, serif' }}
                    >
                      Voir l'album complet ✦
                    </a>
                  </>
                )}

                {activeTab === 'contacts' && (
                  <>
                    <h2 style={{ color: '#1a5276', fontSize: '1.08rem', marginBottom: 14 }}>Contacts familiaux</h2>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
                      {(resident.emergency_contacts ?? []).map((c, i) => (
                        <div key={i} style={{ background: '#f8fafc', border: '1px solid #e5edf5', borderRadius: 10, padding: '11px 12px' }}>
                          <b style={{ display: 'block', color: '#1a5276', marginBottom: 4 }}>{c.name}</b>
                          <div style={{ fontSize: '.9rem', lineHeight: 1.45 }}>{c.relation} · {c.phone}</div>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {activeTab === 'vie_privee' && (
                  <>
                    <h2 style={{ color: '#1a5276', fontSize: '1.08rem', marginBottom: 14 }}>Vie privée & RGPD</h2>
                    <div style={{ background: '#eaf4fb', borderLeft: '3px solid #1a5276', borderRadius: 9, padding: '12px 15px', color: '#4b5563', fontSize: '.82rem', lineHeight: 1.5 }}>
                      Les données affichées ici sont strictement limitées aux informations de bien-être général. Aucune donnée médicale précise n'est transmise dans cet espace.
                    </div>
                    <div style={{ marginTop: 12, padding: '11px 12px', border: '1px solid #d7e1ec', background: '#f8fafc', borderRadius: 10, color: '#4b5563', fontSize: '.82rem', lineHeight: 1.45 }}>
                      <b style={{ color: '#1a5276', display: 'block', marginBottom: 4 }}>Données collectées</b>
                      Présence, activités, bien-être général. Conformément au RGPD, vous disposez d'un droit d'accès, de rectification et d'effacement.
                    </div>
                  </>
                )}
              </div>

              <div style={{ padding: 28, background: 'linear-gradient(90deg, #fbf4e9, #fffdf8)' }}>
                <div style={{ color: '#8a8f98', fontSize: '.76rem', textAlign: 'right', marginBottom: 12 }}>
                  Dernière mise à jour: {resident.last_seen ?? new Date().toLocaleDateString('fr-FR')}
                </div>
                <div style={{ padding: '12px 15px', background: '#eaf4fb', borderLeft: '3px solid #1a5276', borderRadius: 9, color: '#4b5563', fontSize: '.82rem', lineHeight: 1.5 }}>
                  Seules les informations générales de bien-être sont partagées ici. Pour toute question médicale, contactez directement l'équipe soignante.
                </div>
                <div style={{ marginTop: 12, textAlign: 'center', color: '#94a3b8', fontSize: '.78rem' }}>
                  Données actualisées toutes les 5 minutes
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PhotoCard({ src, label, fallback, angle }: { src: string; label: string; fallback: string; angle: number }) {
  const [failed, setFailed] = useState(false);
  return (
    <div style={{ background: '#fff', border: '1px solid #eadfcd', borderRadius: 10, padding: 8, boxShadow: '0 6px 18px rgba(62,51,38,.10)', transform: `rotate(${angle}deg)` }}>
      {failed ? (
        <div style={{ height: 120, borderRadius: 8, background: 'linear-gradient(135deg, #1a5276, #2980b9)', display: 'grid', placeItems: 'center', color: '#fff', fontSize: '2rem' }}>{fallback}</div>
      ) : (
        <img src={src} alt={label} onError={() => setFailed(true)} style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 8, display: 'block' }} />
      )}
      <p style={{ marginTop: 8, color: '#334155', fontSize: '.82rem', lineHeight: 1.35 }}>{label}</p>
    </div>
  );
}
