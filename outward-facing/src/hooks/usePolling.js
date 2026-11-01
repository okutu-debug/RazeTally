import { useEffect, useRef } from 'react'

/** Calls `callback` every `intervalMs`, skipping ticks while the tab is hidden. */
export function usePolling(callback, intervalMs = 15000) {
  const savedCallback = useRef(callback)

  useEffect(() => {
    savedCallback.current = callback
  }, [callback])

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') {
        savedCallback.current()
      }
    }, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
}
