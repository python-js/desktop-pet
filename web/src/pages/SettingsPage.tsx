import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  onConnectionTested,
  onPetChanged,
  PetGallery,
  SecretsStatus,
  Settings,
} from '../api'
import { BridgeError } from '../bridge/bridge'
import {
  Button, Card, Icon, Pill, Row, Segmented, StatusLine, TextInput, TimeInput, Toggle,
} from '../ui'
import { setTheme, useTheme } from '../theme'

function messageOf(err: unknown): string {
  return err instanceof BridgeError || err instanceof Error ? err.message : '操作失败，请重试。'
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export default function SettingsPage(props: {
  settings: Settings
  secrets: SecretsStatus
  dataDir: string
  onSettings: (patch: Partial<Settings>) => void
}) {
  return (
    <div className="page">
      <header className="page-head">
        <div className="page-head-main">
          <div className="eyebrow settings-eyebrow">MAKE IT YOURS　/　偏好</div>
          <h1 className="page-title">偏好设置</h1>
          <p className="page-sub">改动即时生效，无需重启。</p>
        </div>
        <div className="page-head-side">
          <Pill tone="calm"><Icon name="check" size={11} />已自动保存</Pill>
        </div>
      </header>
      <div className="settings-page">
        <ModelCard settings={props.settings} secrets={props.secrets} onSettings={props.onSettings} />
        <WebSearchCard settings={props.settings} secrets={props.secrets} onSettings={props.onSettings} />
        <ReminderCard settings={props.settings} onSettings={props.onSettings} />
        <AppearanceCard settings={props.settings} onSettings={props.onSettings} />
        <DataCard dataDir={props.dataDir} />
        <PetCard />
        <DingTalkCard secrets={props.secrets} />
      </div>
    </div>
  )
}

function ModelCard(props: {
  settings: Settings
  secrets: SecretsStatus
  onSettings: (patch: Partial<Settings>) => void
}) {
  const [baseUrl, setBaseUrl] = useState(props.settings.base_url ?? '')
  const [model, setModel] = useState(props.settings.model ?? '')
  const [apiKey, setApiKey] = useState('')
  const [keyDirty, setKeyDirty] = useState(false)
  const [notice, setNotice] = useState(
    props.secrets.hasApiKey ? '已保存密钥；留空并保存即可清除。' : '更改后点「保存」，下一条消息生效。',
  )
  const [noticeTone, setNoticeTone] = useState<'calm' | 'alert' | 'plain'>('plain')
  const [testing, setTesting] = useState(false)
  const [rememberEnabled, setRememberEnabled] = useState(props.settings.remember_key ?? false)
  const jobId = useRef('')

  useEffect(() => setRememberEnabled(props.settings.remember_key ?? false), [props.settings.remember_key])

  useEffect(() => onConnectionTested((result) => {
    if (result.jobId !== jobId.current) return
    setTesting(false)
    setNotice(result.message)
    setNoticeTone(result.ok ? 'calm' : 'alert')
  }), [])

  const save = async () => {
    try {
      const base = baseUrl.trim()
      const name = model.trim()
      if (!!base !== !!name) {
        throw new BridgeError('VALIDATION_ERROR', '请同时填写服务地址和模型，或同时留空使用规则模式。')
      }
      if (keyDirty) {
        await api.saveApiKey(base, apiKey.trim())
        setKeyDirty(false)
        setApiKey('')
      }
      await api.setSettings({ base_url: base, model: name, stream: props.settings.stream ?? true })
      if ((props.settings.remember_key ?? false) !== rememberEnabled) {
        await api.setRememberKey(rememberEnabled)
      }
      setNotice(rememberEnabled
        ? '设置已保存；密钥由当前 Windows 用户加密保存。'
        : '设置已保存；API Key 仅在本次运行有效。')
      setNoticeTone('calm')
    } catch (err) {
      setNotice(messageOf(err))
      setNoticeTone('alert')
    }
  }

  const test = async () => {
    if (!baseUrl.trim() || !model.trim()) {
      setNotice('请先填写服务地址和模型。')
      setNoticeTone('alert')
      return
    }
    setTesting(true)
    setNotice('正在测试连接…')
    setNoticeTone('plain')
    try {
      const { jobId: id } = await api.testConnection('model')
      jobId.current = id
    } catch (err) {
      setTesting(false)
      setNotice(messageOf(err))
      setNoticeTone('alert')
    }
  }

  return (
    <Card title="模型与对话" icon="chat" desc="接支持 Chat Completions 的服务。模型留空时走本地规则，一样能记事。">
      <Row label="服务地址" desc="OpenAI 兼容端点">
        <TextInput
          value={baseUrl}
          placeholder="供应商提供的 API 根地址，通常以 /v1 结尾"
          onChange={(v) => setBaseUrl(v)}
        />
      </Row>
      <Row label="模型" desc="决定回答速度与措辞">
        <TextInput value={model} onChange={setModel} />
      </Row>
      <Row label="API Key" desc="默认只留在本次运行内存里">
        <TextInput
          value={apiKey}
          password
          placeholder={props.secrets.hasApiKey ? '已保存（输入新值可替换）' : '只用于当前服务地址的密钥'}
          onChange={(v) => { setApiKey(v); setKeyDirty(true) }}
        />
        <Toggle
          label="用当前 Windows 账户加密记住"
          desc="写入系统凭据，不进设置文件。"
          checked={rememberEnabled}
          onChange={setRememberEnabled}
        />
        <Toggle
          label="逐字显示回答"
          desc="服务不支持流式时会自动整段返回。"
          checked={props.settings.stream ?? true}
          onChange={(checked) => props.onSettings({ stream: checked })}
        />
        <div className="btn-row">
          <Button primary onClick={() => void save()}>保存</Button>
          <Button onClick={() => void test()} disabled={testing}>测试连接</Button>
        </div>
        <StatusLine text={notice} tone={noticeTone} />
      </Row>
    </Card>
  )
}

function WebSearchCard(props: {
  settings: Settings
  secrets: SecretsStatus
  onSettings: (patch: Partial<Settings>) => void
}) {
  const [key, setKey] = useState('')
  const [status, setStatus] = useState(
    props.secrets.hasTavily ? 'Tavily 密钥已载入。' : '尚未配置 Tavily 密钥；配置后默认自动联网。',
  )
  const [tone, setTone] = useState<'calm' | 'alert' | 'plain'>('plain')
  const [testing, setTesting] = useState(false)
  const jobId = useRef('')

  useEffect(() => onConnectionTested((result) => {
    if (result.jobId !== jobId.current) return
    setTesting(false)
    setStatus(result.message)
    setTone(result.ok ? 'calm' : 'alert')
  }), [])

  const save = async () => {
    try {
      await api.saveTavily(key.trim())
      await api.setSettings({ web_search_enabled: props.settings.web_search_enabled ?? true })
      setStatus(key.trim() ? '联网搜索设置已保存；密钥由当前 Windows 用户加密保存。' : '已清除 Tavily 密钥，联网搜索关闭。')
      setTone('calm')
      setKey('')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    }
  }

  const test = async () => {
    const value = key.trim()
    if (!value && !props.secrets.hasTavily) {
      setStatus('请先填写 Tavily API Key。')
      setTone('alert')
      return
    }
    setTesting(true)
    setStatus('正在测试 Tavily 连接（会消耗 1 credit）…')
    setTone('plain')
    try {
      const { jobId: id } = await api.testConnection('tavily', value ? { value } : {})
      jobId.current = id
    } catch (err) {
      setTesting(false)
      setStatus(messageOf(err))
      setTone('alert')
    }
  }

  return (
    <Card title="联网搜索" icon="search" desc="接入 Tavily 查实时资料；只发送当前问题，不发送对话历史和待办。">
      <Row label="Tavily API Key" desc="在 tavily.com 创建，形如 tvly-…">
        <TextInput
          value={key}
          password
          placeholder={props.secrets.hasTavily ? '已保存（输入新值可替换）' : '仅用于 Tavily 搜索'}
          onChange={setKey}
        />
        <Toggle
          label="自动联网查资料"
          desc="命中查资料类问题且已配置密钥时先搜索；每次消耗 1 credit。"
          checked={props.settings.web_search_enabled ?? true}
          onChange={(checked) => props.onSettings({ web_search_enabled: checked })}
        />
        <div className="btn-row">
          <Button primary onClick={() => void save()}>保存</Button>
          <Button onClick={() => void test()} disabled={testing}>测试连接</Button>
        </div>
        <StatusLine text={status} tone={tone} />
      </Row>
    </Card>
  )
}

function ReminderCard(props: { settings: Settings; onSettings: (patch: Partial<Settings>) => void }) {
  const [startupChecked, setStartupChecked] = useState(false)
  const [startupDirty, setStartupDirty] = useState(false)
  const [startupSupported, setStartupSupported] = useState(true)
  const [status, setStatus] = useState('')
  const [tone, setTone] = useState<'calm' | 'alert' | 'plain'>('plain')

  useEffect(() => {
    api.getStartup()
      .then((data) => { setStartupChecked(data.enabled); setStartupSupported(true) })
      .catch(() => setStartupSupported(false))
  }, [])

  const applyStartup = async () => {
    try {
      await api.setStartup(startupChecked)
      setStartupDirty(false)
      setStatus('开机启动设置已应用。')
      setTone('calm')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    }
  }

  const dndStart = props.settings.dnd_start ?? '22:30'
  const dndEnd = props.settings.dnd_end ?? '07:00'
  const dndOn = props.settings.dnd_enabled ?? true

  return (
    <Card title="提醒与免打扰" icon="bell" desc="桌面气泡是主通道，钉钉只是备份。">
      <Row label="提醒方式" desc="到点后弹桌面气泡，不抢焦点。">
        <Toggle
          label="提前 10 分钟轻轻提点"
          desc="只在小满身上显示，不弹气泡。"
          checked={props.settings.early_nudge ?? true}
          onChange={(checked) => props.onSettings({ early_nudge: checked })}
        />
        <Toggle
          label="桌面气泡 + 提示音"
          desc="到点播放一声系统提示音。"
          checked={props.settings.sound_enabled ?? true}
          onChange={(checked) => props.onSettings({ sound_enabled: checked })}
        />
        <Toggle
          label="错过后自动顺延 10 分钟"
          desc="关掉后，逾期未回应的事项保持逾期。"
          checked={props.settings.auto_postpone ?? false}
          onChange={(checked) => props.onSettings({ auto_postpone: checked })}
        />
      </Row>
      <Row label="免打扰" desc="这段时间只静默记录，不弹窗也不推送。">
        <div className="inline-row">
          <TimeInput value={dndStart} onChange={(v) => props.onSettings({ dnd_start: v })} />
          <span className="status-line">—</span>
          <TimeInput value={dndEnd} onChange={(v) => props.onSettings({ dnd_end: v })} />
          <Pill tone={dndOn ? 'calm' : 'plain'}>{dndOn ? '已开启' : '已关闭'}</Pill>
          <Toggle
            label="启用免打扰时段"
            checked={dndOn}
            onChange={(checked) => props.onSettings({ dnd_enabled: checked })}
          />
        </div>
      </Row>
      <Row label="开机与后台" desc="登录后启动；关机或睡眠期间的提醒，下次启动时补检。">
        <Toggle
          label="登录 Windows 后启动，主窗口收起到托盘"
          desc="小满直接出现在桌面上。"
          checked={startupChecked}
          disabled={!startupSupported}
          onChange={(checked) => { setStartupChecked(checked); setStartupDirty(true) }}
        />
        <div className="btn-row">
          <Button onClick={() => void applyStartup()} disabled={!startupSupported || !startupDirty}>应用启动设置</Button>
        </div>
        {!startupSupported && <StatusLine text="当前环境不支持开机启动管理。" tone="alert" />}
        <StatusLine text={status} tone={tone} />
      </Row>
    </Card>
  )
}

function AppearanceCard(props: { settings: Settings; onSettings: (patch: Partial<Settings>) => void }) {
  const theme = useTheme()
  return (
    <Card title="外观与密度" icon="sun" desc="主题与列表密度即时生效，只影响这台电脑。">
      <Row label="主题" desc="纸白适合白天，夜幕降低夜间亮度。">
        <Segmented
          options={[{ key: 'light', label: '纸白' }, { key: 'dark', label: '夜幕' }] as const}
          value={theme}
          onChange={setTheme}
        />
      </Row>
      <Row label="密度" desc="宽松更清晰，紧凑一屏看更多。">
        <Segmented
          options={[{ key: 'comfortable', label: '宽松' }, { key: 'compact', label: '紧凑' }] as const}
          value={props.settings.density ?? 'comfortable'}
          onChange={(value) => props.onSettings({ density: value })}
        />
      </Row>
    </Card>
  )
}

function DataCard(props: { dataDir: string }) {
  const [status, setStatus] = useState('设置、密钥和宠物图片不在导出与清空范围内。')
  const [tone, setTone] = useState<'calm' | 'alert' | 'plain'>('plain')
  const [busy, setBusy] = useState(false)

  const exportData = async () => {
    try {
      const { path } = await api.pickSavePath(
        `desktop-pet-export-${new Date().toISOString().slice(0, 10)}.json`,
        'JSON 文件 (*.json)',
        '.json',
      )
      if (!path) return
      setBusy(true)
      const result = await api.exportData(path)
      setStatus(`已导出 ${result.tasks} 条待办和 ${result.sessions} 段对话：${result.file}`)
      setTone('calm')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    } finally {
      setBusy(false)
    }
  }

  const clearData = async () => {
    if (!window.confirm('将清空全部待办、对话和草稿，并先自动备份数据库。\nAPI Key、钉钉配置和宠物图片不会被删除。')) return
    if (!window.confirm('确定清空全部待办和对话？清空后可在数据目录用 .bak 备份恢复。')) return
    try {
      setBusy(true)
      const result = await api.clearData()
      setStatus(result.backup ? `数据已清空，备份：${result.backup}` : '数据已清空。')
      setTone('calm')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="数据与隐私" icon="database" desc="待办和对话都在本机，不上传；导出不含密钥。">
      <Row label="存放位置" desc="所有数据都在这个目录；清空前会先自动备份。">
        <p className="mono-path" title={props.dataDir}>{props.dataDir}</p>
        <div className="btn-row">
          <Button onClick={() => void api.openDataDir()}>打开文件夹</Button>
          <Button onClick={() => void exportData()} disabled={busy}>导出数据</Button>
          <Button danger onClick={() => void clearData()} disabled={busy}>清空数据</Button>
        </div>
        <StatusLine text={status} tone={tone} />
      </Row>
    </Card>
  )
}

function PetCard() {
  const [gallery, setGallery] = useState<PetGallery | null>(null)
  const [status, setStatus] = useState('')
  const [tone, setTone] = useState<'calm' | 'alert' | 'plain'>('plain')
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    try {
      setGallery(await api.petGallery())
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    }
  }, [])

  useEffect(() => {
    void reload()
    return onPetChanged(() => { void reload() })
  }, [reload])

  const run = async (action: () => Promise<{ changed: boolean }>, label: string) => {
    if (busy) return
    setBusy(true)
    setTone('plain')
    setStatus(`${label}…`)
    try {
      const { changed } = await action()
      await reload()
      setStatus(changed ? '宠物形象已更新。' : '已取消，形象保持不变。')
      setTone(changed ? 'calm' : 'plain')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    } finally {
      setBusy(false)
    }
  }

  const select = async (image: string) => {
    if (busy || !gallery || gallery.active === image) return
    setBusy(true)
    setTone('plain')
    setStatus(image ? '正在切换宠物图片…' : '正在切换默认形象…')
    try {
      const { applied } = await api.petSelect(image)
      await reload()
      setStatus(applied ? (image ? '已切换宠物图片。' : '已切换到默认形象。') : '切换未完成，形象保持不变。')
      setTone(applied ? 'calm' : 'alert')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    } finally {
      setBusy(false)
    }
  }

  const resetPosition = async () => {
    if (busy) return
    setBusy(true)
    try {
      await api.petResetPosition()
      setStatus('已把宠物找回到屏幕可见区域。')
      setTone('calm')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    } finally {
      setBusy(false)
    }
  }

  const defaultActive = !gallery?.active
  const tiles: { key: string; thumb: string; label: string; active: boolean }[] = [
    { key: '', thumb: gallery?.defaultThumb ?? '', label: '默认形象', active: defaultActive },
    ...(gallery?.items ?? []).map((item) => ({
      key: item.image, thumb: item.thumb, label: fileName(item.image), active: item.active,
    })),
  ]

  return (
    <Card title="宠物形象" icon="image" desc="2D 使用这张图片，3D 使用内置形象，可在桌面右键切换。">
      <Row label="正在使用" desc="桌面上就是这一只。">
        {!gallery ? (
          <p className="status-line">正在读取形象…</p>
        ) : (
          <div className="pet-preview">
            <img src={gallery.preview || gallery.defaultThumb} alt="当前宠物形象" />
            <span className="status-line" style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis' }} title={gallery.active || '默认形象'}>
              {gallery.active ? fileName(gallery.active) : '默认形象'}
            </span>
          </div>
        )}
        <div className="pet-tiles">
          {tiles.map((tile) => (
            <button
              key={tile.key || 'default'}
              type="button"
              className="pet-tile"
              title={tile.label}
              aria-label={tile.label}
              aria-pressed={tile.active}
              disabled={busy}
              onClick={() => void select(tile.key)}
            >
              {tile.thumb
                ? <img src={tile.thumb} alt="" />
                : <span>无法预览</span>}
            </button>
          ))}
        </div>
        <div className="btn-row">
          <Button primary onClick={() => void run(api.petChooseImage, '正在打开图片选择')} disabled={busy}>
            上传新图片
          </Button>
          <Button
            onClick={() => void run(api.petRemoveImage, '正在移除当前图片')}
            disabled={busy || !gallery?.active}
          >
            移除这张图片
          </Button>
          <Button
            onClick={() => void run(api.petRemoveBackground, '正在打开背景处理')}
            disabled={busy || !gallery?.active}
          >
            纯色背景移除
          </Button>
          <Button
            onClick={() => void run(api.petRestoreOriginal, '正在恢复原图')}
            disabled={busy || !gallery?.hasOriginal}
          >
            恢复原图
          </Button>
        </div>
        <p className="pet-note">
          上传或切换后直接使用这张图片，不再生成动作。建议使用透明背景 PNG；纯色底图可先做背景移除。
          上传新图片会保留在历史中。
        </p>
        <StatusLine text={status} tone={tone} />
      </Row>
      <Row label="桌面位置" desc="记住上次拖到的地方，不跟随显示器切换。">
        <div className="btn-row">
          <Button onClick={() => void resetPosition()} disabled={busy}>找回宠物</Button>
        </div>
      </Row>
    </Card>
  )
}

