export function Loading({ label = 'Loading…' }) {
  return (
    <div className="status-block">
      <p>{label}</p>
    </div>
  )
}

export function ErrorState({ title = 'Something went wrong', message }) {
  return (
    <div className="status-block">
      <h2>⚠️ {title}</h2>
      {message && <p>{message}</p>}
    </div>
  )
}
