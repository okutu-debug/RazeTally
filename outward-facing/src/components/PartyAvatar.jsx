import { useState } from 'react'
import Avatar from './Avatar'

function PartyAvatar({ name, size = 44, logoUrl }) {
  const [failed, setFailed] = useState(false)

  if (!logoUrl || failed) return <Avatar name={name} size={size} />

  return (
    <img
      className="rz-avatar rz-avatar-img"
      style={{ width: size, height: size }}
      src={logoUrl}
      alt={name || ''}
      onError={() => setFailed(true)}
    />
  )
}

export default PartyAvatar
