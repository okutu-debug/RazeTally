import { useState, useEffect } from 'react'
import { getCandidates, candidatePhotoUrl, partyLogoUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'
import Avatar from '../components/Avatar'

const POSITIONS = [
  { value: '', label: 'All' },
  { value: 'President', label: 'President' },
  { value: 'Member of National Assembly', label: 'MNA' },
  { value: 'Member of County Assembly', label: 'MCA' },
  { value: 'County Governor', label: 'Governor' },
  { value: 'Senator', label: 'Senator' },
  { value: 'County Woman Rep', label: 'CWMNA' },
]

function CandidatePhoto({ candidate }) {
  const [failed, setFailed] = useState(false)
  if (!candidate.photo || failed) return <Avatar name={candidate.name} size={56} />
  return (
    <img
      className="candidate-card-photo"
      src={candidatePhotoUrl(candidate.id)}
      alt={candidate.name}
      onError={() => setFailed(true)}
    />
  )
}

function PartyLogoSmall({ candidate }) {
  const [failed, setFailed] = useState(false)
  if (!candidate.party_id || !candidate.party_logo || failed) return null
  return (
    <img
      className="candidate-card-party-logo"
      src={partyLogoUrl(candidate.party_id)}
      alt=""
      onError={() => setFailed(true)}
    />
  )
}

function Candidates() {
  const [position, setPosition] = useState('')
  const [search, setSearch] = useState('')
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const timeout = setTimeout(() => {
      getCandidates({ position, search })
        .then(setCandidates)
        .catch(err => setError(err.message))
    }, 250)
    return () => clearTimeout(timeout)
  }, [position, search])

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Election results</p>
        <h1>Candidates</h1>
        <p>Candidates standing for election, by office.</p>
      </div>

      <div className="form-type-picker">
        {POSITIONS.map(p => (
          <button
            key={p.value}
            className={p.value === position ? 'active' : ''}
            onClick={() => setPosition(p.value)}
            title={p.label}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Search by name, county, constituency or ward…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {error && <ErrorState title="Could not load candidates" message={error} />}
      {!error && candidates === null && <Loading label="Loading candidates…" />}
      {!error && candidates && candidates.length === 0 && (
        <div className="status-block">
          <p>No candidates found.</p>
        </div>
      )}

      {candidates && candidates.length > 0 && (
        <div className="card-grid">
          {candidates.map(candidate => (
            <div key={candidate.id} className="item-card candidate-card">
              <div className="item-card-body candidate-card-body">
                <div className="candidate-card-photo-wrap">
                  <CandidatePhoto candidate={candidate} />
                  <PartyLogoSmall candidate={candidate} />
                </div>
                <h3>{candidate.name}</h3>
                <p>{candidate.position}</p>
                <div className="item-card-meta">
                  {candidate.party_name && (
                    <span className="rz-badge rz-badge-neutral">{candidate.party_name}</span>
                  )}
                  {(candidate.ward || candidate.constituency || candidate.county) && (
                    <span className="rz-badge rz-badge-neutral">
                      {candidate.ward || candidate.constituency || candidate.county}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default Candidates
