import { useState, useEffect, useCallback } from 'react'
import PartyAvatar from '../components/PartyAvatar'
import { listFormTypes, getTallySummary, getTallyByLocation, getFormLocations, partyLogoUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'
import LiveBadge from '../components/LiveBadge'
import AnimatedNumber from '../components/AnimatedNumber'
import { colorFor } from '../components/Avatar'
import { usePolling } from '../hooks/usePolling'

const POLL_INTERVAL_MS = 15000

// Which geographic level makes sense to filter each office's results by:
// President is national, so break it down by county; governor/senator/woman
// rep are county-wide offices, so break down by constituency; MP already IS
// a constituency race; MCA already IS a ward race, so ward just narrows to one.
const LOCATION_LEVEL = {
  '34a': 'county',
  '35a': 'constituency',
  '36a': 'ward',
  '37a': 'constituency',
  '38a': 'constituency',
  '39a': 'constituency',
}

const LEVEL_KEY = { county: 'counties', constituency: 'constituencies', ward: 'wards' }

const FORM_TYPE_SHORT = {
  '34a': 'President',
  '35a': 'MNA',
  '36a': 'MCA',
  '37a': 'Governor',
  '38a': 'Senator',
  '39a': 'CWMNA',
}

function Results() {
  const [formTypes, setFormTypes] = useState(null)
  const [activeType, setActiveType] = useState(null)
  const [locationCode, setLocationCode] = useState('')
  const [view, setView] = useState('progress') // 'table' | 'progress'
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [locations, setLocations] = useState({ counties: [], constituencies: [], wards: [] })
  const [locationsLoading, setLocationsLoading] = useState(true)

  useEffect(() => {
    listFormTypes()
      .then(types => {
        setFormTypes(types)
        if (types.length > 0) setActiveType(types[0].form_type)
      })
      .catch(err => setError(err.message))
  }, [])

  const level = activeType ? LOCATION_LEVEL[activeType] : null

  // Only offer locations that actually have data for the selected form type,
  // rather than the full national county/constituency/ward reference lists.
  useEffect(() => {
    if (!activeType) return
    setLocationsLoading(true)
    getFormLocations(activeType)
      .then(setLocations)
      .catch(() => setLocations({ counties: [], constituencies: [], wards: [] }))
      .finally(() => setLocationsLoading(false))
  }, [activeType])

  // There's no "All" view — always land on the first available location for
  // the current office once its location list has loaded.
  useEffect(() => {
    if (locationsLoading || !level) return
    const options = locations[LEVEL_KEY[level]] || []
    setLocationCode(options.length > 0 ? options[0].code : '')
  }, [locations, level, locationsLoading])

  const fetchRows = useCallback(() => {
    if (!activeType) return
    const request = locationCode
      ? getTallyByLocation(activeType, {
          countyCode: level === 'county' ? locationCode : undefined,
          constituencyCode: level === 'constituency' ? locationCode : undefined,
          wardCode: level === 'ward' ? locationCode : undefined,
        })
      : getTallySummary(activeType, { top: 20 })

    request
      .then(result => { setRows(result); setLastUpdated(new Date()) })
      .catch(err => setError(err.message))
  }, [activeType, locationCode, level])

  // Manual changes (switching office/location) show a loading state first.
  useEffect(() => {
    if (!activeType) return
    setRows(null)
    setError(null)
    fetchRows()
  }, [activeType, locationCode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Background refresh keeps numbers current without flashing a loading state.
  usePolling(fetchRows, POLL_INTERVAL_MS)

  if (error && !formTypes) return <ErrorState title="Could not load results" message={error} />
  if (!formTypes) return <Loading label="Loading election results…" />

  const activeLabel = formTypes.find(t => t.form_type === activeType)?.label
  const locationOptions = level ? locations[LEVEL_KEY[level]] || [] : []
  const selectedLocationName = locationOptions.find(o => o.code === locationCode)?.name

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Election results</p>
        <h1>Tally Results</h1>
        <p>Live vote counts as forms are captured and verified.</p>
        <LiveBadge lastUpdated={lastUpdated} />
      </div>

      <div className="form-type-picker">
        {formTypes.map(t => (
          <button
            key={t.form_type}
            className={t.form_type === activeType ? 'active' : ''}
            onClick={() => { setActiveType(t.form_type); setLocationCode('') }}
            title={t.label}
          >
            {FORM_TYPE_SHORT[t.form_type] || t.label}
          </button>
        ))}
      </div>

      <div className="rz-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="results-card-header">
          <h3>
            {activeLabel ? `${activeLabel} — Live Tally` : 'Live Tally'}
            {selectedLocationName ? ` (${selectedLocationName})` : ''}
          </h3>
          <div className="results-card-header-controls">
            <div className="view-toggle">
              
              <button className={view === 'progress' ? 'active' : ''} onClick={() => setView('progress')}>
                Progress
              </button>
              <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>
                Table
              </button>
            </div>
            <select
              className="results-filter-input"
              value={locationCode}
              onChange={e => setLocationCode(e.target.value)}
              disabled={locationsLoading || locationOptions.length === 0}
            >
              {locationsLoading && <option value="">Loading…</option>}
              {!locationsLoading && locationOptions.length === 0 && (
                <option value="">No {level} data yet</option>
              )}
              {locationOptions.map(opt => (
                <option key={opt.code} value={opt.code}>{opt.name}</option>
              ))}
            </select>
          </div>
        </div>

        {error && <ErrorState title="Could not load tally" message={error} />}
        {!error && rows === null && <Loading label="Loading tally…" />}
        {!error && rows && rows.length === 0 && (
          <div className="status-block">
            <p>No results captured yet for this selection.</p>
          </div>
        )}

        {rows && rows.length > 0 && view === 'table' && (
          <div style={{ overflowX: 'auto' }}>
            <table className="results-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Candidate</th>
                  <th>Votes</th>
                  <th>Stations Counted</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={`${row.candidate_number}-${i}`}>
                    <td>{row.candidate_number ?? i + 1}</td>
                    <td>{row.candidate_name}</td>
                    <td>
                      <strong>
                        <AnimatedNumber value={Number(row.total_votes || 0)} format={v => v.toLocaleString()} />
                      </strong>
                    </td>
                    <td><AnimatedNumber value={row.stations_counted ?? '—'} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {rows && rows.length > 0 && view === 'progress' && (
          <div className="tally-bars">
            {(() => {
              const totalVotes = rows.reduce((sum, r) => sum + Number(r.total_votes || 0), 0)
              return rows.map((row, i) => {
                const votes = Number(row.total_votes || 0)
                const pct = totalVotes > 0 ? (votes / totalVotes) * 100 : 0
                return (
                  <div className="tally-bar-card" key={`${row.candidate_number}-${i}`}>
                    <PartyAvatar
                      name={row.candidate_name}
                      size={48}
                      logoUrl={row.party_logo ? partyLogoUrl(row.party_id) : null}
                    />
                    <div className="tally-bar-body">
                      <div className="tally-bar-name">{row.candidate_name}</div>
                      {row.party_name && <div className="tally-bar-party">{row.party_name}</div>}
                      <div className="tally-bar-track">
                        <div
                          className="tally-bar-fill"
                          style={{ width: `${pct}%`, background: colorFor(row.candidate_name || '?') }}
                        />
                      </div>
                    </div>
                    <div className="tally-bar-stats">
                      <div className="tally-bar-votes">
                        <AnimatedNumber value={votes} format={v => v.toLocaleString()} />
                      </div>
                      <div className="tally-bar-pct">{pct.toFixed(1)}%</div>
                    </div>
                  </div>
                )
              })
            })()}
          </div>
        )}
      </div>
    </div>
  )
}

export default Results
