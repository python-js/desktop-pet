import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { connectBridge } from './bridge/bridge'
import { api, onNavigate, onSettingsChanged, onTasksChanged, SecretsStatus, Settings, SystemInfo, Task } from './api'
import { formatDue } from './tasks'
import SettingsPage from './pages/SettingsPage'
import HomePage from './pages/HomePage'
import TasksPage from './pages/TasksPage'
import ChatPage from './pages/ChatPage'
import KnowledgePage from './pages/KnowledgePage'
import { Icon, IconName, Paw, Pill } from './ui'
import { fetchCached, invalidateCache, readCache } from './queryCache'
import { applyTheme, initTheme, nextTheme, setTheme, useTheme } from './theme'

type Phase = 'connecting' | 'loading' | 'ready' | 'error'
type Page = 'home' | 'chat' | 'tasks' | 'knowledge' | 'settings'

const NAV: { key: Page; label: string; icon: IconName }[] = [
  { key: 'home', label: '首页', icon: 'home' },
  { key: 'chat', label: '对话助手', icon: 'chat' },
  { key: 'tasks', label: '待办事项', icon: 'tasks' },
  { key: 'knowledge', label: '本地知识库', icon: 'book' },
  { key: 'settings', label: '偏好设置', icon: 'settings' },
]

async function copyToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const area = document.createElement('textarea')
  area.value = text
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  document.execCommand('copy')
  area.remove()
}

function toggleThemeWithReveal(button: HTMLButtonElement) {
  const theme = nextTheme()
  const apply = () => setTheme(theme)

  const startViewTransition = document.startViewTransition?.bind(document)
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!startViewTransition || reducedMotion) {
    apply()
    return
  }

  const rect = button.getBoundingClientRect()
  const enteringNight = theme === 'dark'
  const x = enteringNight ? window.innerWidth - 1 : rect.left + rect.width / 2
  const y = enteringNight ? 0 : rect.top + rect.height / 2
  const radius = Math.hypot(
    Math.max(x, window.innerWidth - x),
    Math.max(y, window.innerHeight - y),
  )
  const transition = startViewTransition(apply)
  void transition.ready.then(() => {
    const animation = document.documentElement.animate(
      [
        { clipPath: `circle(0px at ${x}px ${y}px)` },
        { clipPath: `circle(${radius}px at ${x}px ${y}px)` },
      ],
      {
        duration: 480,
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
        pseudoElement: '::view-transition-new(root)',
      },
    )
    return animation.finished.finally(() => animation.cancel())
  }).catch(() => transition.skipTransition())
}

