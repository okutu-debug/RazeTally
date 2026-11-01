import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { submitApplication, listJobDescriptions } from '../api'
import { useDemography } from '../hooks/useDemography'

const EMPTY_FORM = {
  gender: 'MALE',
  date_of_birth: '',
  position: '',
  county_id: '',
  constituency_id: '',
  other_names: '',
  surname: '',
  ward_id: '',
  email: '',
  phone_number: '',
  id_passport_number: '',
}

function Apply() {
  const [searchParams] = useSearchParams()
  const [formData, setFormData] = useState({
    ...EMPTY_FORM,
    position: searchParams.get('position') || '',
  })
  const {
    counties, constituencies, wards,
    loading: demographyLoading, error: demographyError,
    constituenciesForCounty, wardsForConstituency,
  } = useDemography()

  const [jobs, setJobs] = useState(null)
  const [jobsError, setJobsError] = useState(null)

  useEffect(() => {
    listJobDescriptions()
      .then(result => setJobs(result.items))
      .catch(err => setJobsError(err.message))
  }, [])

  const [files, setFiles] = useState({
    cv: null,
    certificate: null,
    id_document: null,
    other_document: null,
  })

  const [status, setStatus] = useState({ type: '', message: '' })
  const [submitting, setSubmitting] = useState(false)

  const handleInputChange = (e) => {
    const { name, value } = e.target
    if (name === 'county_id') {
      setFormData({ ...formData, county_id: value, constituency_id: '', ward_id: '' })
    } else if (name === 'constituency_id') {
      setFormData({ ...formData, constituency_id: value, ward_id: '' })
    } else {
      setFormData({ ...formData, [name]: value })
    }
  }

  const handleFileChange = (e) => {
    setFiles({ ...files, [e.target.name]: e.target.files[0] })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setStatus({ type: '', message: '' })

    const county = counties.find(c => c.county_id === formData.county_id)
    const constituency = constituencies.find(c => c.constituency_id === formData.constituency_id)
    const ward = wards.find(w => w.ward_id === formData.ward_id)

    const payload = new FormData()
    const { county_id, constituency_id, ward_id, ...rest } = formData
    Object.keys(rest).forEach(key => {
      payload.append(key, rest[key])
    })
    payload.append('county', county?.county_name || '')
    payload.append('sub_county', constituency?.constituency_name || '')
    payload.append('ward', ward?.ward_name || '')
    if (ward_id) payload.append('ward_id', ward_id)

    Object.keys(files).forEach(key => {
      if (files[key]) payload.append(key, files[key])
    })

    try {
      await submitApplication(payload)
      setStatus({ type: 'success', message: 'Application submitted successfully! ✅' })
      setFormData({ ...EMPTY_FORM, position: formData.position })
      setFiles({ cv: null, certificate: null, id_document: null, other_document: null })
    } catch (err) {
      setStatus({ type: 'error', message: err.message || 'Failed to connect to server.' })
    } finally {
      setSubmitting(false)
    }
  }

  const constituencyOptions = constituenciesForCounty(formData.county_id)
  const wardOptions = wardsForConstituency(formData.constituency_id)

  return (
    <div className="rz-page form-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Recruitment</p>
        <h1>New Application</h1>
        <p>Fill in the details below to apply for a position.</p>
      </div>

      <div className="rz-card">
        {status.message && (
          <div className={`status ${status.type}`}>{status.message}</div>
        )}
        {(demographyError || jobsError) && (
          <div className="status error">
            Could not load form data: {demographyError || jobsError}
          </div>
        )}

        <form onSubmit={handleSubmit} encType="multipart/form-data">
          <div className="form-grid">
            <div className="form-group">
              <label>Surname</label>
              <input type="text" name="surname" value={formData.surname} onChange={handleInputChange} required />
            </div>
            <div className="form-group">
              <label>Other Names</label>
              <input type="text" name="other_names" value={formData.other_names} onChange={handleInputChange} required />
            </div>

            <div className="form-group">
              <label>Email</label>
              <input type="email" name="email" value={formData.email} onChange={handleInputChange} required />
            </div>
            <div className="form-group">
              <label>Phone Number</label>
              <input type="tel" name="phone_number" value={formData.phone_number} onChange={handleInputChange} required />
            </div>

            <div className="form-group">
              <label>ID/Passport Number</label>
              <input type="text" name="id_passport_number" value={formData.id_passport_number} onChange={handleInputChange} required />
            </div>
            <div className="form-group">
              <label>Date of Birth</label>
              <input type="date" name="date_of_birth" value={formData.date_of_birth} onChange={handleInputChange} required />
            </div>

            <div className="form-group">
              <label>Gender</label>
              <select name="gender" value={formData.gender} onChange={handleInputChange}>
                <option value="MALE">Male</option>
                <option value="FEMALE">Female</option>
              </select>
            </div>
            <div className="form-group">
              <label>Position</label>
              <select name="position" value={formData.position} onChange={handleInputChange} disabled={jobs === null} required>
                <option value="">{jobs === null ? 'Loading…' : 'Select position…'}</option>
                {(jobs || []).map(job => (
                  <option key={job.id} value={job.position}>{job.position}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>County</label>
              <select name="county_id" value={formData.county_id} onChange={handleInputChange} disabled={demographyLoading} required>
                <option value="">{demographyLoading ? 'Loading…' : 'Select county…'}</option>
                {counties.map(c => (
                  <option key={c.county_id} value={c.county_id}>{c.county_name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Sub County</label>
              <select
                name="constituency_id"
                value={formData.constituency_id}
                onChange={handleInputChange}
                disabled={!formData.county_id}
                required
              >
                <option value="">{formData.county_id ? 'Select sub county…' : 'Select a county first'}</option>
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
                onChange={handleInputChange}
                disabled={!formData.constituency_id}
                required
              >
                <option value="">{formData.constituency_id ? 'Select ward…' : 'Select a sub county first'}</option>
                {wardOptions.map(w => (
                  <option key={w.ward_id} value={w.ward_id}>{w.ward_name}</option>
                ))}
              </select>
            </div>

            <div className="form-group full">
              <label>CV</label>
              <input type="file" name="cv" accept=".pdf,.doc,.docx" onChange={handleFileChange} />
            </div>

            <div className="form-group full">
              <label>Certificate</label>
              <input type="file" name="certificate" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFileChange} />
            </div>

            <div className="form-group full">
              <label>ID Document</label>
              <input type="file" name="id_document" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFileChange} />
            </div>

            <div className="form-group full">
              <label>Other Document (Optional)</label>
              <input type="file" name="other_document" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFileChange} />
            </div>
          </div>

          <button type="submit" disabled={submitting} className="rz-btn rz-btn-primary" style={{ marginTop: '2rem', width: '100%' }}>
            {submitting ? 'Submitting…' : 'Submit Application'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default Apply
