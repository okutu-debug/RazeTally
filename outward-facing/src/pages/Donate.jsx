import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getContributionsSummary,
  getPublicContributions,
  contributeMpesa,
  getMpesaContributionStatus,
  contributePaypal,
  capturePaypalContribution,
  cancelPaypalContribution,
} from '../api'

const MPESA_POLL_MS = 3000
const MPESA_POLL_TIMEOUT_MS = 120000

const EMPTY_MPESA = { contributor_name: '', phone_number: '', amount: 100 }
const EMPTY_PAYPAL = { contributor_name: '', email: '', amount: 10 }

function Donate() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [totals, setTotals] = useState(null)
  const [redirectStatus, setRedirectStatus] = useState(null)
  const [donations, setDonations] = useState(null)
  const [donationsError, setDonationsError] = useState('')

  const [mpesaForm, setMpesaForm] = useState(EMPTY_MPESA)
  const [mpesaSubmitting, setMpesaSubmitting] = useState(false)
  const [mpesaError, setMpesaError] = useState('')
  const [mpesaContribution, setMpesaContribution] = useState(null)
  const mpesaPollStart = useRef(null)

  const [paypalForm, setPaypalForm] = useState(EMPTY_PAYPAL)
  const [paypalSubmitting, setPaypalSubmitting] = useState(false)
  const [paypalError, setPaypalError] = useState('')

  const loadTotals = useCallback(() => {
    getContributionsSummary()
      .then(rows => {
        const byCurrency = Object.fromEntries(rows.map(r => [r.currency, r]))
        setTotals(byCurrency)
      })
      .catch(() => {}) // non-critical — the page still works without totals
  }, [])

  const loadDonations = useCallback(() => {
    getPublicContributions(100)
      .then(setDonations)
      .catch(err => setDonationsError(err.message || 'Could not load donations.'))
  }, [])

  useEffect(() => { loadTotals(); loadDonations() }, [loadTotals, loadDonations])

  // Handle PayPal's redirect back to this page (?paypal_action=return|cancel&token=<order id>)
  useEffect(() => {
    const action = searchParams.get('paypal_action')
    const token = searchParams.get('token')
    if (!action || !token) return

    const resolve = async () => {
      try {
        if (action === 'return') {
          await capturePaypalContribution(token)
          setRedirectStatus({ type: 'success', message: 'Thank you! Your PayPal contribution was received. 🎉' })
          loadTotals()
          loadDonations()
        } else {
          await cancelPaypalContribution(token)
          setRedirectStatus({ type: 'error', message: 'Payment was cancelled.' })
        }
      } catch (err) {
        setRedirectStatus({ type: 'error', message: err.message || 'Could not confirm PayPal payment.' })
      } finally {
        const next = new URLSearchParams(searchParams)
        next.delete('paypal_action')
        next.delete('token')
        setSearchParams(next, { replace: true })
      }
    }
    resolve()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Poll an in-flight M-Pesa contribution until it resolves (or times out)
  useEffect(() => {
    if (!mpesaContribution || mpesaContribution.status !== 'pending') return

    const id = setInterval(() => {
      if (Date.now() - mpesaPollStart.current > MPESA_POLL_TIMEOUT_MS) {
        clearInterval(id)
        return
      }
      getMpesaContributionStatus(mpesaContribution.id)
        .then(setMpesaContribution)
        .catch(() => {})
    }, MPESA_POLL_MS)

    return () => clearInterval(id)
  }, [mpesaContribution])

  useEffect(() => {
    if (mpesaContribution?.status === 'completed') { loadTotals(); loadDonations() }
  }, [mpesaContribution, loadTotals, loadDonations])

  const handleMpesaChange = (e) => {
    const { name, value } = e.target
    setMpesaForm({ ...mpesaForm, [name]: value })
  }

  const handleMpesaSubmit = async (e) => {
    e.preventDefault()
    setMpesaError('')
    setMpesaSubmitting(true)
    try {
      const result = await contributeMpesa({
        ...mpesaForm,
        amount: Number(mpesaForm.amount),
      })
      mpesaPollStart.current = Date.now()
      setMpesaContribution(result)
    } catch (err) {
      setMpesaError(err.message || 'Could not send the STK push. Please try again.')
    } finally {
      setMpesaSubmitting(false)
    }
  }

  const handlePaypalChange = (e) => {
    const { name, value } = e.target
    setPaypalForm({ ...paypalForm, [name]: value })
  }

  const handlePaypalSubmit = async (e) => {
    e.preventDefault()
    setPaypalError('')
    setPaypalSubmitting(true)
    try {
      const result = await contributePaypal({
        ...paypalForm,
        amount: Number(paypalForm.amount),
      })
      window.location.href = result.approval_url
    } catch (err) {
      setPaypalError(err.message || 'Could not start PayPal checkout. Please try again.')
      setPaypalSubmitting(false)
    }
  }

  const resetMpesa = () => {
    setMpesaContribution(null)
    setMpesaForm(EMPTY_MPESA)
  }

  return (
    <div className="rz-page form-page">
      <div className="rz-hero">
        <p className="rz-eyebrow">Raze Tally</p>
        <h1>Support the Cause</h1>
        <p>Real-time, transparent election tallying and campaign coordination — from the first rally to the final count.</p>
      </div>

      <div className="rz-card" style={{ marginBottom: '2rem' }}>
        <p>
          Raze Tally powers the campaign end to end: coordinating events and rallies on the ground,
          capturing and verifying official tally forms as results come in, and publishing live,
          transparent vote counts the public can trust.
        </p>
        <p>
          With your support, we can keep results transparent and verifiable, keep the campaign
          moving on the ground, and make sure the voice of the people is directly reflected in the
          leaders we choose.
        </p>
        <p>If you can, and only if you can – please make a contribution to support this cause.</p>

        <div className="donate-details-grid">
          <div>
            <h3>Bank Deposit Details</h3>
            <dl className="donate-detail-list">
              <div><dt>Bank</dt><dd>Cooperative Bank Branch</dd></div>
              <div><dt>Account Name</dt><dd>Raze Technologies</dd></div>
              <div><dt>Account Number</dt><dd>02406705546150</dd></div>
              <div><dt>M-PESA Paybill</dt><dd>542542</dd></div>
            </dl>
          </div>
          <div>
            <h3>For International Donors</h3>
            <dl className="donate-detail-list">
              <div><dt>Sendwave M-PESA Number</dt><dd>+254706650263</dd></div>
            </dl>
          </div>
        </div>
      </div>

      {redirectStatus && <div className={`status ${redirectStatus.type}`}>{redirectStatus.message}</div>}

      {totals && (
        <div className="stats-grid" style={{ marginBottom: '2rem' }}>
          <div className="stat-card">
            <h3>Raised via M-Pesa</h3>
            <div className="stat-value">KES {(totals.KES?.total ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <p className="stat-label">{totals.KES?.n ?? 0} contribution(s)</p>
          </div>
          <div className="stat-card">
            <h3>Raised via PayPal</h3>
            <div className="stat-value">USD {(totals.USD?.total ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <p className="stat-label">{totals.USD?.n ?? 0} contribution(s)</p>
          </div>
        </div>
      )}

      <div className="donate-grid">
        <div className="rz-card">
          <h2>Contribute via M-Pesa</h2>
          {mpesaError && <div className="status error">{mpesaError}</div>}

          {mpesaContribution ? (
            <div>
              {mpesaContribution.status === 'pending' && (
                <div className="status">⏳ Check your phone and enter your M-Pesa PIN to complete this contribution…</div>
              )}
              {mpesaContribution.status === 'completed' && (
                <div className="status success">
                  ✅ Received KES {mpesaContribution.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  {mpesaContribution.mpesa_receipt_number ? ` — receipt ${mpesaContribution.mpesa_receipt_number}` : ''}
                </div>
              )}
              {(mpesaContribution.status === 'failed' || mpesaContribution.status === 'cancelled') && (
                <div className="status error">
                  ❌ Payment {mpesaContribution.status}{mpesaContribution.result_desc ? `: ${mpesaContribution.result_desc}` : '.'}
                </div>
              )}
              {mpesaContribution.status !== 'pending' && (
                <button type="button" className="rz-btn rz-btn-outline" style={{ width: '100%', marginTop: '1rem' }} onClick={resetMpesa}>
                  Make another contribution
                </button>
              )}
            </div>
          ) : (
            <form onSubmit={handleMpesaSubmit}>
              <div className="form-group">
                <label>Full name</label>
                <input type="text" name="contributor_name" value={mpesaForm.contributor_name} onChange={handleMpesaChange} required />
              </div>
              <div className="form-group">
                <label>M-Pesa phone number</label>
                <input type="tel" name="phone_number" placeholder="e.g. 0712345678" value={mpesaForm.phone_number} onChange={handleMpesaChange} required />
              </div>
              <div className="form-group">
                <label>Amount (KES)</label>
                <input type="number" name="amount" min="1" step="1" value={mpesaForm.amount} onChange={handleMpesaChange} required />
              </div>
              <button type="submit" disabled={mpesaSubmitting} className="rz-btn rz-btn-primary" style={{ width: '100%', marginTop: '0.5rem' }}>
                {mpesaSubmitting ? 'Sending…' : '📲 Send STK Push'}
              </button>
            </form>
          )}
        </div>

        <div className="rz-card">
          <h2>Contribute via PayPal</h2>
          {paypalError && <div className="status error">{paypalError}</div>}

          <form onSubmit={handlePaypalSubmit}>
            <div className="form-group">
              <label>Full name</label>
              <input type="text" name="contributor_name" value={paypalForm.contributor_name} onChange={handlePaypalChange} required />
            </div>
            <div className="form-group">
              <label>Email</label>
              <input type="email" name="email" value={paypalForm.email} onChange={handlePaypalChange} required />
            </div>
            <div className="form-group">
              <label>Amount (USD)</label>
              <input type="number" name="amount" min="1" step="1" value={paypalForm.amount} onChange={handlePaypalChange} required />
            </div>
            <button type="submit" disabled={paypalSubmitting} className="rz-btn rz-btn-primary" style={{ width: '100%', marginTop: '0.5rem' }}>
              {paypalSubmitting ? 'Redirecting…' : '💳 Continue to PayPal'}
            </button>
          </form>
        </div>
      </div>

      <div className="rz-card" style={{ marginTop: '2rem' }}>
        <h2>For Transparency</h2>
        <p style={{ color: 'var(--rz-text-soft)' }}>Here are all the donations we have got:</p>

        {donationsError && <div className="status error">{donationsError}</div>}

        {donations && donations.length === 0 && !donationsError && (
          <p style={{ color: 'var(--rz-text-soft)' }}>No donations received yet — be the first!</p>
        )}

        {donations && donations.length > 0 && (
          <div className="donations-table-wrap">
            <table className="results-table">
              <thead>
                <tr>
                  <th>Donor</th>
                  <th>Amount</th>
                  <th>Method</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {donations.map(d => (
                  <tr key={d.id}>
                    <td>{d.contributor_name}</td>
                    <td>{d.currency} {d.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td>{d.payment_method === 'mpesa' ? 'M-Pesa' : 'PayPal'}</td>
                    <td>{d.created_at ? new Date(d.created_at).toLocaleDateString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default Donate
