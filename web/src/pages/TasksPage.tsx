import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, Horizon, onTasksChanged, RepeatRule, Task } from '../api'
import { Button, Icon, Pill, Segmented, Toggle } from '../ui'
import SpotlightCard from '../components/SpotlightCard'
import Calendar from '../components/Calendar'
import GlideSelect from '../components/GlideSelect'
import { fetchCached, invalidateCache, isFresh, readCache } from '../queryCache'
import {
  defaultDueInput, formatDue, fromLocalInput, HORIZON_LABELS, HORIZON_OPTIONS, isOverdue, isTimed, isToday,
  REPEAT_LABELS, REPEAT_OPTIONS, toLocalInput,
} from '../tasks'

type Mode = 'pending' | 'done'
type Period = 'all' | 'today' | 'overdue' | 'future' | 'week' | 'month' | 'someday'

const PERIOD_OPTIONS: { key: Period; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'today', label: '今天' },
  { key: 'overdue', label: '逾期' },
  { key: 'future', label: '未来' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
  { key: 'someday', label: '待安排' },
]

export default function TasksPage(props: {
  startNew?: number
  onStartNewConsumed: () => void
  density: 'comfortable' | 'compact'
  onDensity: (density: 'comfortable' | 'compact') => void
  active?: boolean
}) {
  const [mode, setMode] = useState<Mode>('pending')
  const [pendingRows, setPendingRows] = useState<Task[]>(() => readCache<Task[]>('tasks.pending') ?? [])
  const [historyRows, setHistoryRows] = useState<Task[]>(() => readCache<Task[]>('tasks.done') ?? [])
  const [initialLoading, setInitialLoading] = useState(() => !readCache<Task[]>('tasks.pending'))
  const [refreshing, setRefreshing] = useState(false)
  const [search, setSearch] = useState('')
  const [period, setPeriod] = useState<Period>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [editor, setEditor] = useState<{ task: Task | null } | null>(null)
  const [lastDeleted, setLastDeleted] = useState<string[]>([])
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const pending = readCache<Task[]>('tasks.pending')
    const history = readCache<Task[]>('tasks.done')
    if (pending) { setPendingRows(pending); setInitialLoading(false) }
    if (history) { setHistoryRows(history); setInitialLoading(false) }
  }, [])

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setRefreshing(true)
    try {
      const [pending, history] = await Promise.all([
        fetchCached('tasks.pending', api.tasksList),
        fetchCached('tasks.done', () => api.tasksHistory('done', '')),
      ])
      setPendingRows(pending)
      setHistoryRows(history)
      setInitialLoading(false)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '读取任务失败')
      setInitialLoading(false)
    } finally {
      if (!quiet) setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (!props.active) return
    const cachedPending = readCache<Task[]>('tasks.pending')
    const cachedHistory = readCache<Task[]>('tasks.done')
    if (cachedPending) setPendingRows(cachedPending)
    if (cachedHistory) setHistoryRows(cachedHistory)

    // Keep the visible list stable when returning to this page. Refresh only
    // after the shared cache has expired; task events below invalidate it.
    if (!isFresh('tasks.pending', 20_000) || !isFresh('tasks.done', 20_000)) {
      void load(true)
    }

    const offTasks = onTasksChanged(() => {
      invalidateCache('tasks.pending')
      invalidateCache('tasks.done')
      invalidateCache('tasks.stats')
      invalidateCache('tasks.today-events')
      void load(true)
    })
    return offTasks
  }, [load, props.active])

  useEffect(() => {
    setSelected(new Set())
    setEditor(null)
  }, [mode])

  useEffect(() => {
    if (!props.startNew) return
    setMode('pending')
    setEditor({ task: null })
    props.onStartNewConsumed()
  }, [props.startNew])

  useEffect(() => {
    if (!editor) return
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setEditor(null)
      if (event.key !== 'Tab') return
      const dialog = document.querySelector<HTMLElement>('.task-editor-modal')
      const focusable = dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])')
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus()
    }
  }, [editor])

  const act = async (label: string, run: () => Promise<unknown>) => {
    try {
      await run()
      setNotice('')
      ;['tasks.pending', 'tasks.done', 'tasks.stats', 'tasks.today-events'].forEach(invalidateCache)
      await load()
    } catch (err) {
      setNotice(`${label}失败：${err instanceof Error ? err.message : '请重试'}`)
      ;['tasks.pending', 'tasks.done', 'tasks.stats', 'tasks.today-events'].forEach(invalidateCache)
      await load()
    }
  }

  const term = search.trim().toLowerCase()
  const rows = (mode === 'pending' ? pendingRows : historyRows).filter((task) => {
    if (term && !task.title.toLowerCase().includes(term)) return false
    if (mode !== 'pending') return true
    if (period === 'today') return isTimed(task) && isToday(task)
    if (period === 'overdue') return isOverdue(task)
    if (period === 'future') return isTimed(task) && new Date(task.due_at).getTime() > Date.now()
    if (period === 'week') return task.horizon === 'week'
    if (period === 'month') return task.horizon === 'month'
    if (period === 'someday') return task.horizon === 'someday'
    return true
  })

  const groups = useMemo(() => {
    if (mode === 'done') return [{ label: `已完成 ${rows.length} 项`, tone: '', rows }]
    const overdue = rows.filter(isOverdue)
    const rest = rows.filter((task) => !isOverdue(task))
    const timed = rest.filter(isTimed)
    const today = timed.filter(isToday)
    const future = timed.filter((task) => !isToday(task))
    const week = rest.filter((task) => task.horizon === 'week')
    const month = rest.filter((task) => task.horizon === 'month')
    const someday = rest.filter((task) => task.horizon === 'someday')
    return [
      { label: '逾期 · 需要你回应', tone: 'alert', rows: overdue },
      { label: `今天 ${today.length} 项`, tone: '', rows: today },
      { label: `接下来 ${future.length} 项`, tone: '', rows: future },
      { label: `本周 ${week.length} 项`, tone: '', rows: week },
      { label: `本月 ${month.length} 项`, tone: '', rows: month },
      { label: `待安排 ${someday.length} 项`, tone: '', rows: someday },
    ].filter((group) => group.rows.length > 0)
  }, [mode, rows])

  const togglePick = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const runSelected = async (label: string, run: (id: string) => Promise<unknown>) => {
    const ids = [...selected]
    if (ids.length === 0) return
    try {
      for (const id of ids) await run(id)
      setSelected(new Set())
      setNotice('')
      ;['tasks.pending', 'tasks.done', 'tasks.stats', 'tasks.today-events'].forEach(invalidateCache)
    } catch (err) {
      setNotice(`${label}失败：${err instanceof Error ? err.message : '请重试'}`)
    }
    await load()
  }

  const removeMany = async (ids: string[]) => {
    if (ids.length === 0) return
    try {
      for (const id of ids) await api.taskDelete(id)
      ;['tasks.pending', 'tasks.done', 'tasks.stats', 'tasks.today-events'].forEach(invalidateCache)
      setLastDeleted(ids)
      setSelected(new Set())
      setNotice('')
    } catch (err) {
      setNotice(`删除失败：${err instanceof Error ? err.message : '请重试'}`)
    }
    await load()
  }

  const undoDelete = async () => {
    const ids = lastDeleted
    setLastDeleted([])
    try {
      for (const id of ids) await api.taskUndoDelete(id)
      ;['tasks.pending', 'tasks.done', 'tasks.stats', 'tasks.today-events'].forEach(invalidateCache)
      setNotice('已恢复删除的待办。')
    } catch (err) {
      setNotice(`撤销失败：${err instanceof Error ? err.message : '请重试'}`)
    }
    await load()
  }

  return (
    <div className={`tasks${props.density === 'compact' ? ' compact' : ''}`}>
      <header className="page-head">
        <div className="page-head-main">
          <div className="eyebrow tasks-eyebrow">YOUR RHYTHM　/　任务节奏</div>
          <div className="page-title-row">
            <h1 className="page-title">待办事项</h1>
            <span className="page-sub-inline">单击选择 · 双击编辑</span>
          </div>
        </div>
        <div className="page-head-side">
          <Segmented
            options={[{ key: 'comfortable', label: '宽松' }, { key: 'compact', label: '紧凑' }]}
            value={props.density}
            onChange={props.onDensity}
            ariaLabel="列表密度"
          />
          <span className="head-divider" aria-hidden />
          <Button primary onClick={() => setEditor({ task: null })}>
            <Icon name="plus" size={15} />新增待办
          </Button>
        </div>
      </header>

      <div className="task-toolbar">
        <GlideSelect
          className="task-mode-select"
          ariaLabel="切换待办状态"
          value={mode}
          options={[
            { value: 'pending', label: `未完成 ${pendingRows.length} 项` },
            { value: 'done', label: `已完成 ${historyRows.length} 项` },
          ]}
          onChange={(value) => setMode(value as Mode)}
        />
        {mode === 'pending' ? (
          <Segmented
            className="task-periods"
            variant="compact"
            ariaLabel="按时间筛选"
            options={PERIOD_OPTIONS}
            value={period}
            onChange={setPeriod}
          />
        ) : <span className="task-sort-note">最近完成</span>}
        <div className="search">
          <span className="search-ico"><Icon name="search" size={14} /></span>
          <input
            className="field"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索待办标题"
            aria-label="搜索待办标题"
          />
          {search && <button type="button" className="search-clear" aria-label="清除搜索" onClick={() => setSearch('')}><Icon name="x" size={13} /></button>}
        </div>
        <span className="filter-count">
          {mode === 'pending' ? `${rows.length} 项未完成` : `${rows.length} 项已完成`}
        </span>
        {refreshing && !initialLoading && <span className="page-refresh-indicator"><i />正在同步</span>}
      </div>

      {lastDeleted.length > 0 && (
        <div className="bulkbar">
          <span className="label">已删除 {lastDeleted.length} 项（可在本次会话内撤销）</span>
          <Button small onClick={() => void undoDelete()}>撤销</Button>
          <Button small ghost onClick={() => setLastDeleted([])}>忽略</Button>
        </div>
      )}

      {editor && createPortal((
        <div
          className="task-modal-backdrop"
          role="presentation"
          onPointerDown={(event) => { if (event.target === event.currentTarget) setEditor(null) }}
        >
          <TaskEditor
            key={editor.task?.id ?? 'new'}
            initial={editor.task}
            onCancel={() => setEditor(null)}
            onSaved={async () => {
              setEditor(null)
              setNotice('')
              ;['tasks.pending', 'tasks.done', 'tasks.stats', 'tasks.today-events'].forEach(invalidateCache)
              await load()
            }}
          />
        </div>
      ), document.body)}

      {notice && <p className="status-line alert">{notice}</p>}

      {initialLoading ? (
        <div className="page-skeleton task-skeleton" aria-label="正在加载待办">
          <span /><span /><span />
        </div>
      ) : rows.length === 0 ? (
        <div className="card empty-card">
          <span className="empty-icon"><Icon name={mode === 'pending' ? 'list' : 'check-circle'} size={18} /></span>
          <p className="empty-title">{mode === 'pending' ? '这个筛选下没有待办' : '还没有已完成的记录'}</p>
          <p className="empty-desc">{mode === 'pending' ? '换个筛选，或者新建一件事。' : '完成的任务会出现在这里。'}</p>
        </div>
      ) : (
        groups.map((group) => (
          <section key={group.label} className="group">
            <div className={`group-label${group.tone === 'alert' ? ' alert' : ''}`}>{group.label}</div>
            {group.rows.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                mode={mode}
                picked={selected.has(task.id)}
                onPick={() => togglePick(task.id)}
                onEdit={() => setEditor({ task })}
                onSnooze={() => void act('顺延', () => api.taskSnooze(task.id, 10))}
                onComplete={() => void act('完成', () => api.taskComplete(task.id))}
                onReopen={() => void act('重新打开', () => api.taskReopen(task.id))}
                onDelete={() => void removeMany([task.id])}
              />
            ))}
          </section>
        ))
      )}

      {selected.size > 0 && (
        <div className="bulkbar">
          <span className="label">已选 {selected.size} 项</span>
          {mode === 'pending' ? (
            <>
              <Button primary small onClick={() => void runSelected('批量完成', (id) => api.taskComplete(id))}>完成</Button>
              <Button small onClick={() => void runSelected('批量顺延', (id) => api.taskSnooze(id, 10))}>顺延 10 分</Button>
            </>
          ) : (
            <Button small onClick={() => void runSelected('批量重新打开', (id) => api.taskReopen(id))}>重新打开</Button>
          )}
          <Button small danger onClick={() => void removeMany([...selected])}>删除</Button>
          <Button small ghost onClick={() => setSelected(new Set())}>取消</Button>
        </div>
      )}
    </div>
  )
}

