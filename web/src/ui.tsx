// Native primitives styled after the 0.31 Qt shell (paper/night tokens in styles.css).
import { ReactNode, useLayoutEffect, useRef } from 'react'

export type IconName =
  | 'home' | 'chat' | 'tasks' | 'settings' | 'bell' | 'clock' | 'check'
  | 'check-circle' | 'plus' | 'search' | 'chevron-down' | 'calendar'
  | 'sparkles' | 'moon' | 'sun' | 'edit' | 'trash' | 'x' | 'stop'
  | 'send' | 'pause' | 'play' | 'refresh' | 'folder' | 'download' | 'image'
  | 'link' | 'alert' | 'info' | 'list' | 'book' | 'database' | 'user' | 'copy'
  | 'panel' | 'file' | 'clipboard'

const ICONS: Record<IconName, ReactNode> = {
  home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5.5 9.5V20h13V9.5" /></>,
  chat: <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H8l-5 3 1.5-4.5A8.5 8.5 0 1 1 21 11.5Z" />,
  tasks: <><rect x="3.5" y="3.5" width="17" height="17" rx="4" /><path d="m8 12 2.8 2.8L16.5 9" /></>,
  settings: <><circle cx="12" cy="12" r="3.2" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" /></>,
  bell: <><path d="M18 9a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7" /><path d="M10 20a2 2 0 0 0 4 0" /></>,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  'check-circle': <><circle cx="12" cy="12" r="8.5" /><path d="m8.3 12.3 2.5 2.5 5-5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></>,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  calendar: <><rect x="3.5" y="5" width="17" height="15.5" rx="3" /><path d="M3.5 10h17M8 3v4M16 3v4" /></>,
  sparkles: <><path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4L12 3Z" /><path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" /></>,
  moon: <path d="M20 13.5A8.5 8.5 0 1 1 10.5 4a7 7 0 0 0 9.5 9.5Z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" /></>,
  edit: <><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" /><path d="m14.5 6.5 3 3" /></>,
  trash: <><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13" /><path d="M10.5 11v5M13.5 11v5" /></>,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="1.5" />,
  send: <><path d="M21 3 10.5 13.5" /><path d="M21 3l-7 18-3.5-7.5L3 10l18-7Z" /></>,
  pause: <path d="M9 5v14M15 5v14" />,
  play: <path d="M8 5.5 18.5 12 8 18.5v-13Z" />,
  refresh: <><path d="M20 12a8 8 0 1 1-2.3-5.6" /><path d="M20 4v5h-5" /></>,
  folder: <path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h3.6l2 2.5h7.4a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7.5Z" />,
  download: <><path d="M12 4v10.5" /><path d="m7.5 10 4.5 4.5L16.5 10" /><path d="M4.5 19.5h15" /></>,
  image: <><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="m5 17 5-5 3.5 3.5L16 13l3 3.5" /></>,
  link: <><path d="M10 14a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 0 0-5.7-5.7L11.5 6.8" /><path d="M14 10a4 4 0 0 0-5.7 0l-2.8 2.8a4 4 0 0 0 5.7 5.7l1.3-1.3" /></>,
  alert: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5M12 16.2v.1" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 7.8v.1" /></>,
  list: <path d="M8 6h12M8 12h12M8 18h12M4 6h.1M4 12h.1M4 18h.1" />,
  book: <><path d="M4 5.5A2 2 0 0 1 6 3.5h5v17H6a2 2 0 0 0-2 2v-17Z" /><path d="M20 5.5a2 2 0 0 0-2-2h-5v17h5a2 2 0 0 1 2 2v-17Z" /></>,
  database: <><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>,
  user: <><circle cx="12" cy="8" r="3.6" /><path d="M5 20c.6-3.6 3.4-5.5 7-5.5s6.4 1.9 7 5.5" /></>,
  copy: <><rect x="8.5" y="8.5" width="11" height="11" rx="2.2" /><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5" /></>,
  panel: <><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><path d="M9.5 4.5v15" /></>,
  file: <><path d="M6 3.5h8l4 4v13H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z" /><path d="M14 3.5v4h4M8 12h8M8 16h8" /></>,
  clipboard: <><rect x="5" y="5" width="14" height="16" rx="2" /><path d="M9 5V3.5h6V5M8.5 10h7M8.5 14h7M8.5 18h4" /></>,
}

export function Icon(props: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={props.className}
      width={props.size ?? 16}
      height={props.size ?? 16}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {ICONS[props.name]}
    </svg>
  )
}

