import { useState, useCallback, useEffect } from 'react'
import { getDashboardSummary } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'
import LiveBadge from '../components/LiveBadge'
import AnimatedNumber from '../components/AnimatedNumber'
import { usePolling } from '../hooks/usePolling'

const POLL_INTERVAL_MS = 15000

function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const load = useCallback(() => {
    getDashboardSummary()
      .then(result => {
        setData(result)
        setLoading(false)
        setLastUpdated(new Date())
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  useEffect(() => { load() }, [load])
  usePolling(load, POLL_INTERVAL_MS)

  if (loading) return <Loading label="Loading dashboard…" />
  if (error || !data) {
    return (
      <ErrorState
        title="Could not connect to backend"
        message={error || 'Make sure the API server is running.'}
      />
    )
  }

  const completionRate = data.total_registered
    ? Math.round((data.total_valid_votes / data.total_registered) * 100)
    : 0

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Live overview</p>
        <h1>Election Dashboard</h1>
        <p>Tallying results, trusting democracy — a real-time view of everything counted so far.</p>
        <LiveBadge lastUpdated={lastUpdated} />
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <h3>Total Forms</h3>
          <div className="stat-value"><AnimatedNumber value={data.total_forms} /></div>
          <p className="stat-label">Submitted</p>
        </div>

        <div className="stat-card">
          <h3>Form Types</h3>
          <div className="stat-value">
            <AnimatedNumber value={data.form_types} /> / {data.form_types_total}
          </div>
          <p className="stat-label">Active Types</p>
        </div>

        <div className="stat-card">
          <h3>Valid Votes</h3>
          <div className="stat-value">
            <AnimatedNumber value={data.total_valid_votes} format={v => v.toLocaleString()} />
          </div>
          <p className="stat-label">Accepted</p>
        </div>

        <div className="stat-card">
          <h3>Registered Voters</h3>
          <div className="stat-value">
            <AnimatedNumber value={data.total_registered} format={v => v.toLocaleString()} />
          </div>
          <p className="stat-label">Total</p>
        </div>

        <div className="stat-card">
          <h3>Rejected</h3>
          <div className="stat-value red"><AnimatedNumber value={data.total_rejected} /></div>
          <p className="stat-label">Invalid Forms</p>
        </div>

        <div className="stat-card highlight">
          <h3>Completion Rate</h3>
          <div className="stat-value"><AnimatedNumber value={completionRate} format={v => `${v}%`} /></div>
          <p className="stat-label">Valid Votes / Registered</p>
        </div>
      </div>

      <div className="details">
        <h2>Summary</h2>
        <p>
          Out of <strong>{data.total_registered.toLocaleString()}</strong> registered voters,{' '}
          <strong>{data.total_valid_votes.toLocaleString()}</strong> valid votes were recorded
          across <strong>{data.total_forms}</strong> forms.
        </p>
      </div>
    </div>
  )
}

export default Dashboard