function TaskRow(props: {
  task: Task
  mode: Mode
  picked: boolean
  onPick: () => void
  onEdit: () => void
  onSnooze: () => void
  onComplete: () => void
  onReopen: () => void
  onDelete: () => void
}) {
  const { task, mode } = props
  const overdue = isOverdue(task)
  const done = mode === 'done'
  const deferred = !done && task.deferred === 1
  const someday = task.horizon === 'someday'
  const bucket = task.horizon === 'week' || task.horizon === 'month'
  const soon = !done && !overdue && !deferred && isTimed(task)
    && new Date(task.due_at).getTime() - Date.now() <= 30 * 60000
  const sub = metaText(task)
  return (
    <SpotlightCard className={`task-row${overdue ? ' is-overdue' : ''}${done ? ' is-done' : ''}${props.picked ? ' is-picked' : ''}`}>
      <button
        type="button"
        className={`check${done ? ' done' : ''}`}
        aria-pressed={done}
        aria-label={done ? '重新打开' : '完成'}
        title={done ? '重新打开' : '标记完成'}
        onClick={done ? props.onReopen : props.onComplete}
      >
        <Icon name="check" size={11} />
      </button>
      <div className="task-time">
        <small>{someday ? '收集箱' : dayLabel(task.due_at as string)}</small>
        {someday ? '待整理' : bucket ? '截止' : formatClock(task.due_at)}
      </div>
      <button
        type="button"
        className="task-main task-main-button"
        aria-pressed={props.picked}
        onClick={props.onPick}
        onDoubleClick={props.onEdit}
        title="单击选择，双击编辑"
      >
        <div className="task-title">{task.title}</div>
        {sub && <div className="task-sub">{sub}</div>}
      </button>
      <div className="task-side" onClick={(e) => e.stopPropagation()}>
        {Boolean(task.dingtalk) && <Pill tone="info"><Icon name="send" size={11} />钉钉</Pill>}
        {(task.source === 'chat' || task.source === 'draft') && (
          <Pill tone="brand"><Icon name="chat" size={11} />来自对话</Pill>
        )}
        {done ? (
          <Pill tone="calm"><Icon name="check" size={11} />已完成</Pill>
        ) : deferred ? (
          <Pill tone="caution"><Icon name="clock" size={11} />已延期</Pill>
        ) : overdue ? (
          <Pill tone="danger"><Icon name="alert" size={11} />{overdueText(task.due_at as string)}</Pill>
        ) : someday ? (
          <Pill tone="plain"><Icon name="list" size={11} />待安排</Pill>
        ) : bucket ? (
          <Pill tone="plain"><Icon name="calendar" size={11} />{task.horizon === 'week' ? '本周内' : '本月内'}</Pill>
        ) : (
          <Pill tone={soon ? 'caution' : 'plain'}>
            <Icon name="clock" size={11} />{dueChip(task.due_at as string)}
          </Pill>
        )}
        <div className="task-actions">
          {!done && (
            <>
              {!someday && (
                <button
                  type="button"
                  className="task-action"
                  data-warm-tooltip="十分钟后提醒"
                  title="十分钟后提醒"
                  aria-label="十分钟后提醒"
                  onClick={props.onSnooze}
                >
                  <Icon name="clock" size={14} />
                </button>
              )}
              <button
                type="button"
                className="task-action"
                data-warm-tooltip="编辑"
                title="编辑"
                aria-label="编辑待办"
                onClick={props.onEdit}
              >
                <Icon name="edit" size={14} />
              </button>
            </>
          )}
          <button
            type="button"
            className="task-action danger"
            data-warm-tooltip="删除"
            title="删除"
            aria-label="删除待办"
            onClick={props.onDelete}
          >
            <Icon name="trash" size={14} />
          </button>
        </div>
      </div>
    </SpotlightCard>
  )
}

