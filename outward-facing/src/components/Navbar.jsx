import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

const LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/results', label: 'Results' },
  { to: '/events', label: 'Events' },
  { to: '/feeds', label: 'Feeds' },
  { to: '/parties', label: 'Parties' },
  { to: '/candidates', label: 'Candidates' },
  { to: '/polls', label: 'Polls' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/join', label: 'Become A Member' },
  { to: '/donate', label: 'Donate' },
 
]

function Navbar() {
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  // Close the mobile menu after navigating to another page
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  return (
    <nav className="main-nav">
      <div className="nav-bar">
        <Link to="/" className="nav-brand">
          <img src="/logo.png" alt="RazeTally" />
          <span>RazeTally</span>
        </Link>
        <button
          type="button"
          className={`nav-toggle${menuOpen ? ' open' : ''}`}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={menuOpen}
          aria-controls="nav-links"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span />
          <span />
          <span />
        </button>
      </div>
      <div id="nav-links" className={`nav-links${menuOpen ? ' open' : ''}`}>
        {LINKS.map(({ to, label }) => (
          <Link key={to} to={to} className={location.pathname === to ? 'active' : ''}>
            {label}
          </Link>
        ))}
      </div>
    </nav>
  )
}

export default Navbar
