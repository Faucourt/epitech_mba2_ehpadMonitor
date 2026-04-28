import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

interface Activity {
  id: string;
  nom: string;
  description: string;
  image: string;
  emoji: string;
  residents: string[];
}

const ACTIVITIES: Activity[] = [
  { id: 'theatre', nom: 'Théâtre', description: 'Atelier théâtre et expression corporelle', image: '/activites/01_theatre_scene.png', emoji: '🎭', residents: ['Marie Curie', 'Louis Pasteur', 'Joséphine Baker', 'Jean Gabin', 'Line Renaud', 'Fernandel'] },
  { id: 'dominos', nom: 'Dominos', description: 'Jeux de table en petit groupe', image: '/activites/02_dominos_scene.png', emoji: '🁣', residents: ['Fernandel', 'Brigitte Bardot', 'Jean-Paul Belmondo', 'Mireille Mathieu', 'Claude Brasseur'] },
  { id: 'loto', nom: 'Loto', description: "Loto de l'après-midi en salle commune", image: '/activites/03_loto_scene.png', emoji: '🎰', residents: ['Brigitte Bardot', 'Henri Salvador', 'Line Renaud', 'Bourvil', 'Roger Leblanc', 'Germaine Fontaine'] },
  { id: 'dessin', nom: 'Dessin', description: 'Atelier dessin et couleurs.', image: '/activites/04_dessin_scene.png', emoji: '🎨', residents: ['Marie Curie', 'Fernandel', 'Brigitte Bardot', 'Mireille Mathieu', 'Jean-Paul Belmondo'] },
  { id: 'jardin', nom: 'Jardin', description: 'Promenade accompagnée au jardin thérapeutique.', image: '/activites/05_jardin_scene.png', emoji: '🌿', residents: ['Jeanne Moreau', 'Yves Montand', 'Henri Salvador', 'Alain Delon', 'Line Renaud', 'Joséphine Baker'] },
  { id: 'chorale', nom: 'Chorale', description: 'Chants en chœur pour le plaisir de tous.', image: '/activites/06_chorale_scene.png', emoji: '🎵', residents: ['Jean Gabin', 'Louis Pasteur', 'Brigitte Bardot', 'Joséphine Baker', 'Claude François', 'Sophie Marceau'] },
];

function normalise(s: string) {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

function residentMatch(name: string, filter: string): boolean {
  if (!filter) return false;
  return normalise(name).includes(normalise(filter)) || normalise(filter).includes(normalise(name.split(' ')[0]));
}

export function AlbumActivites() {
  const [params] = useSearchParams();
  const filterResident = params.get('resident') ?? '';
  const [imgErrors, setImgErrors] = useState<Set<string>>(new Set());

  return (
    <div style={{ fontFamily: 'Georgia, serif', background: '#f5f0e8', color: '#2c2416', minHeight: '100vh' }}>
      <header style={{ background: '#fff', borderBottom: '2px solid #d4af6a', padding: '22px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: '1.45rem', fontWeight: 700, color: '#2c2416' }}>
          <span style={{ fontSize: '1.3rem', color: '#b8870b' }}>✦</span>
          Résidence <span style={{ color: '#b8870b', marginLeft: 4, marginRight: 4 }}>EpiD'or</span> — Album des Activités
          <span style={{ fontSize: '1.3rem', color: '#b8870b' }}>✦</span>
        </div>
        <button onClick={() => history.back()} style={{ fontFamily: 'Segoe UI, sans-serif', fontSize: '.85rem', padding: '7px 14px', background: '#f0e8d5', border: '1px solid #d4af6a', borderRadius: 8, color: '#7a5c1e', fontWeight: 600, cursor: 'pointer' }}>
          ← Retour
        </button>
      </header>

      {filterResident && (
        <div style={{ background: '#fff8e8', borderBottom: '1px solid #e8d5a0', padding: '10px 32px', fontFamily: 'Segoe UI, sans-serif', fontSize: '.88rem', color: '#7a5c1e', display: 'flex', alignItems: 'center', gap: 10 }}>
          Activités de{' '}
          <span style={{ background: '#b8870b', color: '#fff', borderRadius: 999, padding: '3px 12px', fontWeight: 700, fontSize: '.85rem' }}>
            {filterResident}
          </span>
          <span style={{ color: '#a08050' }}>— Les activités où votre proche participe sont mises en avant</span>
        </div>
      )}

      <main style={{ maxWidth: 1200, margin: '0 auto', padding: '36px 24px 60px' }}>
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <h2 style={{ fontSize: '1rem', color: '#7a5c1e', fontWeight: 400, fontStyle: 'italic' }}>
            La vie sociale et culturelle de notre résidence, semaine après semaine.
          </h2>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 28 }}>
          {ACTIVITIES.map(act => {
            const participates = filterResident && act.residents.some(r => residentMatch(r, filterResident));
            const imgFailed = imgErrors.has(act.id);

            return (
              <div
                key={act.id}
                style={{
                  background: '#fff',
                  borderRadius: 14,
                  overflow: 'hidden',
                  boxShadow: '0 6px 28px rgba(44,36,22,.10)',
                  border: participates ? '2px solid #b8870b' : '1px solid #e4d5b8',
                  transition: 'transform .2s, box-shadow .2s',
                } as React.CSSProperties}
              >
                {imgFailed ? (
                  <div style={{ width: '100%', aspectRatio: '16/10', background: 'linear-gradient(135deg, #f0e8d5, #e4d5b8)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#b8a080', fontSize: '2.5rem' }}>
                    {act.emoji}
                  </div>
                ) : (
                  <img
                    src={act.image}
                    alt={act.nom}
                    onError={() => setImgErrors(prev => new Set([...prev, act.id]))}
                    style={{ width: '100%', aspectRatio: '16/10', objectFit: 'cover', display: 'block' }}
                  />
                )}
                <div style={{ padding: '16px 18px 18px' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#2c2416', marginBottom: 4 }}>
                    {act.nom}
                    {participates && (
                      <span style={{ display: 'inline', fontFamily: 'Segoe UI, sans-serif', fontSize: '.75rem', fontWeight: 700, background: '#b8870b', color: '#fff', borderRadius: 999, padding: '2px 10px', marginLeft: 8 }}>
                        Participe ✓
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '.85rem', color: '#7a6848', fontStyle: 'italic', marginBottom: 10, lineHeight: 1.4 }}>
                    {act.description}
                  </div>
                  <div style={{ height: 1, background: 'linear-gradient(90deg, transparent, #d4af6a, transparent)', margin: '10px 0' }} />
                  <div style={{ fontFamily: 'Segoe UI, sans-serif', fontSize: '.75rem', fontWeight: 700, color: '#b8870b', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>
                    Participants
                  </div>
                  <div style={{ fontFamily: 'Segoe UI, sans-serif', fontSize: '.82rem', color: '#5a4a2e', lineHeight: 1.55 }}>
                    {act.residents.map((r, i) => (
                      <span key={r}>
                        {i > 0 && ', '}
                        {residentMatch(r, filterResident) ? (
                          <span style={{ fontWeight: 700, color: '#b8870b', background: '#fff8e0', borderRadius: 4, padding: '0 3px' }}>{r}</span>
                        ) : r}
                      </span>
                    ))}
                    …
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}
