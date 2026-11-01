import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getJobDescription } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'

function JobDetail() {
  const { id } = useParams()
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setJob(null)
    setError(null)
    getJobDescription(id)
      .then(setJob)
      .catch(err => setError(err.message))
  }, [id])

  if (error) return <ErrorState title="Job not found" message={error} />
  if (!job) return <Loading label="Loading position…" />

  return (
    <div className="rz-page form-page">
      <p className="rz-eyebrow">Open position</p>
      <h1>{job.position}</h1>

      <div className="detail-meta-row">
        {job.application_deadline && (
          <span className="rz-badge rz-badge-neutral">Application deadline: {job.application_deadline}</span>
        )}
        {job.num_applicants_required && (
          <span className="rz-badge rz-badge-neutral">{job.num_applicants_required} needed</span>
        )}
      </div>

      <div className="rz-card">
        <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, color: 'var(--rz-text)' }}>
          {job.description || 'No further details provided.'}
        </p>

        {job.attachment_requirements?.length > 0 && (
          <>
            <h3 style={{ marginTop: '1.5rem' }}>Required documents</h3>
            <ul>
              {job.attachment_requirements.map(req => (
                <li key={req}>{req}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div style={{ marginTop: '1.5rem' }}>
        <Link to={`/apply?position=${encodeURIComponent(job.position)}`} className="rz-btn rz-btn-primary">
          Apply for this role
        </Link>
      </div>
    </div>
  )
}

export default JobDetail
