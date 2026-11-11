// Display helpers shared by the home/tasks pages; bridge payloads stay snake_case.
import { RepeatRule, Task } from './api'

export const REPEAT_OPTIONS: { key: RepeatRule; label: string }[] = [
  { key: 'none', label: '不重复' },
  { key: 'daily', label: '每天' },
  { key: 'weekdays', label: '工作日' },
  { key: 'weekly', label: '每周' },
]

export const REPEAT_LABELS: Record<RepeatRule, string> = {
  none: '',
  daily: '每天',
  weekdays: '工作日',
  weekly: '每周',
}

export const EVENT_LABELS: Record<string, string> = {
  created: '创建',
  reminded: '提醒',
  quiet: '静默',
  early: '提前提醒',
  muted: '今日免打扰',
  completed: '完成',
  deleted: '删除',
  restored: '恢复',
  reopened: '重新打开',
  edited: '编辑',
  snoozed: '顺延',
  auto_postponed: '自动顺延',
}

const pad = (value: number) => String(value).padStart(2, '0')

function startOfDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

export function toLocalInput(iso: string): string {
  const date = new Date(iso)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function fromLocalInput(value: string): string {
  return new Date(value).toISOString()
}

export function defaultDueInput(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000)
  date.setMinutes(Math.ceil(date.getMinutes() / 5) * 5, 0, 0)
  return toLocalInput(date.toISOString())
}

export function formatDue(iso: string): string {
  const date = new Date(iso)
  const days = Math.round((startOfDay(date) - startOfDay(new Date())) / 86400000)
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (days === 0) return `今天 ${clock}`
  if (days === 1) return `明天 ${clock}`
  if (days === -1) return `昨天 ${clock}`
  if (days > 1 && days < 7) return `周${'日一二三四五六'[date.getDay()]} ${clock}`
  return `${date.getMonth() + 1}月${date.getDate()}日 ${clock}`
}

export function formatClock(iso: string): string {
  const date = new Date(iso)
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function isOverdue(task: Task): boolean {
  return task.status === 'pending' && new Date(task.due_at).getTime() < Date.now()
}

export function isToday(task: Task): boolean {
  return startOfDay(new Date(task.due_at)) === startOfDay(new Date())
}
