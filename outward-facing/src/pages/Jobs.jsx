import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { listJobDescriptions } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'

function Jobs() {
  const [items, setItems] = useState(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    const timeout = setTimeout(() => {
      listJobDescriptions({ search })
        .then(result => setItems(result.items))
        .catch(err => setError(err.message))
    }, 250)
    return () => clearTimeout(timeout)
  }, [search])

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Recruitment</p>
        <h1>Open Positions</h1>
        <p>Join the team on the ground — browse current openings and apply directly.</p>
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Search by position…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {error && <ErrorState title="Could not load job listings" message={error} />}
      {!error && items === null && <Loading label="Loading positions…" />}
      {!error && items && items.length === 0 && (
        <div className="status-block">
          <p>No open positions right now — check back soon.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <div className="card-grid">
          {items.map(job => (
            <Link key={job.id} to={`/jobs/${job.id}`} className="item-card">
              <div className="item-card-body">
                <h3>{job.position}</h3>
                <p>{(job.description || '').slice(0, 140)}{job.description?.length > 140 ? '…' : ''}</p>
                <div className="item-card-meta">
                  {job.application_deadline && (
                    <span className="rz-badge rz-badge-neutral">Closes {job.application_deadline}</span>
                  )}
                  <span className="rz-badge rz-badge-success">Hiring</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export default Jobs
