import { useState, useEffect } from 'react'
import { getParties, partyLogoUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'
import { colorFor } from '../components/Avatar'

function PartyLogo({ party }) {
  const [failed, setFailed] = useState(false)
  if (!party.logo || failed) {
    return (
      <div
        className="party-card-logo party-card-logo-placeholder"
        style={{ background: colorFor(party.name || '?') }}
      >
        {(party.name || '?').slice(0, 2).toUpperCase()}
      </div>
    )
  }
  return (
    <img
      className="party-card-logo"
      src={partyLogoUrl(party.id)}
      alt={party.name}
      onError={() => setFailed(true)}
    />
  )
}

function Parties() {
  const [parties, setParties] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getParties()
      .then(setParties)
      .catch(err => setError(err.message))
  }, [])

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Election results</p>
        <h1>Parties</h1>
        <p>Political parties fielding candidates in this election.</p>
      </div>

      {error && <ErrorState title="Could not load parties" message={error} />}
      {!error && parties === null && <Loading label="Loading parties…" />}
      {!error && parties && parties.length === 0 && (
        <div className="status-block">
          <p>No parties have been added yet.</p>
        </div>
      )}

      {parties && parties.length > 0 && (
        <div className="card-grid">
          {parties.map(party => (
            <div key={party.id} className="item-card party-card">
              <div className="item-card-body party-card-body">
                <PartyLogo party={party} />
                <h3>{party.name}</h3>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default Parties
