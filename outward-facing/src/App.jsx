import './App.css'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import JobDetail from './pages/JobDetail'
import Apply from './pages/Apply'
import Events from './pages/Events'
import EventDetail from './pages/EventDetail'
import Join from './pages/Join'
import Results from './pages/Results'
import Feeds from './pages/Feeds'
import Donate from './pages/Donate'
import Parties from './pages/Parties'
import Candidates from './pages/Candidates'
import Polls from './pages/Polls'
import PollDetail from './pages/PollDetail'

function App() {
  return (
    <Router>
      <div className="app-container">
        <Navbar />
        <div className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/apply" element={<Apply />} />
            <Route path="/events"  element={<Events />} />
            <Route path="/events/:id" element={<EventDetail />} />
            <Route path="/join" element={<Join />} />
            <Route path="/results" element={<Results />} />
            <Route path="/parties" element={<Parties />} />
            <Route path="/candidates" element={<Candidates />} />
            <Route path="/polls" element={<Polls />} />
            <Route path="/polls/:id" element={<PollDetail />} />
            <Route path="/feeds" element={<Feeds />} />
            <Route path="/donate" element={<Donate />} />
          </Routes>
        </div>
      </div>
    </Router>
  )
}

export default App
