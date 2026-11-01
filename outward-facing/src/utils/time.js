/** Relative timestamp, e.g. "2h ago", falling back to a formatted date. */
export function timeAgo(isoString) {
  if (!isoString) return ''
  const date = new Date(isoString)
  const seconds = (Date.now() - date.getTime()) / 1000
  if (seconds < 0) return date.toLocaleString()
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 172800) return 'Yesterday'
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}
