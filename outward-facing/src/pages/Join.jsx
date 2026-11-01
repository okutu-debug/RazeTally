import { useState } from 'react'
import { submitPartyMember } from '../api'
import { useDemography } from '../hooks/useDemography'

const EMPTY_FORM = {
  name: '',
  id_number: '',
  email: '',
  phone_number: '',
  age: '',
  gender: '',
  county_id: '',
  constituency_id: '',
  ward_id: '',
}

function Join() {
  const [formData, setFormData] = useState(EMPTY_FORM)
  const [status, setStatus] = useState({ type: '', message: '' })
  const [submitting, setSubmitting] = useState(false)
  const { counties, constituencies, wards, loading: demographyLoading, error: demographyError, constituenciesForCounty, wardsForConstituency } = useDemography()

  const handleChange = (e) => {
    const { name, value } = e.target
    if (name === 'county_id') {
      setFormData({ ...formData, county_id: value, constituency_id: '', ward_id: '' })
    } else if (name === 'constituency_id') {
      setFormData({ ...formData, constituency_id: value, ward_id: '' })
    } else {
      setFormData({ ...formData, [name]: value })
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setStatus({ type: '', message: '' })

    const county = counties.find(c => c.county_id === formData.county_id)
    const constituency = constituencies.find(c => c.constituency_id === formData.constituency_id)
    const ward = wards.find(w => w.ward_id === formData.ward_id)

    const payload = {
      name: formData.name,
      id_number: formData.id_number,
      email: formData.email,
      phone_number: formData.phone_number,
      age: formData.age ? Number(formData.age) : null,
      gender: formData.gender,
      county: county?.county_name || '',
      constituency: constituency?.constituency_name || '',
      ward: ward?.ward_name || '',
      ward_id: formData.ward_id || null,
    }

    try {
      await submitPartyMember(payload)
      setStatus({ type: 'success', message: 'Welcome to the party! Your membership has been recorded. ✅' })
      setFormData(EMPTY_FORM)
    } catch (err) {
      setStatus({ type: 'error', message: err.message || 'Failed to submit. Please try again.' })
    } finally {
      setSubmitting(false)
    }
  }

  const constituencyOptions = constituenciesForCounty(formData.county_id)
  const wardOptions = wardsForConstituency(formData.constituency_id)

  return (
    <div className="rz-page form-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Membership</p>
        <h1>Join the Party</h1>
        <p>Become a registered member and help drive the movement forward.</p>
      </div>

      <div className="rz-card">
        {status.message && <div className={`status ${status.type}`}>{status.message}</div>}
        {demographyError && (
          <div className="status error">Could not load county/constituency/ward lists: {demographyError}</div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <div className="form-group">
              <label>Full Name</label>
              <input type="text" name="name" value={formData.name} onChange={handleChange} required />
            </div>
            <div className="form-group">
              <label>ID Number</label>
              <input type="text" name="id_number" value={formData.id_number} onChange={handleChange} required />
            </div>

            <div className="form-group">
              <label>Email</label>
              <input type="email" name="email" value={formData.email} onChange={handleChange} />
            </div>
            <div className="form-group">
              <label>Phone Number</label>
              <input type="tel" name="phone_number" value={formData.phone_number} onChange={handleChange} />
            </div>

            <div className="form-group">
              <label>Age</label>
              <input type="number" name="age" min="18" value={formData.age} onChange={handleChange} />
            </div>
            <div className="form-group">
              <label>Gender</label>
              <select name="gender" value={formData.gender} onChange={handleChange}>
                <option value="">Select…</option>
                <option value="MALE">Male</option>
                <option value="FEMALE">Female</option>
              </select>
            </div>

            <div className="form-group">
              <label>County</label>
              <select name="county_id" value={formData.county_id} onChange={handleChange} disabled={demographyLoading} required>
                <option value="">{demographyLoading ? 'Loading…' : 'Select county…'}</option>
                {counties.map(c => (
                  <option key={c.county_id} value={c.county_id}>{c.county_name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Constituency</label>
              <select
                name="constituency_id"
                value={formData.constituency_id}
                onChange={handleChange}
                disabled={!formData.county_id}
                required
              >
                <option value="">{formData.county_id ? 'Select constituency…' : 'Select a county first'}</option>
                {constituencyOptions.map(c => (
                  <option key={c.constituency_id} value={c.constituency_id}>{c.constituency_name}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Ward</label>
              <select
                name="ward_id"
                value={formData.ward_id}
                onChange={handleChange}
                disabled={!formData.constituency_id}
                required
              >
                <option value="">{formData.constituency_id ? 'Select ward…' : 'Select a constituency first'}</option>
                {wardOptions.map(w => (
                  <option key={w.ward_id} value={w.ward_id}>{w.ward_name}</option>
                ))}
              </select>
            </div>
          </div>

          <button type="submit" disabled={submitting} className="rz-btn rz-btn-primary" style={{ marginTop: '2rem', width: '100%' }}>
            {submitting ? 'Submitting…' : 'Join Now'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default Join