export function Paw(props: { size?: number }) {
  return (
    <svg width={props.size ?? 18} height={props.size ?? 18} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <ellipse cx="12.1875" cy="15.5625" rx="4.6875" ry="3.9375" />
      <ellipse cx="6.375" cy="11.25" rx="1.875" ry="2.25" />
      <ellipse cx="10.5" cy="7.6875" rx="1.875" ry="2.4375" />
      <ellipse cx="15.375" cy="8.0625" rx="1.875" ry="2.4375" />
      <ellipse cx="18.9375" cy="11.8125" rx="1.6875" ry="2.0625" />
    </svg>
  )
}

export function Button(props: {
  children: ReactNode
  onClick?: () => void
  primary?: boolean
  danger?: boolean
  ghost?: boolean
  small?: boolean
  large?: boolean
  disabled?: boolean
  pressed?: boolean
  title?: string
  className?: string
}) {
  const cls = [
    'btn',
    props.primary && 'btn-primary',
    props.danger && 'btn-danger',
    props.ghost && 'btn-ghost',
    props.small && 'btn-sm',
    props.large && 'btn-lg',
    props.className,
  ].filter(Boolean).join(' ')
  return (
    <button
      type="button"
      className={cls}
      disabled={props.disabled}
      aria-pressed={props.pressed}
      title={props.title}
      onClick={props.onClick}
    >
      {props.children}
    </button>
  )
}

export function Pill(props: {
  children: ReactNode
  tone?: 'plain' | 'brand' | 'danger' | 'calm' | 'caution' | 'info' | 'line'
  className?: string
}) {
  return (
    <span className={`pill${props.tone && props.tone !== 'plain' ? ` pill-${props.tone}` : ''}${props.className ? ` ${props.className}` : ''}`}>
      {props.children}
    </span>
  )
}

export function Card(props: {
  title: string
  desc: string
  icon: IconName
  children: ReactNode
}) {
  return (
    <section className="set-card">
      <header className="set-card-head">
        <span className="set-icon"><Icon name={props.icon} size={18} /></span>
        <div>
          <h2 className="set-title">{props.title}</h2>
          <p className="set-desc">{props.desc}</p>
        </div>
      </header>
      {props.children}
    </section>
  )
}

export function Row(props: { label: string; desc: string; children: ReactNode }) {
  return (
    <div className="set-row">
      <div>
        <div className="set-row-label">{props.label}</div>
        {props.desc && <div className="set-row-desc">{props.desc}</div>}
      </div>
      <div className="set-row-body">{props.children}</div>
    </div>
  )
}

export function Toggle(props: {
  label: string
  desc?: string
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      className="switch"
      aria-checked={props.checked}
      disabled={props.disabled}
      onClick={() => props.onChange(!props.checked)}
    >
      <span className="switch-track"><Icon name="check" size={11} /></span>
      <span className="switch-text">
        <span className="switch-label">{props.label}</span>
        {props.desc && <span className="switch-desc">{props.desc}</span>}
      </span>
    </button>
  )
}