export default function App() {
  const [phase, setPhase] = useState<Phase>('connecting')
  const [page, setPage] = useState<Page>('home')
  const [visitedPages, setVisitedPages] = useState<Set<Page>>(() => new Set(['home']))
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [secrets, setSecrets] = useState<SecretsStatus | null>(null)
  const [tasks, setTasks] = useState<Task[]>(() => readCache<Task[]>('tasks.pending') ?? [])
  const [error, setError] = useState('')
  const [taskDraftRequest, setTaskDraftRequest] = useState(0)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; selection: string } | null>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)
  const navigate = (next: Page) => {
    setPage(next)
    setVisitedPages((visited) => visited.has(next) ? visited : new Set(visited).add(next))
  }
  const [railCollapsed, setRailCollapsed] = useState(() => {
    try {
      const stored = localStorage.getItem('pet.railCollapsed')
      if (stored === '0' || stored === '1') return stored === '1'
    } catch {
      // 本地存储不可用时退回窗口宽度判断。
    }
    return window.innerWidth < 1280
  })

  useEffect(() => {
    let cancelled = false
    connectBridge()
      .then(() => api.systemInfo())
      .then(async (data) => {
        if (cancelled) return
        setInfo(data)
        setPhase('loading')
        const [loadedSettings, loadedSecrets] = await Promise.all([
          api.getSettings(), api.getSecretsStatus(),
        ])
        if (cancelled) return
        initTheme(loadedSettings.theme)
        setSettings(loadedSettings)
        setSecrets(loadedSecrets)
        setPhase('ready')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setPhase('error')
        setError(err instanceof Error ? err.message : String(err))
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => onSettingsChanged(({ theme, ...patch }) => {
    // 主题走独立订阅源，不再回灌 App 状态，避免每次切换多一次整页渲染。
    if (theme) applyTheme(theme)
    if (Object.keys(patch).length) {
      setSettings((prev) => (prev ? { ...prev, ...patch } : prev))
    }
  }), [])

  useEffect(() => onNavigate((payload) => {
    if (payload.page === 'home' || payload.page === 'chat'
      || payload.page === 'tasks' || payload.page === 'knowledge' || payload.page === 'settings') {
      navigate(payload.page)
    }
  }), [])

  useEffect(() => {
    const close = () => setContextMenu(null)
    const onContextMenu = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element) || !target.closest('.shell')) return
      if (target.closest('input, textarea, select, [contenteditable="true"]')) return
      event.preventDefault()
      const selection = window.getSelection()?.toString().trim() ?? ''
      setContextMenu({ x: event.clientX, y: event.clientY, selection })
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    const closeOutside = (event: PointerEvent) => {
      if (!contextMenuRef.current?.contains(event.target as Node)) close()
    }
    document.addEventListener('contextmenu', onContextMenu, true)
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('scroll', close, true)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('contextmenu', onContextMenu, true)
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('scroll', close, true)
      document.removeEventListener('keydown', onEscape)
    }
  }, [])

  useLayoutEffect(() => {
    if (!contextMenu) return
    const menu = contextMenuRef.current
    if (!menu) return
    const rect = menu.getBoundingClientRect()
    const x = Math.max(8, Math.min(contextMenu.x, window.innerWidth - rect.width - 8))
    const y = Math.max(8, Math.min(contextMenu.y, window.innerHeight - rect.height - 8))
    if (x !== contextMenu.x || y !== contextMenu.y) setContextMenu({ ...contextMenu, x, y })
  }, [contextMenu])

  useEffect(() => {
    if (phase !== 'ready') return
    let cancelled = false
    const load = () => {
      void fetchCached('tasks.pending', api.tasksList)
        .then((rows) => { if (!cancelled) setTasks(rows) })
        .catch(() => {})
    }
    load()
    const off = onTasksChanged(() => {
      invalidateCache('tasks.pending')
      invalidateCache('tasks.done')
      invalidateCache('tasks.stats')
      invalidateCache('tasks.today-events')
      load()
    })
    return () => { cancelled = true; off() }
  }, [phase])

  const patchSettings = (patch: Partial<Settings>) => {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev))
    void api.setSettings(patch).catch((err: unknown) => {
      console.error('保存设置失败', err)
    })
  }

  const toggleRail = () => {
    setRailCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('pet.railCollapsed', next ? '1' : '0')
      } catch {
        // 本地存储不可用时只影响下次启动的默认状态。
      }
      return next
    })
  }

  if (phase === 'connecting' || phase === 'loading') {
    return <Splash text={phase === 'connecting' ? '正在连接桌面桥…' : '正在载入设置…'} />
  }
  if (phase === 'error' || !settings || !secrets || !info) {
    return <Splash text={`连接失败：${error || '桥不可用'}。请在桌面宠物壳内运行。`} />
  }

  const paused = settings.pet_paused ?? false
  const next = tasks[0]
  const openNewTask = () => {
    setTaskDraftRequest((value) => value + 1)
    navigate('tasks')
  }

  return (
    <div className={`shell${railCollapsed ? ' rail-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="rail-brand">
          <span className="rail-logo"><Paw size={20} /></span>
          <div>
            <div className="rail-name">小满 <span>DESK COMPANION</span></div>
            <div className="rail-sub">你的桌面事务伙伴</div>
          </div>
        </div>
        <nav className="rail-nav">
          {NAV.map((item) => (
            <button
              key={item.key}
              type="button"
              className="nav-item"
              aria-current={page === item.key ? 'page' : undefined}
              onClick={() => navigate(item.key)}
            >
              <span className="nav-icon"><Icon name={item.icon} size={18} /></span>
              <span className="nav-label">{item.label}</span>
            </button>
          ))}
        </nav>

        <section className="rail-pet" aria-label="小满状态">
          <div className="rail-pet-head">
            <span className="rail-pet-name">小满</span>
            <Pill>{settings.pet_mode === '3d' ? '3D · 内置' : '2D · 内置'}</Pill>
          </div>
          <div className={`rail-pet-state${paused ? ' paused' : ''}`}>
            <span className="dot" aria-hidden />
            <span className="rail-pet-state-text">
              {paused ? '歇会儿' : '值守中'}
              <span className="state-detail">{paused ? ' · 随时可以叫醒' : ' · 屏幕右上角'}</span>
            </span>
          </div>
          <div className="rail-pet-rows">
            <div className="rail-pet-row">
              <span>今天替你盯着</span>
              <b>{tasks.length} 件</b>
            </div>
            <div className="rail-pet-row">
              <span>下一次提醒</span>
              <b>{next ? formatDue(next.due_at) : '暂无'}</b>
            </div>
          </div>
          <div className="rail-pet-actions">
            <button type="button" className="btn btn-sm" onClick={() => navigate('chat')}>
              <Icon name="chat" size={13} />说句话
            </button>
            <button
              type="button"
              className="btn btn-sm"
              aria-pressed={paused}
              onClick={() => patchSettings({ pet_paused: !paused })}
            >
              <Icon name={paused ? 'play' : 'pause'} size={13} />
              {paused ? '继续值守' : '歇会儿'}
            </button>
          </div>
        </section>

        <div className="rail-bottom">
          <span>v{info.appVersion}</span>
          <RailThemeButton />
          <button
            type="button"
            className="icon-btn"
            title={railCollapsed ? '展开侧栏' : '收起侧栏'}
            aria-label={railCollapsed ? '展开侧栏' : '收起侧栏'}
            aria-expanded={!railCollapsed}
            onClick={toggleRail}
          >
            <Icon name="panel" size={16} />
          </button>
        </div>
      </aside>

      <header className="winbar">
        <div className="winbar-title">
          <span className="brand"><Paw size={14} /></span>
          小满
          <span className="winbar-context">/ {NAV.find((item) => item.key === page)?.label}</span>
        </div>
        <div className={`winbar-status${paused ? ' paused' : ''}`}>
          <span className="dot" aria-hidden />
          小满 {paused ? '正在歇会儿' : '正在桌面值守'}
        </div>
      </header>

      <main className="content">
        {visitedPages.has('home') && <section className={`content-panel${page === 'home' ? ' is-active' : ''}`} aria-hidden={page !== 'home'}>
          <HomePage
            onOpenChat={() => navigate('chat')}
            onNewTask={openNewTask}
            active={page === 'home'}
          />
        </section>}
        {visitedPages.has('chat') && <section className={`content-panel content-panel-chat content-chat${page === 'chat' ? ' is-active' : ''}`} aria-hidden={page !== 'chat'}>
          <ChatPage
            onOpenTasks={() => navigate('tasks')}
            onOpenSettings={() => navigate('settings')}
            active={page === 'chat'}
          />
        </section>}
        {visitedPages.has('tasks') && <section className={`content-panel${page === 'tasks' ? ' is-active' : ''}`} aria-hidden={page !== 'tasks'}>
          <TasksPage
            startNew={taskDraftRequest}
            onStartNewConsumed={() => setTaskDraftRequest(0)}
            density={settings.density ?? 'comfortable'}
            onDensity={(density) => patchSettings({ density })}
            active={page === 'tasks'}
          />
        </section>}
        {visitedPages.has('settings') && <section className={`content-panel${page === 'settings' ? ' is-active' : ''}`} aria-hidden={page !== 'settings'}>
          <SettingsPage
            settings={settings}
            secrets={secrets}
            dataDir={info.dataDir}
            onSettings={patchSettings}
          />
        </section>}
        {visitedPages.has('knowledge') && <section className={`content-panel${page === 'knowledge' ? ' is-active' : ''}`} aria-hidden={page !== 'knowledge'}>
          <KnowledgePage settings={settings} onSettings={patchSettings} active={page === 'knowledge'} />
        </section>}
      </main>

      <footer className="statusbar">
        <span>关闭主窗口后可在托盘继续提醒；完全退出后不提醒。</span>
        <span className="spacer" />
        <span>数据只保存在这台电脑</span>
      </footer>
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="app-context-menu"
          role="menu"
          aria-label="应用操作菜单"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <div className="app-context-menu-title">页面操作</div>
          {contextMenu.selection && (
            <button type="button" role="menuitem" onClick={() => {
              void copyToClipboard(contextMenu.selection)
              setContextMenu(null)
            }}><Icon name="copy" size={14} />复制选中文字</button>
          )}
          <button type="button" role="menuitem" onClick={() => {
            const content = document.querySelector<HTMLElement>('.content')
            void copyToClipboard(content?.innerText ?? '')
            setContextMenu(null)
          }}><Icon name="copy" size={14} />复制当前页面内容</button>
          <button type="button" role="menuitem" onClick={() => {
            const content = document.querySelector('.content')
            if (content) {
              const range = document.createRange()
              range.selectNodeContents(content)
              const selection = window.getSelection()
              selection?.removeAllRanges()
              selection?.addRange(range)
            }
            setContextMenu(null)
          }}><Icon name="list" size={14} />全选当前页面</button>
          <button type="button" role="menuitem" onClick={() => window.location.reload()}><Icon name="refresh" size={14} />重新加载</button>
          <div className="app-context-menu-divider" />
          <div className="app-context-menu-title">快速跳转</div>
          {NAV.map((item) => (
            <button key={item.key} type="button" role="menuitem" aria-current={page === item.key ? 'page' : undefined} onClick={() => {
              navigate(item.key)
              setContextMenu(null)
            }}><Icon name={item.icon} size={14} />{item.label}{page === item.key && <span className="app-context-menu-current">当前</span>}</button>
          ))}
        </div>
      )}
    </div>
  )
}

function RailThemeButton() {
  const theme = useTheme()
  return (
    <button
      type="button"
      className="icon-btn"
      title={theme === 'dark' ? '切换到纸白主题' : '切换到夜幕主题'}
      aria-label="切换主题"
      onClick={(event) => toggleThemeWithReveal(event.currentTarget)}
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />
    </button>
  )
}

const loadingGif = new URL('./assets/loading.gif', import.meta.url).href

function Splash(props: { text: string }) {
  return (
    <main className="splash">
      <img className="splash-loader" src={loadingGif} alt="" />
      <p className="splash-text">{props.text}</p>
    </main>
  )
}
