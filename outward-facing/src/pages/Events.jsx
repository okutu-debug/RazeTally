import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { listCampaignRoutes, campaignRouteBannerUrl } from '../api'
import { Loading, ErrorState } from '../components/StatusMessage'

function CampaignCard({ route }) {
  const [bannerFailed, setBannerFailed] = useState(false)

  return (
    <Link to={`/events/${route.id}`} className="item-card">
      {bannerFailed ? (
        <div className="item-card-banner placeholder">{route.name}</div>
      ) : (
        <img
          className="item-card-banner"
          src={campaignRouteBannerUrl(route.id)}
          alt={route.name}
          onError={() => setBannerFailed(true)}
        />
      )}
      <div className="item-card-body">
        <h3>{route.name}</h3>
        <p>{route.address || [route.ward, route.constituency, route.county].filter(Boolean).join(', ')}</p>
        <div className="item-card-meta">
          {route.status && <span className="rz-badge rz-badge-neutral">{route.status}</span>}
          {route.date_from && <span className="rz-badge rz-badge-success">{route.date_from}</span>}
        </div>
      </div>
    </Link>
  )
}

function Events() {
  const [items, setItems] = useState(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    const timeout = setTimeout(() => {
      listCampaignRoutes({ search })
        .then(result => setItems(result.items))
        .catch(err => setError(err.message))
    }, 250)
    return () => clearTimeout(timeout)
  }, [search])

  return (
    <div className="rz-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">On the ground</p>
        <h1>Events / Rallies</h1>
        <p>Follow the event / rally trail — see where we've been and where we're headed next.</p>
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Search by location, county, ward…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {error && <ErrorState title="Could not load campaign routes" message={error} />}
      {!error && items === null && <Loading label="Loading campaign routes…" />}
      {!error && items && items.length === 0 && (
        <div className="status-block">
          <p>No campaign stops published yet — check back soon.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <div className="card-grid">
          {items.map(route => <CampaignCard key={route.id} route={route} />)}
        </div>
      )}
    </div>
  )
}

export default Events
