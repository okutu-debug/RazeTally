import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { listOpinionPolls } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'

const POSITIONS = [
  { value: '', label: 'All' },
  { value: 'President', label: 'President' },
  { value: 'Member of National Assembly', label: 'MNA' },
  { value: 'Member of County Assembly', label: 'MCA' },
  { value: 'County Governor', label: 'Governor' },
  { value: 'Senator', label: 'Senator' },
  { value: 'County Woman Rep', label: 'CWMNA' },
]

function Polls() {
  const [position, setPosition] = useState('')
  const [search, setSearch] = useState('')
  const [polls, setPolls] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const timeout = setTimeout(() => {
      listOpinionPolls({ search, position })
        .then(result => setPolls(result.items))
        .catch(err => setError(err.message))
    }, 250)
    return () => clearTimeout(timeout)
  }, [search, position])

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Opinion polls</p>
        <h1>Opinion Polls</h1>
        <p>Independent pollster-reported standings, by office.</p>
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
          placeholder="Search by poll title or pollster…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {error && <ErrorState title="Could not load opinion polls" message={error} />}
      {!error && polls === null && <Loading label="Loading opinion polls…" />}
      {!error && polls && polls.length === 0 && (
        <div className="status-block">
          <p>No opinion polls published yet.</p>
        </div>
      )}

      {polls && polls.length > 0 && (
        <div className="card-grid">
          {polls.map(poll => (
            <Link key={poll.id} to={`/polls/${poll.id}`} className="item-card">
              <div className="item-card-body">
                <h3>{poll.title}</h3>
                {poll.source === 'self_hosted' ? <p>Our own poll — public voting</p> : poll.pollster && <p>{poll.pollster}</p>}
                <div className="item-card-meta">
                  {poll.position && <span className="rz-badge rz-badge-neutral">{poll.position}</span>}
                  {poll.source === 'self_hosted' ? (
                    <span className="rz-badge rz-badge-success">🗳 Vote now</span>
                  ) : (
                    <>
                      {poll.date_conducted && <span className="rz-badge rz-badge-neutral">{poll.date_conducted}</span>}
                      {poll.sample_size && <span className="rz-badge rz-badge-neutral">n={poll.sample_size}</span>}
                    </>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export default Polls
