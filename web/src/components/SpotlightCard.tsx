import { PointerEvent, ReactNode } from 'react'

/** Lightweight, CSS-only spotlight interaction for dense cards. */
export default function SpotlightCard(props: { children: ReactNode; className?: string }) {
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse') return
    const bounds = event.currentTarget.getBoundingClientRect()
    event.currentTarget.style.setProperty('--spotlight-x', `${event.clientX - bounds.left}px`)
    event.currentTarget.style.setProperty('--spotlight-y', `${event.clientY - bounds.top}px`)
  }

  return (
    <div
      className={`spotlight-card${props.className ? ` ${props.className}` : ''}`}
      onPointerMove={move}
    >
      {props.children}
    </div>
  )
}
