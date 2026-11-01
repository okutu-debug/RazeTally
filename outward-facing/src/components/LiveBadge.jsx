function LiveBadge({ lastUpdated }) {
  return (
    <div className="live-row">
      <span className="live-badge">
        <span className="live-dot" />
        Live
      </span>
      {lastUpdated && (
        <span className="live-updated">Updated {lastUpdated.toLocaleTimeString()}</span>
      )}
    </div>
  )
}

export default LiveBadge
