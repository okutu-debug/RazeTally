import { useState, useEffect } from 'react'
import { listAllCounties, listAllConstituencies, listAllWards } from '../api'

/** Fetches the full county/constituency/ward reference lists once, for cascading dropdowns. */
export function useDemography() {
  const [counties, setCounties] = useState([])
  const [constituencies, setConstituencies] = useState([])
  const [wards, setWards] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([listAllCounties(), listAllConstituencies(), listAllWards()])
      .then(([c, con, w]) => {
        setCounties(c)
        setConstituencies(con)
        setWards(w)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  const constituenciesForCounty = (countyId) =>
    countyId ? constituencies.filter(c => c.county_id === countyId) : []

  const wardsForConstituency = (constituencyId) =>
    constituencyId ? wards.filter(w => w.constituency_id === constituencyId) : []

  const wardsForCounty = (countyId) => {
    if (!countyId) return []
    const county = counties.find(c => c.county_id === countyId)
    return county ? wards.filter(w => w.county_name === county.county_name) : []
  }

  return { counties, constituencies, wards, loading, error, constituenciesForCounty, wardsForConstituency, wardsForCounty }
}
