import { useEffect, useState } from 'react'
import { connectBridge } from './bridge/bridge'
import { api, onNavigate, onSettingsChanged, onTasksChanged, SecretsStatus, Settings, SystemInfo, Task } from './api'
import { formatDue } from './tasks'
import SettingsPage from './pages/SettingsPage'
import HomePage from './pages/HomePage'
import TasksPage from './pages/TasksPage'
import ChatPage from './pages/ChatPage'
import { Icon, IconName, Paw, Pill } from './ui'

type Phase = 'connecting' | 'loading' | 'ready' | 'error'
type Page = 'home' | 'chat' | 'tasks' | 'settings'

const NAV: { key: Page; label: string; icon: IconName }[] = [
  { key: 'home', label: '首页', icon: 'home' },
  { key: 'chat', label: '对话助手', icon: 'chat' },
  { key: 'tasks', label: '待办事项', icon: 'tasks' },
  { key: 'settings', label: '偏好设置', icon: 'settings' },
]

export default function App() {
  const [phase, setPhase] = useState<Phase>('connecting')
  const [page, setPage] = useState<Page>('home')
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [secrets, setSecrets] = useState<SecretsStatus | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [error, setError] = useState('')
  const [taskDraftRequest, setTaskDraftRequest] = useState(0)
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

  useEffect(() => onSettingsChanged((patch) => {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev))
  }), [])

  useEffect(() => onNavigate((payload) => {
    if (payload.page === 'home' || payload.page === 'chat'
      || payload.page === 'tasks' || payload.page === 'settings') {
      setPage(payload.page)
    }
  }), [])

  useEffect(() => {
    const dark = settings?.theme === 'dark'
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [settings?.theme])

  useEffect(() => {
    if (phase !== 'ready') return
    let cancelled = false
    const load = () => {
      void api.tasksList()
        .then((rows) => { if (!cancelled) setTasks(rows) })
        .catch(() => {})
    }
    load()
    const off = onTasksChanged(() => load())
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
    setPage('tasks')
  }

  return (
    <div className={`shell${railCollapsed ? ' rail-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="rail-brand">
          <span className="rail-logo"><Paw size={20} /></span>
          <div>
            <div className="rail-name">Pet Studio</div>
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
              onClick={() => setPage(item.key)}
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
            <button type="button" className="btn btn-sm" onClick={() => setPage('chat')}>
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
          <button
            type="button"
            className="icon-btn"
            title={settings.theme === 'dark' ? '切换到纸白主题' : '切换到夜幕主题'}
            aria-label="切换主题"
            onClick={() => patchSettings({ theme: settings.theme === 'dark' ? 'light' : 'dark' })}
          >
            <Icon name={settings.theme === 'dark' ? 'sun' : 'moon'} size={16} />
          </button>
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
          Pet Studio
          <span className="winbar-context">· 控制台</span>
        </div>
        <div className={`winbar-status${paused ? ' paused' : ''}`}>
          <span className="dot" aria-hidden />
          小满 {paused ? '正在歇会儿' : '正在桌面值守'}
        </div>
      </header>

      <main className={`content${page === 'chat' ? ' content-chat' : ''}`}>
        {page === 'home' && (
          <HomePage
            onOpenChat={() => setPage('chat')}
            onNewTask={openNewTask}
          />
        )}
        {page === 'chat' && (
          <ChatPage
            onOpenTasks={() => setPage('tasks')}
            onOpenSettings={() => setPage('settings')}
          />
        )}
        {page === 'tasks' && (
          <TasksPage
            startNew={taskDraftRequest}
            onStartNewConsumed={() => setTaskDraftRequest(0)}
            density={settings.density ?? 'comfortable'}
            onDensity={(density) => patchSettings({ density })}
          />
        )}
        {page === 'settings' && (
          <SettingsPage
            settings={settings}
            secrets={secrets}
            dataDir={info.dataDir}
            onSettings={patchSettings}
          />
        )}
      </main>

      <footer className="statusbar">
        <span>关闭主窗口后可在托盘继续提醒；完全退出后不提醒。</span>
        <span className="spacer" />
        <span>数据只保存在这台电脑</span>
      </footer>
    </div>
  )
}

function Splash(props: { text: string }) {
  return (
    <main className="splash">
      <span className="rail-logo"><Paw size={26} /></span>
      <div className="spinner" aria-hidden />
      <p className="splash-text">{props.text}</p>
    </main>
  )
}
