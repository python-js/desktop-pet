import { useEffect, useRef, useState } from 'react'
import './LatticeLoader.css'

// Lattice Loader, copied from the ReactBits TS/CSS registry implementation.
// The props are intentionally kept to the working chat state used here.
const CELLS: (number | null)[] = [0, 1, 2, 7, null, 3, 6, 5, 4]
const STEP_MS = 90
const SCALE = 1.2

function formatElapsed(deciseconds: number) {
  return deciseconds < 600
    ? `${(deciseconds / 10).toFixed(1)}s`
    : `${Math.floor(deciseconds / 600)}m ${((deciseconds % 600) / 10).toFixed(1)}s`
}

export default function LatticeLoader(props: { label?: string }) {
  const timerRef = useRef<HTMLSpanElement>(null)
  const [announce] = useState(`${props.label || '正在回复…'}, in progress`)

  useEffect(() => {
    const startedAt = performance.now()
    const paint = () => {
      const elapsed = Math.floor((performance.now() - startedAt) / 100)
      if (timerRef.current) timerRef.current.textContent = formatElapsed(elapsed)
    }
    paint()
    const timer = window.setInterval(paint, 100)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <span
      className="lattice-loader"
      data-status="working"
      data-shape="round"
      role="status"
      style={{ '--ll-cycle': `${8 * STEP_MS * SCALE}ms` } as import('react').CSSProperties}
    >
      <span className="lattice-loader__grid" aria-hidden="true">
        <span className="lattice-loader__layer lattice-loader__run">
          {CELLS.map((cell, index) => (
            <span
              key={index}
              className="lattice-loader__cell"
              data-hole={cell == null ? '' : undefined}
              style={cell == null ? undefined : { animationDelay: `${Math.round(cell * STEP_MS * SCALE)}ms` }}
            />
          ))}
        </span>
        <span className="lattice-loader__layer lattice-loader__mark">
          {CELLS.map((_, index) => <span key={index} className="lattice-loader__cell" />)}
        </span>
      </span>
      <span className="lattice-loader__label" aria-hidden="true">
        <span className="lattice-loader__text" data-active="">{props.label || '正在回复…'}</span>
      </span>
      <span ref={timerRef} className="lattice-loader__timer" aria-hidden="true">0.0s</span>
      <span className="lattice-loader__sr">{announce}</span>
    </span>
  )
}
