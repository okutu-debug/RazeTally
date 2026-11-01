const PALETTE = ['#152744', '#1e4a85', '#2471a3', '#0f7a5c', '#8a3b7c', '#b23b3b', '#c17d1f', '#2f7a7a']

export function colorFor(seed) {
  let hash = 0
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  return PALETTE[hash % PALETTE.length]
}

function initials(name) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase()
}

function Avatar({ name, size = 44 }) {
  return (
    <div
      className="rz-avatar"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.4,
        background: colorFor(name || '?'),
      }}
    >
      {initials(name || '?')}
    </div>
  )
}

export default Avatar