function TaskEditor(props: {
  initial: Task | null
  onCancel: () => void
  onSaved: () => void | Promise<void>
}) {
  const [title, setTitle] = useState(props.initial?.title ?? '')
  const [horizon, setHorizon] = useState<Horizon>(props.initial?.horizon ?? 'timed')
  const [due, setDue] = useState(props.initial?.due_at ? toLocalInput(props.initial.due_at) : defaultDueInput())
  const [repeat, setRepeat] = useState<RepeatRule>(props.initial?.repeat_rule ?? 'none')
  const [dingtalk, setDingtalk] = useState(Boolean(props.initial?.dingtalk))
  const [note, setNote] = useState(props.initial?.note ?? '')
  const [quick, setQuick] = useState('')
  const [hint, setHint] = useState<{ tone: 'plain' | 'calm' | 'alert'; text: string }>({ tone: 'plain', text: '' })
  const [saving, setSaving] = useState(false)
  const [calendarOpen, setCalendarOpen] = useState(false)
  const titleRef = useRef<HTMLInputElement>(null)
  const calendarRef = useRef<HTMLDivElement>(null)
  const selectedDate = new Date(`${due}:00`)
  const dateLabel = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(selectedDate)

  const setDueDate = (date: Date) => {
    const datePart = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    setDue(`${datePart}T${due.slice(11, 16) || '09:00'}`)
  }

  useEffect(() => { titleRef.current?.focus() }, [])

  useEffect(() => {
    if (!calendarOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (!calendarRef.current?.contains(event.target as Node)) setCalendarOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [calendarOpen])

  useEffect(() => {
    const text = quick.trim()
    if (!text) {
      setHint({ tone: 'plain', text: '' })
      return
    }
    let alive = true
    const timer = window.setTimeout(() => {
      api.taskParseDue(text).then((parsed) => {
        if (!alive) return
        setDue(toLocalInput(parsed.dueAt))
        if (parsed.repeat !== 'none') setRepeat(parsed.repeat)
        const repeatText = parsed.repeat === 'none' ? '' : ` · ${REPEAT_LABELS[parsed.repeat]}`
        setHint({
          tone: parsed.past ? 'alert' : 'calm',
          text: `${parsed.past ? '这个时间已过去：' : '已解析为 '}${formatDue(parsed.dueAt)}${repeatText}`,
        })
      }).catch((err: unknown) => {
        if (alive) setHint({ tone: 'alert', text: err instanceof Error ? err.message : '无法解析这段描述' })
      })
    }, 400)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [quick])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!title.trim()) {
      setHint({ tone: 'alert', text: '请填写待办标题。' })
      return
    }
    setSaving(true)
    try {
      const timed = horizon === 'timed'
      if (props.initial) {
        await api.taskEdit({
          id: props.initial.id,
          title: title.trim(),
          horizon,
          ...(timed ? { dueAt: fromLocalInput(due), repeat } : {}),
          dingtalk,
        })
      } else {
        await api.taskAdd({
          title: title.trim(),
          horizon,
          ...(timed ? { dueAt: fromLocalInput(due), repeat } : {}),
          dingtalk,
          note: note.trim(),
        })
      }
      await props.onSaved()
    } catch (err) {
      setHint({ tone: 'alert', text: err instanceof Error ? err.message : '保存失败，请重试。' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="editor task-editor-modal" role="dialog" aria-modal="true" aria-labelledby="task-editor-title" onSubmit={(event) => void submit(event)}>
      <div className="editor-head">
        <span className="task-editor-mark"><Icon name={props.initial ? 'edit' : 'plus'} size={16} /></span>
        <div className="task-editor-heading">
          <h2 id="task-editor-title">{props.initial ? '编辑待办' : '新建待办'}</h2>
          <p>{props.initial ? '调整时间和提醒方式' : '先记下来，提醒时间可以随时修改'}</p>
        </div>
        <button type="button" className="task-modal-close" aria-label="关闭" onClick={props.onCancel}><Icon name="x" size={16} /></button>
      </div>
      <label>
        <span className="field-label">标题</span>
        <input
          className="field"
          ref={titleRef}
          autoFocus
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="要做的事"
        />
      </label>
      <div className="task-horizon-section">
        <span className="field-label task-section-label">期限</span>
        <Segmented options={HORIZON_OPTIONS} value={horizon} onChange={setHorizon} ariaLabel="任务期限" />
      </div>
      {horizon === 'timed' ? <>
      <div className="task-datetime-section">
        <span className="field-label task-section-label">提醒时间</span>
        <div className="task-date-control" ref={calendarRef}>
          <button
            type="button"
            className="task-date-trigger"
            aria-label={`选择日期，当前${dateLabel}`}
            aria-haspopup="dialog"
            aria-expanded={calendarOpen}
            onClick={() => setCalendarOpen((open) => !open)}
          >
            <Icon name="calendar" size={14} />
            <span>{dateLabel}</span>
            <Icon name="chevron-down" size={12} className="task-date-chevron" />
          </button>
          {calendarOpen && (
            <div className="task-calendar-popover" role="dialog" aria-label="选择提醒日期">
              <Calendar selected={selectedDate} onSelect={(date) => { setDueDate(date); setCalendarOpen(false) }} />
            </div>
          )}
        </div>
        <div className="task-time-picker">
          <div className="task-time-column">
            <span className="task-time-column-label">时</span>
            <GlideSelect
              className="task-time-select"
              ariaLabel="选择小时"
              value={due.slice(11, 13)}
              options={Array.from({ length: 24 }, (_, hour) => {
                const value = String(hour).padStart(2, '0')
                return { value, label: value }
              })}
              onChange={(hour) => setDue(`${due.slice(0, 10)}T${hour}:${due.slice(14, 16)}`)}
            />
          </div>
          <span className="task-time-separator">:</span>
          <div className="task-time-column">
            <span className="task-time-column-label">分</span>
            <GlideSelect
              className="task-time-select"
              ariaLabel="选择分钟"
              value={due.slice(14, 16)}
              options={Array.from({ length: 60 }, (_, minute) => {
                const value = String(minute).padStart(2, '0')
                return { value, label: value }
              })}
              onChange={(minute) => setDue(`${due.slice(0, 10)}T${due.slice(11, 13)}:${minute}`)}
            />
          </div>
        </div>
      </div>
      <label className="task-quick-time">
        <span className="field-label">一句话快速填写 <span className="optional-label">可选</span></span>
        <input
          className="field"
          value={quick}
          onChange={(e) => setQuick(e.target.value)}
          placeholder="试试：明天 9:30 开会 / 2 小时后喝水"
        />
      </label>
      {hint.text && (
        <p className={`status-line${hint.tone !== 'plain' ? ` ${hint.tone}` : ''}`}>{hint.text}</p>
      )}
      </> : (
        <p className="status-line calm">{horizonHint(horizon)}</p>
      )}
      {!props.initial && (
        <label>
          <span className="field-label">备注 <span className="optional-label">可选</span></span>
          <textarea className="field task-note-field" value={note} maxLength={1000} rows={3} onChange={(e) => setNote(e.target.value)} placeholder="补充一些上下文…" />
        </label>
      )}
      <div className="editor-settings">
        {horizon === 'timed' && (
          <div>
            <span className="field-label">重复</span>
            <Segmented options={REPEAT_OPTIONS} value={repeat} onChange={setRepeat} />
          </div>
        )}
        <Toggle label="推送到钉钉" checked={dingtalk} onChange={setDingtalk} />
      </div>
      <div className="task-editor-footer">
        <span className="task-editor-shortcut"><kbd>Esc</kbd> 关闭</span>
        <span className="spacer" />
        <Button onClick={props.onCancel}>取消</Button>
        <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? '保存中…' : '保存待办'}</button>
      </div>
    </form>
  )
}

function dayLabel(iso: string): string {
  const date = new Date(iso)
  return `${String(date.getMonth() + 1).padStart(2, '0')}月${String(date.getDate()).padStart(2, '0')}日`
}

function dueChip(iso: string): string {
  const date = new Date(iso)
  const now = new Date()
  const start = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime()
  const days = Math.round((start(date) - start(now)) / 86400000)
  if (days === 0) return `今天 ${formatClock(iso)}`
  if (days === 1) return `明天 ${formatClock(iso)}`
  if (days > 1) return `${days} 天后`
  return `${dayLabel(iso)} ${formatClock(iso)}`
}

function overdueText(iso: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000))
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours) return `逾期 ${hours}小时${rest}分`
  if (minutes) return `逾期 ${minutes}分`
  return '逾期 刚刚'
}

