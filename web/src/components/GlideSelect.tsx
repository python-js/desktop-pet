import { ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { Icon } from '../ui'

export type GlideSelectOption = {
  value: string
  label: ReactNode
  description?: ReactNode
}

/** Glide Select interaction adapted from the ReactBits TS/CSS registry. */
export default function GlideSelect(props: {
  options: GlideSelectOption[]
  value: string
  onChange: (value: string) => void
  ariaLabel: string
  className?: string
  renderOptionActions?: (value: string) => ReactNode
}) {
  const id = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<number | null>(null)
  const selected = props.options.findIndex((option) => option.value === props.value)
  const activeIndex = active ?? Math.max(0, selected)

  useLayoutEffect(() => {
    if (!open || selected < 0) return
    const menu = menuRef.current
    const option = optionRefs.current[selected]
    if (!menu || !option) return
    menu.scrollTop = Math.max(0, option.offsetTop - (menu.clientHeight - option.offsetHeight) / 2)
  }, [open, selected])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus({ preventScroll: true })
      }
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  const choose = (index: number) => {
    const option = props.options[index]
    if (!option) return
    setOpen(false)
    props.onChange(option.value)
    triggerRef.current?.focus({ preventScroll: true })
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) {
        setOpen(true)
        setActive(selected >= 0 ? selected : 0)
      } else {
        setActive((activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + props.options.length) % props.options.length)
      }
    } else if (event.key === 'Home' && open) {
      event.preventDefault()
      setActive(0)
    } else if (event.key === 'End' && open) {
      event.preventDefault()
      setActive(props.options.length - 1)
    } else if ((event.key === 'Enter' || event.key === ' ') && open) {
      event.preventDefault()
      choose(activeIndex)
    }
  }

  return (
    <div ref={rootRef} className={`glide-select${open ? ' is-open' : ''}${props.className ? ` ${props.className}` : ''}`}>
      <button
        ref={triggerRef}
        type="button"
        className="glide-select-trigger"
        role="combobox"
        aria-label={props.ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-activedescendant={open ? `${id}-option-${activeIndex}` : undefined}
        onClick={() => { setOpen((value) => !value); setActive(selected >= 0 ? selected : 0) }}
        onKeyDown={onKeyDown}
      >
        <span className="glide-select-trigger-label">{props.options[selected]?.label ?? '选择…'}</span>
        <Icon name="chevron-down" size={13} className="glide-select-chevron" />
      </button>
      {open && (
        <div ref={menuRef} className="glide-select-menu" data-state="open">
          <div
            id={`${id}-list`}
            className="glide-select-list"
            role="listbox"
            aria-label={props.ariaLabel}
            onPointerMove={(event) => {
              if (event.pointerType === 'touch') return
              const target = (event.target as HTMLElement).closest<HTMLElement>('[data-glide-index]')
              if (target) setActive(Number(target.dataset.glideIndex))
            }}
          >
            <span className="glide-select-pill" style={{ transform: `translateY(calc(var(--gs-row-pitch, 42px) * ${activeIndex}))` }} aria-hidden="true" />
            {props.options.map((option, index) => (
              <div key={option.value} className="glide-select-row" data-glide-index={index}>
                <button
                  ref={(element) => { optionRefs.current[index] = element }}
                  id={`${id}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={props.value === option.value}
                  className="glide-select-option"
                  onFocus={() => setActive(index)}
                  onClick={() => choose(index)}
                >
                  <span className="glide-select-option-copy">
                    <span className="glide-select-option-title">{option.label}</span>
                    {option.description && <span className="glide-select-option-desc">{option.description}</span>}
                  </span>
                  <Icon name="check" size={14} className="glide-select-check" />
                </button>
                {props.renderOptionActions && <span className="glide-select-option-actions">{props.renderOptionActions(option.value)}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
