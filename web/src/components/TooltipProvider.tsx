import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

type TooltipState = {
  target: HTMLElement
  text: string
  x: number
  y: number
  width: number
  height: number
  placement: 'top' | 'bottom'
  warm: boolean
}

const TOOLTIP_ID = 'app-tooltip'

/** Replaces native title bubbles throughout the app with one styled tooltip. */
export default function TooltipProvider() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  useEffect(() => {
    let showTimer = 0
    let closeTimer = 0
    let showFrame = 0
    let showRevision = 0
    let activeTarget: HTMLElement | null = null
    let warmUntil = 0
    const measureCanvas = document.createElement('canvas')
    const measureContext = measureCanvas.getContext('2d')

    const upgrade = (node: Node) => {
      if (!(node instanceof HTMLElement)) return
      const candidates = [node, ...node.querySelectorAll<HTMLElement>('[title]')]
      for (const element of candidates) {
        const title = element.getAttribute('title')
        if (title?.trim()) {
          element.dataset.appTooltip = title.trim()
          if (element === activeTarget) refresh(element)
        }
        if (title !== null) element.removeAttribute('title')
      }
    }

    const findTarget = (node: EventTarget | null) => {
      if (!(node instanceof Element)) return null
      // Prefer the explicit interactive control. This keeps tooltips anchored to
      // individual icons even when they sit inside nested/animated row wrappers.
      return node.closest<HTMLElement>('[data-warm-tooltip]')
        ?? node.closest<HTMLElement>('[data-app-tooltip]')
    }

    const tooltipText = (target: HTMLElement) =>
      target.dataset.warmTooltip?.trim() || target.dataset.appTooltip?.trim() || ''

    const hide = (keepWarm = false) => {
      showRevision += 1
      window.clearTimeout(showTimer)
      window.clearTimeout(closeTimer)
      window.cancelAnimationFrame(showFrame)
      if (activeTarget) {
        const ids = activeTarget.getAttribute('aria-describedby')?.split(/\s+/).filter((id) => id && id !== TOOLTIP_ID)
        if (ids?.length) activeTarget.setAttribute('aria-describedby', ids.join(' '))
        else activeTarget.removeAttribute('aria-describedby')
      }
      if (keepWarm) warmUntil = performance.now() + 320
      activeTarget = null
      setTooltip(null)
    }

    const refresh = (target: HTMLElement, warm = false) => {
      const text = tooltipText(target)
      if (!target.isConnected || !text) return
      const rect = target.getBoundingClientRect()
      const family = getComputedStyle(document.body).fontFamily
      if (measureContext) measureContext.font = `500 11.5px ${family}`
      const width = Math.min(Math.ceil((measureContext?.measureText(text).width ?? 70) + 22), window.innerWidth - 24)
      const height = 29
      const halfWidth = width / 2
      const centerX = rect.left + rect.width / 2
      const x = Math.max(halfWidth + 8, Math.min(window.innerWidth - halfWidth - 8, centerX))
      const placement = rect.top >= 56 || window.innerHeight - rect.bottom < 46 ? 'top' : 'bottom'
      const y = placement === 'top' ? rect.top - 7 : rect.bottom + 7
      const describedBy = target.getAttribute('aria-describedby')?.split(/\s+/).filter(Boolean) ?? []
      if (!describedBy.includes(TOOLTIP_ID)) describedBy.push(TOOLTIP_ID)
      target.setAttribute('aria-describedby', describedBy.join(' '))
      setTooltip({ target, text, x, y, width, height, placement, warm })
    }

    const show = (target: HTMLElement, delay: number) => {
      const revision = ++showRevision
      window.clearTimeout(showTimer)
      window.clearTimeout(closeTimer)
      window.cancelAnimationFrame(showFrame)
      if (activeTarget && activeTarget !== target) {
        const ids = activeTarget.getAttribute('aria-describedby')?.split(/\s+/).filter((id) => id && id !== TOOLTIP_ID)
        if (ids?.length) activeTarget.setAttribute('aria-describedby', ids.join(' '))
        else activeTarget.removeAttribute('aria-describedby')
      }
      activeTarget = target
      const display = () => {
        if (revision !== showRevision || activeTarget !== target || !target.isConnected) return
        showFrame = window.requestAnimationFrame(() => {
          if (revision !== showRevision || activeTarget !== target || !target.isConnected) return
          refresh(target, performance.now() < warmUntil && Boolean(document.getElementById(TOOLTIP_ID)))
        })
      }
      const wait = performance.now() < warmUntil ? 0 : delay
      if (wait) showTimer = window.setTimeout(display, wait)
      else display()
    }

    const onPointerOver = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      const target = findTarget(event.target)
      if (!target || target === activeTarget) return
      show(target, 360)
    }
    const onPointerOut = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      const target = findTarget(event.target)
      if (!target || target !== activeTarget) return
      if (event.relatedTarget instanceof Node && target.contains(event.relatedTarget)) return
      window.clearTimeout(showTimer)
      warmUntil = performance.now() + 320
      closeTimer = window.setTimeout(() => hide(), 130)
    }
    const onFocusIn = (event: FocusEvent) => {
      const target = findTarget(event.target)
      if (target) show(target, 0)
    }
    const onFocusOut = (event: FocusEvent) => {
      if (findTarget(event.target) === activeTarget) hide()
    }
    const onViewportChange = () => {
      if (activeTarget) refresh(activeTarget)
    }

    upgrade(document.body)
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === 'attributes') upgrade(record.target)
        else record.addedNodes.forEach(upgrade)
      }
      if (activeTarget && !activeTarget.isConnected) hide()
    })
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['title'],
    })
    document.addEventListener('pointerover', onPointerOver, true)
    document.addEventListener('pointerout', onPointerOut, true)
    document.addEventListener('focusin', onFocusIn, true)
    document.addEventListener('focusout', onFocusOut, true)
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('scroll', onViewportChange, true)

    return () => {
      observer.disconnect()
      document.removeEventListener('pointerover', onPointerOver, true)
      document.removeEventListener('pointerout', onPointerOut, true)
      document.removeEventListener('focusin', onFocusIn, true)
      document.removeEventListener('focusout', onFocusOut, true)
      window.removeEventListener('resize', onViewportChange)
      window.removeEventListener('scroll', onViewportChange, true)
      window.clearTimeout(showTimer)
      window.clearTimeout(closeTimer)
      window.cancelAnimationFrame(showFrame)
      if (activeTarget) {
        const ids = activeTarget.getAttribute('aria-describedby')?.split(/\s+/).filter((id) => id && id !== TOOLTIP_ID)
        if (ids?.length) activeTarget.setAttribute('aria-describedby', ids.join(' '))
        else activeTarget.removeAttribute('aria-describedby')
      }
    }
  }, [])

  if (!tooltip) return null
  const style = {
    left: `${tooltip.x}px`,
    top: `${tooltip.y}px`,
    width: `${tooltip.width}px`,
    height: `${tooltip.height}px`,
  }

  return createPortal(
    <div
      id={TOOLTIP_ID}
      role="tooltip"
      className={`app-tooltip app-tooltip-${tooltip.placement}${tooltip.warm ? ' app-tooltip-warm' : ''}`}
      style={style}
    >
      <span key={tooltip.text} className="app-tooltip-content">{tooltip.text}</span>
    </div>,
    document.body,
  )
}
