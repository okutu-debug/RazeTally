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

  return (
    <nav className="main-nav">
      <Link to="/" className="nav-brand">
        <img src="/logo.png" alt="RazeTally" />
        <span>RazeTally</span>
      </Link>
      <div className="nav-links">
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