function DingTalkCard(props: { secrets: SecretsStatus }) {
  const [webhook, setWebhook] = useState('')
  const [secret, setSecret] = useState('')
  const [status, setStatus] = useState(
    props.secrets.hasDingtalk ? '已配置，仅标记的任务会推送。' : '尚未配置钉钉机器人。',
  )
  const [tone, setTone] = useState<'calm' | 'alert' | 'plain'>('plain')
  const [testing, setTesting] = useState(false)
  const jobId = useRef('')

  useEffect(() => onConnectionTested((result) => {
    if (result.jobId !== jobId.current) return
    setTesting(false)
    setStatus(result.message)
    setTone(result.ok ? 'calm' : 'alert')
  }), [])

  const save = async () => {
    try {
      await api.saveDingtalk(webhook.trim(), secret.trim())
      setStatus(webhook.trim() ? '钉钉机器人已保存，仅标记钉钉通知的待办会推送。' : '已关闭钉钉通知。')
      setTone('calm')
      setWebhook('')
      setSecret('')
    } catch (err) {
      setStatus(messageOf(err))
      setTone('alert')
    }
  }

  const test = async () => {
    setTesting(true)
    setStatus('正在发送测试消息…')
    setTone('plain')
    try {
      const extra: Record<string, unknown> = {}
      if (webhook.trim()) extra.webhook = webhook.trim()
      if (secret.trim()) extra.secret = secret.trim()
      const { jobId: id } = await api.testConnection('dingtalk', extra)
      jobId.current = id
    } catch (err) {
      setTesting(false)
      setStatus(messageOf(err))
      setTone('alert')
    }
  }

  return (
    <Card title="钉钉群通知" icon="send" desc="只有明确标了「钉钉通知」的待办，到期才推群。">
      <Row label="群机器人" desc="Webhook 与加签密钥由当前 Windows 用户加密保存，不写入设置文件。">
        <TextInput
          value={webhook}
          password
          placeholder={props.secrets.hasDingtalk ? 'https://oapi.dingtalk.com/robot/send?…（已保存）' : 'https://oapi.dingtalk.com/robot/send?access_token=…'}
          onChange={setWebhook}
        />
        <TextInput
          value={secret}
          password
          placeholder="机器人「加签」密钥"
          onChange={setSecret}
        />
        <div className="btn-row">
          <Button primary onClick={() => void save()}>保存钉钉设置</Button>
          <Button onClick={() => void test()} disabled={testing}>发送测试</Button>
        </div>
        <StatusLine text={status} tone={tone} />
      </Row>
    </Card>
  )
}
