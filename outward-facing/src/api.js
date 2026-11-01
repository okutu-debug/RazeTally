export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options)
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // response wasn't JSON — fall back to the status text
    }
    throw new Error(detail)
  }
  const contentType = response.headers.get('content-type') || ''
  return contentType.includes('application/json') ? response.json() : response
}

// Dashboard
export function getDashboardSummary() {
  return apiFetch('/dashboard/summary')
}

// Jobs / Recruitment
export function listJobDescriptions({ search = '', limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams({ search, limit, offset, published: 'true' })
  return apiFetch(`/job-descriptions?${params}`)
}

export function getJobDescription(id) {
  return apiFetch(`/job-descriptions/${id}`)
}

export function submitApplication(formData) {
  return apiFetch('/apply', { method: 'POST', body: formData })
}

// Campaigns
export function listCampaignRoutes({ search = '', limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams({ search, limit, offset, published: 'true' })
  return apiFetch(`/campaign-routes?${params}`)
}

export function getCampaignRoute(id) {
  return apiFetch(`/campaign-routes/${id}`)
}

export function campaignRouteBannerUrl(id) {
  return `${API_BASE_URL}/campaign-routes/${id}/banner`
}

export function getCampaignRouteMedia(id) {
  return apiFetch(`/campaign-routes/${id}/media`)
}

export function campaignMediaUrl(mediaId) {
  return `${API_BASE_URL}/campaign-location-media/${mediaId}`
}

// Demography (for cascading county/constituency/ward dropdowns)
export function listAllCounties() {
  return apiFetch('/counties/all')
}

export function listAllConstituencies() {
  return apiFetch('/constituencies/all')
}

export function listAllWards() {
  return apiFetch('/wards/all')
}

// Membership
export function submitPartyMember(payload) {
  return apiFetch('/party-members', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

// Funding / contributions
export function getContributionsSummary() {
  return apiFetch('/contributions/summary')
}

export function getPublicContributions(limit = 100) {
  return apiFetch(`/contributions/public-list?limit=${limit}`)
}

export function contributeMpesa(payload) {
  return apiFetch('/contributions/mpesa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getMpesaContributionStatus(id) {
  return apiFetch(`/contributions/mpesa/${id}`)
}

export function contributePaypal(payload) {
  return apiFetch('/contributions/paypal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function capturePaypalContribution(orderId) {
  return apiFetch('/contributions/paypal/capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order_id: orderId }),
  })
}

export function cancelPaypalContribution(orderId) {
  return apiFetch('/contributions/paypal/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order_id: orderId }),
  })
}

// Election results
export function listFormTypes() {
  return apiFetch('/form-types')
}

export function getTallySummary(formType, { top = 10 } = {}) {
  return apiFetch(`/tally/${formType}/summary?top=${top}`)
}

export function getTally(formType, { groupValue = '', top } = {}) {
  const params = new URLSearchParams()
  if (groupValue) params.set('group_value', groupValue)
  if (top) params.set('top', top)
  const qs = params.toString()
  return apiFetch(`/tally/${formType}${qs ? `?${qs}` : ''}`)
}

export function getFormLocations(formType) {
  return apiFetch(`/forms/${formType}/locations`)
}

export function getTallyByLocation(formType, { countyCode, constituencyCode, wardCode, top = 20 } = {}) {
  const params = new URLSearchParams({ top })
  if (countyCode) params.set('county_code', countyCode)
  if (constituencyCode) params.set('constituency_code', constituencyCode)
  if (wardCode) params.set('ward_code', wardCode)
  return apiFetch(`/tally/${formType}/by-location?${params}`)
}

export function getParties() {
  return apiFetch('/parties')
}

export function partyLogoUrl(partyId) {
  return `${API_BASE_URL}/parties/${partyId}/logo`
}

export function getCandidates({ search, position, partyId } = {}) {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  if (position) params.set('position', position)
  if (partyId) params.set('party_id', partyId)
  const qs = params.toString()
  return apiFetch(`/candidates${qs ? `?${qs}` : ''}`)
}

export function candidatePhotoUrl(candidateId) {
  return `${API_BASE_URL}/candidates/${candidateId}/photo`
}

// Opinion Polls
export function listOpinionPolls({ search = '', position = '', limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams({ search, limit, offset, published: 'true' })
  if (position) params.set('position', position)
  return apiFetch(`/opinion-polls?${params}`)
}

export function getOpinionPoll(id) {
  return apiFetch(`/opinion-polls/${id}`)
}

export function voteOpinionPoll(id, resultId) {
  return apiFetch(`/opinion-polls/${id}/vote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ result_id: resultId }),
  })
}

// Feed (read-only)
export function listFeedPosts({ limit = 20, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit, offset })
  return apiFetch(`/feed/posts?${params}`)
}

export function listFeedPostComments(postId) {
  return apiFetch(`/feed/posts/${postId}/comments`)
}

export function feedImageUrl(imageId) {
  return `${API_BASE_URL}/feed/images/${imageId}`
}