function metaText(task: Task): string {
  const parts: string[] = []
  const horizon = task.horizon ?? 'timed'
  if (horizon === 'timed') {
    if (task.repeat_rule !== 'none') parts.push(REPEAT_LABELS[task.repeat_rule])
  } else if (HORIZON_LABELS[horizon]) {
    parts.push(HORIZON_LABELS[horizon])
  }
  if (task.status === 'done') {
    if (task.completed_at) {
      if (task.due_at) {
        const minutes = Math.floor(
          (new Date(task.due_at).getTime() - new Date(task.completed_at).getTime()) / 60000,
        )
        const tail = minutes > 0
          ? `提前 ${minutes} 分钟`
          : minutes < 0 ? `晚 ${Math.abs(minutes)} 分钟` : '准点'
        parts.push(`${formatClock(task.completed_at)} 完成，${tail}`)
      } else {
        parts.push(`${formatClock(task.completed_at)} 完成`)
      }
    }
  } else if (task.early_notified_at) {
    parts.push('提前 10 分钟提醒')
  } else if (task.deferred === 1) {
    parts.push('提醒已达上限')
  } else if (isOverdue(task) && task.remind_count > 0) {
    parts.push(`已提醒 ${task.remind_count} 次`)
  }
  if (task.source === 'chat' || task.source === 'draft') {
    const stamp = task.created_at || task.due_at
    if (stamp) parts.push(`由对话创建 ${formatClock(stamp)}`)
  }
  const note = task.note.trim()
  if (note) parts.push(`备注：${note}`)
  return parts.join(' · ')
}

function horizonHint(horizon: Horizon): string {
  if (horizon === 'week') return '本周内完成：周五 17:00 提醒你，周日结束前完成即可。'
  if (horizon === 'month') return '本月内完成：最后一个工作日下午 5 点提醒你，月末前完成即可。'
  return '放入待安排：没有时间压力，每周五下午会提醒你回顾整理。'
}

function formatClock(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
