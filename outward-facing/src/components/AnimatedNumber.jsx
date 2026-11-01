import { useEffect, useRef, useState } from 'react'

/** Renders a value and briefly flashes when it changes, to signal a live update. */
function AnimatedNumber({ value, format = (v) => v, as: Tag = 'span' }) {
  const prevRef = useRef(value)
  const [flash, setFlash] = useState(false)

  useEffect(() => {
    if (prevRef.current !== value) {
      prevRef.current = value
      setFlash(true)
      const t = setTimeout(() => setFlash(false), 900)
      return () => clearTimeout(t)
    }
  }, [value])

  return <Tag className={flash ? 'value-flash' : ''}>{format(value)}</Tag>
}

export default AnimatedNumber
