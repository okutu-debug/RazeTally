import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getOpinionPoll, voteOpinionPoll, partyLogoUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'
import PartyAvatar from '../components/PartyAvatar'
import { colorFor } from '../components/Avatar'

const votedKey = id => `rz_poll_voted_${id}`

function PollDetail() {
  const { id } = useParams()
  const [poll, setPoll] = useState(null)
  const [error, setError] = useState(null)
  const [hasVoted, setHasVoted] = useState(false)
  const [selectedResultId, setSelectedResultId] = useState(null)
  const [voting, setVoting] = useState(false)
  const [voteError, setVoteError] = useState('')

  useEffect(() => {
    setPoll(null)
    setError(null)
    setSelectedResultId(null)
    setVoteError('')
    setHasVoted(localStorage.getItem(votedKey(id)) === '1')
    getOpinionPoll(id)
      .then(setPoll)
      .catch(err => setError(err.message))
  }, [id])

  if (error) return <ErrorState title="Poll not found" message={error} />
  if (!poll) return <Loading label="Loading poll…" />

  const results = [...(poll.results || [])].sort((a, b) => Number(b.percentage) - Number(a.percentage))
  const isSelfHosted = poll.source === 'self_hosted'
  const canVote = isSelfHosted && !hasVoted

  const handleVote = async () => {
    if (!selectedResultId) return
    setVoting(true)
    setVoteError('')
    try {
      const updated = await voteOpinionPoll(id, selectedResultId)
      setPoll(updated)
      localStorage.setItem(votedKey(id), '1')
      setHasVoted(true)
    } catch (err) {
      if (err.message?.toLowerCase().includes('already voted')) {
        // Cast on a previous visit without (or with cleared) localStorage —
        // the server is the source of truth, so just resync to that state.
        localStorage.setItem(votedKey(id), '1')
        setHasVoted(true)
        getOpinionPoll(id).then(setPoll).catch(() => {})
      } else {
        setVoteError(err.message || 'Could not record your vote. Please try again.')
      }
    } finally {
      setVoting(false)
    }
  }

  return (
    <div className="rz-page form-page">
      <p className="rz-eyebrow">Opinion poll</p>
      <h1>{poll.title}</h1>

      <div className="detail-meta-row">
        {poll.position && <span className="rz-badge rz-badge-neutral">{poll.position}</span>}
        {isSelfHosted ? (
          <span className="rz-badge rz-badge-neutral">🗳 Our own poll — public voting</span>
        ) : (
          poll.pollster && <span className="rz-badge rz-badge-neutral">{poll.pollster}</span>
        )}
        {!isSelfHosted && poll.date_conducted && (
          <span className="rz-badge rz-badge-neutral">Conducted {poll.date_conducted}</span>
        )}
        {!isSelfHosted && poll.sample_size && (
          <span className="rz-badge rz-badge-neutral">Sample size: {poll.sample_size}</span>
        )}
        {!isSelfHosted && poll.margin_of_error != null && (
          <span className="rz-badge rz-badge-neutral">±{poll.margin_of_error}% margin of error</span>
        )}
        {isSelfHosted && (
          <span className="rz-badge rz-badge-neutral">
            {results.reduce((sum, r) => sum + Number(r.vote_count || 0), 0)} vote(s) so far
          </span>
        )}
        {hasVoted && <span className="rz-badge rz-badge-success">✅ You voted</span>}
      </div>

      {canVote && results.length > 0 && (
        <div className="rz-card" style={{ padding: 0, overflow: 'hidden', marginBottom: '1.5rem' }}>
          <div className="poll-vote-options">
            {results.map(row => (
              <button
                key={row.id}
                type="button"
                className={`poll-vote-option${selectedResultId === row.id ? ' selected' : ''}`}
                onClick={() => setSelectedResultId(row.id)}
              >
                <PartyAvatar
                  name={row.candidate_name}
                  size={36}
                  logoUrl={row.party_logo ? partyLogoUrl(row.party_id) : null}
                />
                <span className="poll-vote-option-name">{row.candidate_name}</span>
              </button>
            ))}
          </div>
          {voteError && <div className="status error" style={{ margin: '0 1.5rem 1rem' }}>{voteError}</div>}
          <div className="poll-vote-actions">
            <button
              type="button"
              className="rz-btn rz-btn-primary"
              disabled={!selectedResultId || voting}
              onClick={handleVote}
            >
              {voting ? 'Submitting…' : 'Cast your vote'}
            </button>
          </div>
        </div>
      )}

      {results.length > 0 && (
        <div className="rz-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="tally-bars">
            {results.map((row, i) => (
              <div className="tally-bar-card" key={`${row.candidate_name}-${i}`}>
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
                      style={{ width: `${row.percentage}%`, background: colorFor(row.candidate_name || '?') }}
                    />
                  </div>
                </div>
                <div className="tally-bar-stats">
                  <div className="tally-bar-pct">{Number(row.percentage).toFixed(1)}%</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(poll.methodology || poll.notes || poll.source_url) && (
        <div className="rz-card" style={{ marginTop: '1.5rem' }}>
          {poll.methodology && (
            <>
              <h3>Methodology</h3>
              <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, color: 'var(--rz-text)' }}>{poll.methodology}</p>
            </>
          )}
          {poll.notes && (
            <>
              <h3 style={{ marginTop: poll.methodology ? '1.5rem' : 0 }}>Notes</h3>
              <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, color: 'var(--rz-text)' }}>{poll.notes}</p>
            </>
          )}
          {poll.source_url && (
            <p style={{ marginTop: '1rem' }}>
              <a href={poll.source_url} target="_blank" rel="noopener noreferrer">Source ↗</a>
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default PollDetail