export function Segmented<T extends string>(props: {
  options: readonly { key: T; label: ReactNode }[]
  value: T
  onChange: (value: T) => void
  className?: string
  variant?: 'default' | 'tabs' | 'compact'
  ariaLabel?: string
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const thumbRef = useRef<HTMLSpanElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])
  const previous = useRef<{ left: number; width: number } | null>(null)
  const liveProps = useRef(props)
  liveProps.current = props
  const optionsKey = props.options.map((option) => option.key).join('\u001f')

  useLayoutEffect(() => {
    const track = trackRef.current
    const thumb = thumbRef.current
    const item = itemRefs.current[props.options.findIndex((option) => option.key === props.value)]
    if (!track || !thumb || !item) return
    const trackRect = track.getBoundingClientRect()
    const itemRect = item.getBoundingClientRect()
    const next = { left: itemRect.left - trackRect.left - track.clientLeft, width: itemRect.width }
    const thumbRect = thumb.getBoundingClientRect()
    const from = previous.current
      ? { left: thumbRect.left - trackRect.left - track.clientLeft, width: thumbRect.width }
      : null
    if (!from || window.matchMedia('(prefers-reduced-motion: reduce)').matches || typeof thumb.animate !== 'function') {
      thumb.style.left = `${next.left}px`
      thumb.style.width = `${next.width}px`
      previous.current = next
      return
    }

    const delta = next.left - from.left
    const stretch = Math.min(Math.abs(delta) * 0.5, Math.max(next.width, from.width) * 1.25)
    const stretched = delta >= 0
      ? { left: from.left, width: from.width + stretch }
      : { left: from.left - stretch, width: from.width + stretch }
    const overshoot = Math.max(0, Math.min(next.width * 0.055, 4))
    const frames: Keyframe[] = [
      { left: `${from.left}px`, width: `${from.width}px`, offset: 0 },
      { left: `${stretched.left}px`, width: `${stretched.width}px`, offset: 0.36 },
      { left: `${next.left}px`, width: `${next.width + overshoot}px`, offset: 0.78 },
      { left: `${next.left}px`, width: `${next.width}px`, offset: 1 },
    ]
    thumb.getAnimations().forEach((animation) => animation.cancel())
    thumb.style.left = `${from.left}px`
    thumb.style.width = `${from.width}px`
    const animation = thumb.animate(frames, { duration: 440, easing: 'cubic-bezier(.23,1,.32,1)' })
    animation.onfinish = () => {
      thumb.style.left = `${next.left}px`
      thumb.style.width = `${next.width}px`
    }
    previous.current = next
  }, [props.value, optionsKey])

  useLayoutEffect(() => {
    const track = trackRef.current
    if (!track) return
    const update = () => {
      const currentProps = liveProps.current
      const item = itemRefs.current[currentProps.options.findIndex((option) => option.key === currentProps.value)]
      const thumb = thumbRef.current
      if (!item || !thumb) return
      const trackRect = track.getBoundingClientRect()
      const rect = item.getBoundingClientRect()
      const next = { left: rect.left - trackRect.left - track.clientLeft, width: rect.width }
      thumb.getAnimations().forEach((animation) => animation.cancel())
      thumb.style.left = `${next.left}px`
      thumb.style.width = `${next.width}px`
      previous.current = next
    }
    const observer = new ResizeObserver(update)
    observer.observe(track)
    itemRefs.current.forEach((item) => item && observer.observe(item))
    return () => observer.disconnect()
  }, [])

  const variant = props.variant ?? 'default'
  return (
    <div
      ref={trackRef}
      className={`seg rubber-segment rubber-segment-${variant}${props.className ? ` ${props.className}` : ''}`}
      role={variant === 'tabs' ? 'tablist' : 'group'}
      aria-label={props.ariaLabel}
    >
      <span ref={thumbRef} className="rubber-segment-thumb" aria-hidden="true" />
      {props.options.map((option) => (
        <button
          key={option.key}
          ref={(element) => { itemRefs.current[props.options.indexOf(option)] = element }}
          type="button"
          role={variant === 'tabs' ? 'tab' : undefined}
          aria-selected={variant === 'tabs' ? props.value === option.key : undefined}
          aria-pressed={variant === 'tabs' ? undefined : props.value === option.key}
          tabIndex={props.value === option.key ? 0 : -1}
          className={`seg-item${props.value === option.key ? ' is-active' : ''}`}
          onClick={() => props.onChange(option.key)}
          onKeyDown={(event) => {
            const current = props.options.findIndex((item) => item.key === props.value)
            const direction = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
            const target = direction ? (current + direction + props.options.length) % props.options.length : event.key === 'Home' ? 0 : event.key === 'End' ? props.options.length - 1 : -1
            if (target < 0) return
            event.preventDefault()
            const next = props.options[target]
            props.onChange(next.key)
            itemRefs.current[target]?.focus()
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function TextInput(props: {
  value: string
  placeholder?: string
  password?: boolean
  onChange: (value: string) => void
}) {
  return (
    <input
      className="field"
      type={props.password ? 'password' : 'text'}
      value={props.value}
      placeholder={props.placeholder}
      autoComplete="off"
      onChange={(e) => props.onChange(e.target.value)}
    />
  )
}

export function TimeInput(props: { value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <input
      className="field field-time"
      type="time"
      value={props.value}
      disabled={props.disabled}
      onChange={(e) => e.target.value && props.onChange(e.target.value)}
    />
  )
}

export function StatusLine(props: { text: string; tone?: 'calm' | 'alert' | 'plain' }) {
  if (!props.text) return null
  return <p className={`status-line${props.tone && props.tone !== 'plain' ? ` ${props.tone}` : ''}`}>{props.text}</p>
}
