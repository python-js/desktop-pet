import { CSSProperties, PointerEvent, ReactNode } from 'react'

type SpecularStyle = CSSProperties & {
  '--specular-x'?: string
  '--specular-y'?: string
}

/** Pointer-following specular highlight adapted from the ReactBits button effect. */
export default function SpecularButton(props: {
  children: ReactNode
  disabled?: boolean
  onClick: () => void
  className?: string
  title?: string
}) {
  const updateHighlight = (event: PointerEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const style = event.currentTarget.style as CSSStyleDeclaration & {
      setProperty: (name: string, value: string) => void
    }
    style.setProperty('--specular-x', `${event.clientX - rect.left}px`)
    style.setProperty('--specular-y', `${event.clientY - rect.top}px`)
  }

  return (
    <button
      type="button"
      className={`specular-button${props.className ? ` ${props.className}` : ''}`}
      style={{ '--specular-x': '50%', '--specular-y': '50%' } as SpecularStyle}
      disabled={props.disabled}
      title={props.title}
      onClick={props.onClick}
      onPointerMove={updateHighlight}
      onPointerEnter={updateHighlight}
    >
      <span className="specular-button-content">{props.children}</span>
    </button>
  )
}
