// 主题独立于 App 全局状态：切换只重绘用到主题的小组件，避免整页重渲染打断扩散动画。

import { useSyncExternalStore } from 'react'
import { api } from './api'

export type Theme = 'light' | 'dark'

let current: Theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
const listeners = new Set<() => void>()

export function applyTheme(next: Theme) {
  if (next === current) return
  current = next
  document.documentElement.dataset.theme = next
  for (const listener of listeners) listener()
}

export function initTheme(value: Theme | undefined) {
  applyTheme(value === 'dark' ? 'dark' : 'light')
}

export function nextTheme(): Theme {
  return current === 'dark' ? 'light' : 'dark'
}

export function persistTheme(next: Theme) {
  void api.setSettings({ theme: next }).catch((err: unknown) => {
    console.error('保存设置失败', err)
  })
}

export function setTheme(next: Theme) {
  applyTheme(next)
  persistTheme(next)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, () => current, () => current)
}
