import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, onTasksChanged, RepeatRule, Task } from '../api'
import { Button, Icon, Pill, Segmented, Toggle } from '../ui'
import {
  defaultDueInput, formatDue, fromLocalInput, isOverdue, isToday,
  REPEAT_LABELS, REPEAT_OPTIONS, toLocalInput,
} from '../tasks'

type Mode = 'pending' | 'done'
type Period = 'all' | 'today' | 'overdue' | 'future'

const PERIOD_OPTIONS: { key: Period; label: string }[] = [
  { key: 'all', label: '全部时间' },
  { key: 'today', label: '今天' },
  { key: 'overdue', label: '逾期' },
  { key: 'future', label: '未来' },
]

export default function TasksPage(props: {
  startNew?: number
  onStartNewConsumed: () => void
  density: 'comfortable' | 'compact'
  onDensity: (density: 'comfortable' | 'compact') => void
}) {
  const [mode, setMode] = useState<Mode>('pending')
  const [pendingRows, setPendingRows] = useState<Task[]>([])
  const [historyRows, setHistoryRows] = useState<Task[]>([])
  const [search, setSearch] = useState('')
  const [period, setPeriod] = useState<Period>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [editor, setEditor] = useState<{ task: Task | null } | null>(null)
  const [lastDeleted, setLastDeleted] = useState<string[]>([])
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    try {
      const [pending, history] = await Promise.all([api.tasksList(), api.tasksHistory('done', '')])
      setPendingRows(pending)
      setHistoryRows(history)
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '读取任务失败')
    }
  }, [])

  useEffect(() => {
    void load()
    return onTasksChanged(() => void load())
  }, [load])

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

  const act = async (label: string, run: () => Promise<unknown>) => {
    try {
      await run()
      setNotice('')
      await load()
    } catch (err) {
      setNotice(`${label}失败：${err instanceof Error ? err.message : '请重试'}`)
      await load()
    }
  }

  const term = search.trim().toLowerCase()
  const rows = (mode === 'pending' ? pendingRows : historyRows).filter((task) => {
    if (term && !task.title.toLowerCase().includes(term)) return false
    if (mode !== 'pending') return true
    if (period === 'today') return isToday(task)
    if (period === 'overdue') return isOverdue(task)
    if (period === 'future') return new Date(task.due_at).getTime() > Date.now()
    return true
  })

  const groups = useMemo(() => {
    if (mode === 'done') return [{ label: `已完成 ${rows.length} 项`, tone: '', rows }]
    const overdue = rows.filter(isOverdue)
    const today = rows.filter((task) => !isOverdue(task) && isToday(task))
    const future = rows.filter((task) => !isOverdue(task) && !isToday(task))
    return [
      { label: '逾期 · 需要你回应', tone: 'alert', rows: overdue },
      { label: `今天 ${today.length} 项`, tone: '', rows: today },
      { label: `接下来 ${future.length} 项`, tone: '', rows: future },
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
    } catch (err) {
      setNotice(`${label}失败：${err instanceof Error ? err.message : '请重试'}`)
    }
    await load()
  }

  const removeMany = async (ids: string[]) => {
    if (ids.length === 0) return
    try {
      for (const id of ids) await api.taskDelete(id)
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
          <div className="page-title-row">
            <h1 className="page-title">待办事项</h1>
            <span className="page-sub-inline">双击任意一条可改标题和提醒时间。</span>
          </div>
        </div>
        <div className="page-head-side">
          <Segmented
            options={[{ key: 'comfortable', label: '宽松' }, { key: 'compact', label: '紧凑' }]}
            value={props.density}
            onChange={props.onDensity}
          />
          <span className="head-divider" aria-hidden />
          <Button primary onClick={() => setEditor({ task: null })}>
            <Icon name="plus" size={15} />新增待办
          </Button>
        </div>
      </header>

      <div className="task-toolbar">
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            className="tab"
            aria-selected={mode === 'pending'}
            onClick={() => setMode('pending')}
          >
            未完成<span className="count">{pendingRows.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            className="tab"
            aria-selected={mode === 'done'}
            onClick={() => setMode('done')}
          >
            已完成<span className="count">{historyRows.length}</span>
          </button>
        </div>
        {mode === 'pending' ? (
          <select
            className="field select"
            value={period}
            aria-label="筛选时间"
            onChange={(e) => setPeriod(e.target.value as Period)}
          >
            {PERIOD_OPTIONS.map((option) => (
              <option key={option.key} value={option.key}>{option.label}</option>
            ))}
          </select>
        ) : (
          <span className="pill">按完成时间倒序</span>
        )}
        <div className="search">
          <span className="search-ico"><Icon name="search" size={14} /></span>
          <input
            className="field"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索待办标题"
          />
        </div>
        <span className="filter-count">
          {mode === 'pending' ? `${rows.length} 项未完成` : `${rows.length} 项已完成`}
        </span>
      </div>

      {lastDeleted.length > 0 && (
        <div className="bulkbar">
          <span className="label">已删除 {lastDeleted.length} 项（可在本次会话内撤销）</span>
          <Button small onClick={() => void undoDelete()}>撤销</Button>
          <Button small ghost onClick={() => setLastDeleted([])}>忽略</Button>
        </div>
      )}

      {editor && (
        <TaskEditor
          key={editor.task?.id ?? 'new'}
          initial={editor.task}
          onCancel={() => setEditor(null)}
          onSaved={async () => {
            setEditor(null)
            setNotice('')
            await load()
          }}
        />
      )}

      {notice && <p className="status-line alert">{notice}</p>}

      {rows.length === 0 ? (
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
  const soon = !done && !overdue && !deferred
    && new Date(task.due_at).getTime() - Date.now() <= 30 * 60000
  const sub = metaText(task)
  return (
    <div className={`task-row${overdue ? ' is-overdue' : ''}${done ? ' is-done' : ''}${props.picked ? ' is-picked' : ''}`}>
      <button
        type="button"
        className={`check${done ? ' done' : ''}`}
        aria-checked={done}
        aria-label={done ? '重新打开' : '完成'}
        title={done ? '重新打开' : '标记完成'}
        onClick={done ? props.onReopen : props.onComplete}
      >
        <Icon name="check" size={11} />
      </button>
      <div className="task-time">
        <small>{dayLabel(task.due_at)}</small>
        {formatClock(task.due_at)}
      </div>
      <div className="task-main" onClick={props.onPick} title="点击选择这项">
        <div className="task-title">{task.title}</div>
        {sub && <div className="task-sub">{sub}</div>}
      </div>
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
          <Pill tone="danger"><Icon name="alert" size={11} />{overdueText(task.due_at)}</Pill>
        ) : (
          <Pill tone={soon ? 'caution' : 'plain'}>
            <Icon name="clock" size={11} />{dueChip(task.due_at)}
          </Pill>
        )}
        <div className="task-actions">
          {!done && (
            <>
              <button
                type="button"
                className="task-action"
                title="十分钟后提醒"
                aria-label="十分钟后提醒"
                onClick={props.onSnooze}
              >
                <Icon name="clock" size={14} />
              </button>
              <button
                type="button"
                className="task-action"
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
            title="删除"
            aria-label="删除待办"
            onClick={props.onDelete}
          >
            <Icon name="trash" size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}

function TaskEditor(props: {
  initial: Task | null
  onCancel: () => void
  onSaved: () => void | Promise<void>
}) {
  const [title, setTitle] = useState(props.initial?.title ?? '')
  const [due, setDue] = useState(props.initial ? toLocalInput(props.initial.due_at) : defaultDueInput())
  const [repeat, setRepeat] = useState<RepeatRule>(props.initial?.repeat_rule ?? 'none')
  const [dingtalk, setDingtalk] = useState(Boolean(props.initial?.dingtalk))
  const [note, setNote] = useState(props.initial?.note ?? '')
  const [quick, setQuick] = useState('')
  const [hint, setHint] = useState<{ tone: 'plain' | 'calm' | 'alert'; text: string }>({ tone: 'plain', text: '' })
  const [saving, setSaving] = useState(false)

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

  const submit = async () => {
    if (!title.trim()) {
      setHint({ tone: 'alert', text: '请填写待办标题。' })
      return
    }
    setSaving(true)
    try {
      if (props.initial) {
        await api.taskEdit({
          id: props.initial.id,
          title: title.trim(),
          dueAt: fromLocalInput(due),
          repeat,
          dingtalk,
        })
      } else {
        await api.taskAdd({
          title: title.trim(),
          dueAt: fromLocalInput(due),
          repeat,
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
    <section className="editor">
      <div className="editor-head">
        <Icon name={props.initial ? 'edit' : 'plus'} size={16} />
        <h2>{props.initial ? '编辑待办' : '新建待办'}</h2>
        <button type="button" className="link-btn" onClick={props.onCancel}>收起</button>
      </div>
      <label>
        <span className="field-label">标题</span>
        <input
          className="field"
          autoFocus
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="要做的事"
        />
      </label>
      <div className="editor-grid">
        <label>
          <span className="field-label">提醒时间</span>
          <input
            className="field"
            type="datetime-local"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </label>
        <label>
          <span className="field-label">一句话快速填写（可选）</span>
          <input
            className="field"
            value={quick}
            onChange={(e) => setQuick(e.target.value)}
            placeholder="试试：明天 9:30 开会 / 2 小时后喝水"
          />
        </label>
      </div>
      {hint.text && (
        <p className={`status-line${hint.tone !== 'plain' ? ` ${hint.tone}` : ''}`}>{hint.text}</p>
      )}
      <div className="editor-foot">
        <div>
          <span className="field-label">重复</span>
          <Segmented options={REPEAT_OPTIONS} value={repeat} onChange={setRepeat} />
        </div>
        <Toggle label="推送到钉钉" checked={dingtalk} onChange={setDingtalk} />
        <span className="spacer" />
        <Button onClick={props.onCancel}>取消</Button>
        <Button primary disabled={saving} onClick={() => void submit()}>
          {saving ? '保存中…' : '保存'}
        </Button>
      </div>
      {!props.initial && (
        <label>
          <span className="field-label">备注（可选）</span>
          <textarea
            className="field"
            value={note}
            maxLength={1000}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      )}
    </section>
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
  if (task.repeat_rule !== 'none') parts.push(REPEAT_LABELS[task.repeat_rule])
  if (task.status === 'done') {
    if (task.completed_at) {
      const minutes = Math.floor(
        (new Date(task.due_at).getTime() - new Date(task.completed_at).getTime()) / 60000,
      )
      const tail = minutes > 0
        ? `提前 ${minutes} 分钟`
        : minutes < 0 ? `晚 ${Math.abs(minutes)} 分钟` : '准点'
      parts.push(`${formatClock(task.completed_at)} 完成，${tail}`)
    }
  } else if (task.early_notified_at) {
    parts.push('提前 10 分钟提醒')
  } else if (task.deferred === 1) {
    parts.push('提醒已达上限')
  } else if (isOverdue(task) && task.remind_count > 0) {
    parts.push(`已提醒 ${task.remind_count} 次`)
  }
  if (task.source === 'chat' || task.source === 'draft') {
    parts.push(`由对话创建 ${formatClock(task.created_at || task.due_at)}`)
  }
  const note = task.note.trim()
  if (note) parts.push(`备注：${note}`)
  return parts.join(' · ')
}

function formatClock(iso: string): string {
  const date = new Date(iso)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
