import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getCampaignRoute, getCampaignRouteMedia, campaignRouteBannerUrl, campaignMediaUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'

function EventDetail() {
  const { id } = useParams()
  const [route, setRoute] = useState(null)
  const [media, setMedia] = useState([])
  const [error, setError] = useState(null)
  const [bannerFailed, setBannerFailed] = useState(false)

  useEffect(() => {
    setRoute(null)
    setError(null)
    setBannerFailed(false)
    getCampaignRoute(id)
      .then(setRoute)
      .catch(err => setError(err.message))
    getCampaignRouteMedia(id)
      .then(result => setMedia(result.items || []))
      .catch(() => setMedia([]))
  }, [id])

  if (error) return <ErrorState title="Campaign route not found" message={error} />
  if (!route) return <Loading label="Loading campaign route…" />

  const location = [route.ward, route.constituency, route.county].filter(Boolean).join(', ')

  return (
    <div className="rz-page form-page">
      <p className="rz-eyebrow">{route.campaign || 'Campaign route'}</p>
      <h1>{route.name}</h1>

      {!bannerFailed && (
        <img
          className="detail-banner"
          src={campaignRouteBannerUrl(route.id)}
          alt={route.name}
          onError={() => setBannerFailed(true)}
        />
      )}

      <div className="detail-meta-row">
        {route.status && <span className="rz-badge rz-badge-neutral">{route.status}</span>}
        {route.date_from && (
          <span className="rz-badge rz-badge-success">
            {route.date_from}{route.date_to ? ` – ${route.date_to}` : ''}
          </span>
        )}
        {location && <span className="rz-badge rz-badge-neutral">{location}</span>}
      </div>

      <div className="rz-card">
        <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, color: 'var(--rz-text)' }}>
          {route.description || route.address || 'No further details provided.'}
        </p>

        {media.length > 0 && (
          <>
            <h3 style={{ marginTop: '1.5rem' }}>Photos</h3>
            <div className="gallery-grid">
              {media.map(item => (
                <img key={item.id} src={campaignMediaUrl(item.id)} alt={route.name} loading="lazy" />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default EventDetail
