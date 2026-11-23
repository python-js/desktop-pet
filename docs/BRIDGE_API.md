# 桌面宠物「壳子 + HTML」桥接口设计(v1)

> 状态:已实现。web 已是唯一界面(Phase 5),原 Qt 页面与 `ui_shell` 开关已删除。
> 适用范围:主窗口 WebView 与宠物窗 WebView 共用同一套桥协议。

## 1. 目标与非目标

**目标**

- 保留全部 Python 业务逻辑(TaskStore、assistant、knowledge、websearch、planning、secure_storage 等),UI 层由 QWidget 换成本地 HTML 页面,经 QWebChannel 通信。
- 协议**与页面无关**:主窗口、宠物窗、未来的弹窗窗体加载同一个桥,不因迁移阶段不同而分叉。
- 明确的线程边界,兼容现状约束(TaskStore 仅允许主线程访问,见 core.py)。

**非目标**

- 不引入 Electron/Tauri、不引入本地 HTTP 服务(桥走 QWebChannel,无端口、无进程间网络)。
- 不改造宠物窗现有的 `window.pet3d` 宿主→页面控制面(见 §9),壳子侧代码不动。

## 2. 架构总览

```
┌─────────────────────────── PySide6 壳(主线程) ─────────────────────────┐
│  MainWindow / PetWindow(QWebEngineView ×2,共享 QWebEngineProfile)        │
│        │ QWebChannel(registerObject("bridge", BridgeHost))               │
│  BridgeHost(QObject)  ← 唯一注册对象                                     │
│        ├─ 同步调用 → 直接调 TaskStore / 设置 / SecretStore(主线程,安全)   │
│        ├─ 异步调用 → 分发到现有后台机制(AssistantWorker / threading       │
│        │              .Thread),发 event 事件回报进度与结果                │
│        └─ 定时器驱动的事件(2s 到期检查、提前提醒)→ event 推送             │
└──────────────────────────────────────────────────────────────────────┘
        ↕ (invoke / event,JSON 字符串信封)
┌───────────────────── WebView(本地 HTML,主窗 + 宠物窗) ─────────────────┐
│  web/ 前端(Vite 构建,产物打包进 resources)                              │
│  bridge.ts 客户端:invoke(method, payload) / on(eventName, cb)           │
└──────────────────────────────────────────────────────────────────────┘
```

## 3. 协议选型:单对象 JSON 信封(QWebChannel)

QWebChannel 支持注册多个带强类型 slot 的对象,但本项目选择**单对象 + JSON 字符串信封**,理由:

1. 后端数据面本来就以 `dict(row)` 为主(tasks/messages/session 等),JSON 化零成本;
2. 单一 `invoke` 入口便于统一鉴权、日志、异常封装与协议版本化;
3. 避免 Qt QVariant 与 JS 类型在嵌套结构上的边角问题,信封全部用 `str`,调试时可直接打印;
4. 前端只需一个 30 行的通用 client,方法表可用 TypeScript 定义文件集中声明,不用逐对象生成代理。

**信封格式**

```ts
// JS → Python(slot 调用)
bridge.invoke(method: string, payload: string)  // payload = JSON.stringify(args 对象)
// 返回值(异步回调取得)= 响应信封 JSON 字符串
bridge.cancel(jobId: string)

// Python → JS(signal)
bridge.event(name: string, payload: string)     // 前端 bridge.on(name, cb) 订阅
```

**响应信封**

```jsonc
// 成功
{ "ok": true, "data": { ... } }
// 失败
{ "ok": false, "error": { "code": "VALIDATION_ERROR", "message": "标题不能为空" } }
```

**错误码**(枚举,前端按 code 分支提示):

| code | 含义 |
|---|---|
| `NOT_FOUND` | 目标(任务/会话/文档)不存在 |
| `VALIDATION_ERROR` | 输入不合法(标题超长、时间格式错误等) |
| `NOT_AVAILABLE` | 依赖缺失(无 API Key、WebEngine/模型不可用) |
| `CONFLICT` | 状态冲突(重复操作等) |
| `CANCELLED` | 作业被取消 |
| `INTERNAL` | 未归类异常,附 message |

## 4. 方法目录

命名 `模块.方法`。**同步方法**(主线程直接执行,应 <50ms)返回 `data`;**作业方法**(耗时/涉及模型/网络)立即返回 `{ "jobId": "..." }`,结果与进度经 `event` 推送,可用 `bridge.cancel(jobId)` 取消。标注 `(job)` 的即作业方法。

> 行号锚点指向当前实现,供实现时对照;签名以现有后端方法为准,桥层只做转发与 JSON 编解码,不复制业务逻辑。

### 4.1 tasks — 待办 CRUD(后端:core.py TaskStore)

实现:bridge_modules/tasks.py(只做参数适配与事件广播,校验/事务全部留在 TaskStore)。

| 方法 | 入参 | 出参(data) | 后端锚点 |
|---|---|---|---|
| `tasks.list` | `{}` | `Task[]`(pending) | `pending` |
| `tasks.history` | `{status='done', search?}` | `Task[]` | `history` |
| `tasks.add` | `{title, horizon?='timed', dueAt?, repeat?, dingtalk?, note?}` | `Task` | `add`;`timed` 必须给未来 `dueAt`,`week`/`month`/`someday` 忽略 `dueAt` |
| `tasks.edit` | `{id, title?, horizon?, dueAt?, repeat?, dingtalk?}` | `Task` | `edit`;已逾期的 `timed` 任务必须同时给出新的 `dueAt` |
| `tasks.complete` | `{id}` | `{nextId: string \| null}`(重复任务返回新实例) | `complete` |
| `tasks.reopen` | `{id}` | `{}` | `reopen`;已生成下一次的重复任务返回 `CONFLICT` |
| `tasks.delete` | `{id}` | `{}` | `delete` |
| `tasks.undoDelete` | `{id}` | `{}` | `undo_delete` |
| `tasks.snooze` | `{id, minutes=10}` | `{}` | `snooze`;`minutes` 需为 1–1440 的整数 |
| `tasks.setDingtalk` | `{id, enabled}` | `{}` | `set_dingtalk` |
| `tasks.muteToday` | `{id}` | `{mutedUntil: 'YYYY-MM-DD'}` | `mute_today` |
| `tasks.stats` | `{}` | `today_stats` 结构 | `today_stats` |
| `tasks.todayEvents` | `{}` | `today_events` 结构(含任务标题) | `today_events` |
| `tasks.parseDue` | `{text}` | `{dueAt, repeat, past}`(输入框实时解析) | `parse_due_text` |
| `tasks.dismissReminder` | `{id, postpone=true}` | `{postponed: boolean}` | `close_web_reminder`;`postpone` 且开启自动顺延时顺延 10 分钟 |

`repeat` 取值:`none | daily | weekdays | weekly`;`status`:`pending | done | deleted_pending | deleted_done`。Task 字段即 tasks 表行(见 core.py 建表语句)。所有写方法成功后都发 `tasks.changed`,前端据此重拉列表。

`horizon` 取值:`timed`(定时提醒,`due_at` 即提醒时刻)、`week`(本周日 23:59 截止,周五 17:00 提醒)、`month`(月末截止,最后一个工作日 17:00 提醒)、`someday`(待安排收集箱,无 `due_at`/`remind_at`,不计逾期)。`week`/`month`/`someday` 的 `repeat` 固定为 `none`;提醒时刻已过则不补发。

### 4.2 chat — 会话、消息与助手(bridge_modules/chat.py)

实现:`bridge_modules/chat.py`(会话/消息/草稿直接读写 core.py `TaskStore`,模型流水线仍由 AssistantWorker 提供,任务操作复用 `MainWindow.execute_task_op/run_task_ops`)。同一时刻只允许一个对话请求;冲突返回 `code: CONFLICT`。`worker_factory` 可从 `bridge.context` 注入,供离屏验收替换模型流水线。

| 方法 | 类型 | 入参 | 出参 |
|---|---|---|---|
| `chat.sessions` | 同步 | `{}` | `{activeSession, sessions: [{id, title, updatedAt, messageCount}]}` |
| `chat.session` | 同步 | `{sessionId?, limit=100}` | `{activeSession, session: {id, title, inputText}, messages, drafts, canRegenerate, retryable, busy, busySessionId, hasModel, choicePending}` |
| `chat.createSession` | 同步 | `{title?='新对话'}` | `{sessionId, ...chat.session 载荷}` |
| `chat.renameSession` | 同步 | `{sessionId, title}` | `{session: {id, title}}` |
| `chat.saveInput` | 同步 | `{sessionId, text}` | `{}`(未发送输入随输入框自动保存) |
| `chat.messages` | 同步 | `{sessionId?, limit=100}` | `[{role, content}]`;隐藏旧 JSON 包裹,规划提示词显示为「帮我规划今天」 |
| `chat.send` | **(job)** | `{sessionId, text}` | `{accepted, jobId, local?}`;结果事件见 §5.1。本地规则模式同步落库并返回 `local: true` |
| `chat.retry` | **(job)** | `{sessionId}` | `{accepted, jobId}`,重放上次失败/停止时的消息 |
| `chat.regenerate` | **(job)** | `{sessionId}` | `{jobId, sessionId}`;会另开分支会话,标题 `另一版 · <原标题>` |
| `chat.stop` | 同步 | `{}` | `{stopped, jobId?}` |
| `chat.chooseTask` | 同步 | `{sessionId, index}` | `{reply}`(多义待办序号选择,1 起) |
| `chat.planToday` | 同步/任务 | `{sessionId?, confirmed}` | `confirmed: false` → `{snapshot, prompt, usesModel, activeSession}`;`true` → `{accepted, jobId, snapshot, local?}` |

`chat.send` 流水线(知识库检索 → Tavily → 流式输出)整体保留在 AssistantWorker 中,桥只透传事件(§5.1)。任务类指令的 tasks 代码块解析与落库(`decode_response`、`run_task_ops`)保持后端职责,**前端只消费回执里的 `reply / tasks / errors / choice`**,不解析模型协议。模型返回并通过校验的待办操作在后端直接执行,无需用户再点保存；信息不足或目标多义时会追问/要求选择。`drafts.*` 是单独的显式草稿 API,仅对已经以草稿形式保存的条目提供确认/丢弃操作,不改变聊天待办指令的直接执行流程。`planToday` 只读取 `daily_snapshot`,不写待办;用户确认后才把规划提示词写入当前会话。

### 4.3 drafts — 显式草稿任务(core.py)

此 API 管理调用方明确保存为草稿的记录,与 `chat.send` 返回的任务操作分开。普通聊天中的有效待办指令直接执行,不经过草稿确认。

实现:bridge_modules/tasks.py `handle_drafts`。

| 方法 | 入参 | 出参 |
|---|---|---|
| `drafts.list` | `{sessionId?}` | `Draft[]`(缺省返回全部会话) |
| `drafts.save` | `{id?, sessionId?, title, dueAt, repeat?, note?}` | `{id}` |
| `drafts.confirm` | `{id}` | `{taskId}` |
| `drafts.discard` | `{id}` | `{}` |

### 4.4 knowledge — 本地知识库(knowledge.py)

| 方法 | 类型 | 入参 | 出参 |
|---|---|---|---|
| `knowledge.documents` | 同步 | `{}` | `[{docId, name, ...}]` |
| `knowledge.stats` | 同步 | `{}` | `{count, ...}` |
| `knowledge.search` | 同步 | `{query}` | `Hit[]`(见 knowledge.py:406) |
| `knowledge.importPaths` | **(job)** | `{paths: string[]}`(来自 §4.7 原生选择器) | `jobId`,进度事件 `knowledge.jobProgress` |
| `knowledge.remove` | 同步 | `{docId}` | `{}` |
| `knowledge.clear` | 同步 | `{}` | `{}`(与 Qt 侧一致,SQLite 单事务) |
| `knowledge.rebuild` | **(job)** | `{}` | `jobId` |

锚点:knowledge.py:248/351/365/375。导入/重建内部含模型 Wiki 编译,必须为作业;取消沿用 `_kb_cancel` Event 模式。

### 4.5 连接测试(统一入口)

| 方法 | 类型 | 入参 | 出参 |
|---|---|---|---|
| `secrets.testConnection` | **(job)** | `{kind: 'model'\|'tavily'\|'dingtalk', value?, webhook?, secret?}` | `{jobId}` → `connection.testResult {jobId, kind, ok, message}` 事件 |

后端:assistant.py:199、websearch.py:158、dingtalk.py。未传值时使用已存密钥;`dingtalk` 缺加签密钥返回 `ok:false` 与中文原因。联网搜索开关与意图识别(`wants_web_search` websearch.py:33)留在 `chat.send` 流水线内,不单独暴露。

### 4.6 settings — 设置与密钥(settings.py + secure_storage.py)

| 方法 | 类型 | 入参 | 出参 |
|---|---|---|---|
| `settings.getAll` | 同步 | `{}` | 白名单键值对象(见下) |
| `settings.set` | 同步 | `{patch: object}` | `{}`(逐键校验,只收白名单键) |
| `settings.exportData` | 同步 | `{path}`(来自 `system.pickSavePath`) | `{file, tasks, sessions}` |
| `settings.clearData` | 同步 | `{}`(前端做两次确认) | `{backup}`(备份文件名,先备份后清库) |

**密钥(DPAPI,经 SecretStore,save 时直接落盘)**

| 方法 | 类型 | 说明 |
|---|---|---|
| `secrets.saveApiKey` / `secrets.saveTavily` / `secrets.saveDingtalk` | 同步 | `{value}`;空值=删除(saveApiKey 另需 `endpoint`) |
| `secrets.status` | 同步 | `{hasApiKey, hasTavily, hasDingtalk, rememberKey}` |
| `secrets.rememberKey` | 同步 | `{enabled}`(关闭时清除已存密钥) |

**启动项**:`startup.get {enabled}`、`startup.set {enabled}`(startup.py:44/55)。
**钉钉**:测试发送并入 `secrets.testConnection {kind:'dingtalk'}`;到期推送由壳子的 `check_due_web(true)` 触发,结果以 `dingtalk.pushResult` 回报。

**getAll 返回的白名单键**(与 `desktop_pet/bridge_modules/settings.py` 的 `ALL_KEYS` 一致):`base_url, model, pet_image, active_session, pet_mode, theme, density, dnd_start, dnd_end, stream, remember_key, pet_paused, pet_walking, early_nudge, sound_enabled, auto_postpone, dnd_enabled, web_search_enabled, knowledge_enabled, pet_images, pet_position`。其中 `pet_images`、`pet_position` 只读,由壳子维护;密钥明文**永不下发**到 JS,前端只见 `secrets.status` 的布尔值。

### 4.7 system — 壳子能力(必须由原生实现的部分)

| 方法 | 说明 |
|---|---|
| `system.pickFile` / `system.pickFolder` | 原生 QFileDialog,返回**绝对路径**。HTML `<input type=file>` 拿不到路径,知识库导入、图片选择必须走这里 |
| `system.pickSavePath` | 原生另存为对话框,`{name?, filter?, extension?}` → `{path}`;`extension` 自动补全后缀 |
| `system.pickImage` | 原生图片选择(宠物形象、去背景流程入口) |
| `system.openPath` | 在资源管理器中打开数据目录(settings.py:1258 现行为) |
| `system.info` | `{version, bridgeVersion, platform, dataDir, devMode}` |
| `system.notify` | 托盘通知(platforms.py:21,与 HTML 内 toast 互补,用于最小化时) |
| `window.minimize` / `window.toggleMaximize` / `window.close` | 无边框窗体控制(若采用 HTML 标题栏) |

宠物形象管理(选图、去背景、还原)的**文件级操作仍留在壳子侧**(原生对话框、校验/复制、抠图),桥只做触发与预览:图片以 **base64 PNG data URL** 下发(96px 缩略图 / 240px 预览),不下发本地路径;默认形象由 `ui/pet.py` 代码绘制,故也用 data URL。具体方法见 §4.8。

### 4.8 pet — 宠物形象与窗口控制(壳子内行为,事件为主)

| 方法 | 类型 | 说明 |
|---|---|---|
| `pet.gallery` | 同步 | `{}` → `{active, items: [{image, original, thumb, active}], defaultThumb, preview, hasOriginal, position}`;`thumb`/`preview`/`defaultThumb` 为 base64 PNG data URL |
| `pet.select` | 同步 | `{image}`;空串=切回默认形象;图片必须在 `pet_images` 历史内(否则 `NOT_FOUND`),应用成功广播 `pet.changed` |
| `pet.chooseImage` / `pet.removeImage` / `pet.removeBackground` / `pet.restoreOriginal` | 同步 | 无参;分别转发壳侧 `choose_image` / `remove_pet_image` / `remove_image_background` / `restore_original_image`,原生对话框与抠图留在壳子;完成后广播 `pet.changed` 并返回 `{changed}` |
| `pet.resetPosition` | 同步 | 无参,复位宠物窗位置(pet.py:448 `ensure_visible` 同路径);返回 `{}` |
| `pet.say` | — | 气泡由壳子直接调用 `pet.say(text)`(QLabel,12s 自动隐藏),不经桥(Phase 4 决策) |
| `pet.pause` / `pet.walking` / `pet.mode` | — | 非桥方法:暂停、走动与 2D/3D 切换都通过 `settings.set` 的 `pet_paused` / `pet_walking` / `pet_mode` 完成 |

### 4.9 update — 检查、下载与安装更新(update.py)

| 方法 | 类型 | 入参 | 出参 |
|---|---|---|---|
| `update.get` | 同步 | `{}` | `{currentVersion, state, manifest, received, total, error, canInstall, skippedVersion}` |
| `update.check` | 同步(触发后台) | `{}` | `{}`;状态经 `update.state` 事件推送 |
| `update.download` | **(job)** | `{}` | `{jobId}`;进度 `update.progress`,结束 `update.state=ready` |
| `update.install` | 同步 | `{}` | `{}`;校验安装包后启动分离的 PowerShell 助手并退出应用 |
| `update.skip` | 同步 | `{version}` | `{skippedVersion}`;写入 settings.json,启动检查不再提示该版本 |

清单固定从 GitHub Releases 的 `latest.json` 读取,可用环境变量 `DESKTOP_PET_UPDATE_URL` 覆盖(测试用)。只有冻结后的安装版允许 `update.install`;开发版返回 `CONFLICT`。下载文件先写 `.part`,SHA256 与大小校验通过后才改为正式文件名。

## 5. 事件目录(backend → JS)

前端统一 `bridge.on(name, cb)` 订阅。payload 均为对象。

### 5.1 助手流水线(AssistantWorker 信号 → 桥事件)

| 事件 | payload | 说明 |
|---|---|---|
| `assistant.state` | `{state: 'idle'\|'searching'\|'knowledge'\|'responding'\|'stopped'\|'failed', jobId, sessionId, sources?, knowledge?}` | 生命周期汇总事件,前端主状态机依据;`sources` 随 searching 增量出现,`knowledge` 随 knowledge 出现 |
| `assistant.chunk` | `{jobId, sessionId, text}` | **流式增量**。桥内 100ms 定时器把缓冲内容按 `reply_preview` 去重后推送,避免事件风暴 |
| `assistant.result` | `{jobId, sessionId, reply, tasks, errors, choice, note, notices, sources, knowledge, meta}` | 终态;`tasks` 为后端已落库的操作回执,`choice` 为多义待办提示词,`note` 为未采用建议,`notices` 为搜索失败等提示,`meta` 为「小满 · 模型 · 用时」 |
| `assistant.failed` | `{jobId, sessionId, message, retryable}` | 失败前消息留在 `retry_by_session`,可 `chat.retry` |
| `plan.result` | `{snapshot, reply, jobId, sessionId}` | 仅 `chat.planToday(confirmed:true)` 产出,daily_snapshot 结构见 planning.py |
| `chat.changed` | `{reason: 'user'\|'result'\|'choice'\|'create'\|'rename'\|'regenerate', sessionId, title, messageCount}` | 会话栏增量刷新依据 |

### 5.2 作业进度(知识库导入/重建、连接测试、钉钉)

| 事件 | payload |
|---|---|
| `knowledge.jobProgress` | `{jobId, message}`(当前正在处理的文件) |
| `knowledge.jobDone` | `{jobId, ok, message, added?}` |
| `connection.testResult` | `{jobId, kind: 'model'\|'tavily'\|'dingtalk', ok, message}` |
| `dingtalk.pushResult` | `{jobId, ok, message}` |

### 5.3 壳子定时器驱动(无对应前端发起的请求)

| 事件 | payload | 说明 |
|---|---|---|
| `reminder.due` | `{tasks: ReminderTask[]}` | 2s 检查命中。`ReminderTask` 附带 `remind_count / deferred / final`;提醒卡由壳子的 `ReminderPopup` 绘制在宠物头顶,前端仅按需刷新任务数据,`REMIND_LIMIT=3` 后的 deferred 逻辑留在壳子 |
| `reminder.early` | `{tasks: ReminderTask[]}` | 提前提点,附加 `minutesLeft` |
| `tasks.changed` | `{reason}` | 任务状态变化后广播。桥方法写入 `reason` 为动作名(`add/edit/action/reopen/...`),壳子定时器写入 `reminder/early/quiet`;前端收到后重拉 `tasks.list` 与统计 |
| `settings.changed` | `{patch}` | `settings.set` 落盘后广播(含宠物窗在内的所有 view 订阅,用于同步主题/密度) |
| `update.state` | `UpdateState` | 检查/下载/安装状态变化;启动自动检查也会推送,设置页挂载时另用 `update.get` 兜底 |
| `update.progress` | `{jobId, received, total}` | 更新包下载进度,约每 256KB 一次 |
| `pet.changed` | `{active, changed}` | 宠物形象变更(`pet.select` 或壳侧选图/去背景/还原完成后);设置页收到后重拉 `pet.gallery` |
| `pet.say` | `{text}` | 壳子要求宠物窗显示气泡(宠物窗 HTML 订阅);2D 的 QLabel 气泡仍由壳子直接调用 |
| `ui.navigate` | `{page}` | 壳子请求主窗切页(目前用于提醒卡的「打开待办 →」);前端收到后切换 side bar 选中页 |

提醒**卡片/声音/托盘 notify/钉钉推送**都由壳子执行,不依赖前端是否可见:卡片是宠物头顶的无边框 `ReminderPopup`,不占用主窗布局。卡片按钮直接调壳侧 `resolve_reminder`(完成/顺延/静音/跳转任务页);消息中心 `tasks.dismissReminder` 也会收起对应卡片,开启 `auto_postpone` 时壳子顺延 10 分钟。

## 6. 线程与生命周期规则

1. **QWebChannel 的 slot 调用在主线程事件循环中执行**,与 TaskStore「仅主线程」的现有约束天然兼容(core.py 使用主线程 sqlite 连接);桥层同步方法可直接调用 store,无需加锁。
2. **作业方法不得阻塞主线程**:沿用现有后台机制(AssistantWorker QThread、`threading.Thread` + Qt 信号回主线程 app.py:136-141 模式),把现有信号转发为 §5 事件即可。桥层维护 `jobId → cancel Event` 表,`bridge.cancel` 置位。
3. **每 view 一个 channel 注册**,`BridgeHost` 可以是同一个实例(事件经 `event` signal 广播到所有 view,宠物窗因此能收到 `settings.changed`/`pet.say`)。
4. **页面就绪握手**:HTML 加载完成后 JS 主动调 `system.info`;壳子在 `loadFinished` 前缓冲的事件在握手后重放(避免首条提醒丢失)。
5. 生命周期:主窗关闭即注销 view;宠物窗常驻,页面 crash 时壳子负责 `reload()`(沿用现有 WebEngine 可选降级策略 pet.py:165)。

## 7. 安全与打包

- 页面一律 `QUrl.fromLocalFile` 加载本地产物,**禁用远程 origin**;壳子侧显式校验 URL 前缀,防止页面被重定向到外站后仍持有桥。
- 桥不提供任意文件读写:`system.pickFile` 只返回用户主动选择的路径,且接受方方法(如 `knowledge.importPaths`)按后缀白名单处理。
- 密钥仅入不出(§4.6);`invoke` 全量日志仅记录 method 与 ok/code,不落 payload 明文。
- `QTWEBENGINE_REMOTE_DEBUGGING` 仅 dev 构建开启(`system.info.devMode` 暴露给前端判断);发布构建关闭。
- qwebchannel.js 运行时从 `qrc:///qtwebchannel/qwebchannel.js` 加载,永远与运行时 Qt 版本匹配,不落盘 vendor。
- PyInstaller:新增 `web/dist/**` 资源目录与 qwebchannel.js;WebEngine 二进制已在依赖内,体积增量可忽略。

## 8. 客户端约定(TS)

```ts
// web/src/bridge/bridge.ts —— 唯一需要跟 Qt 打交道的文件
type Envelope = { ok: true; data: any } | { ok: false; error: { code: string; message: string } };

declare interface QWebChannel { objects: { bridge: QtBridge } }
interface QtBridge {
  invoke(method: string, payload: string, cb: (resp: string) => void): void;
  cancel(jobId: string): void;
  event: { connect(cb: (name: string, payload: string) => void): void };
}

export const bridge = {
  async invoke(method: string, args: object = {}): Promise<any> {
    return new Promise((resolve, reject) => {
      chan.objects.bridge.invoke(method, JSON.stringify(args), resp => {
        const env = JSON.parse(resp) as Envelope;
        env.ok ? resolve(env.data) : reject(new BridgeError(env.error));
      });
    });
  },
  on(name: string, cb: (payload: any) => void) {
    chan.objects.bridge.event.connect((evName, raw) => {
      if (evName === name) cb(JSON.parse(raw));
    });
  },
};
```

调用例:

```ts
const task = await bridge.invoke('tasks.add', { title, dueAt, repeat: 'daily' });
bridge.on('assistant.chunk', ({ text }) => appendStream(text));
```

## 9. 宠物窗的既有控制面(保持不变)

宠物窗页面(`web/public/pet3d/index.html`,随 web 构建复制到 `web/dist/pet3d/`)继续实现全局对象 `window.pet3d`,壳子经 `runJavaScript` 调用(pet.py:198-307):

`setPaused(bool)` · `lookAt(x, y)` · `react()` · `setDragging(bool)` · `setWalking(bool, dir)`

新增能力只加不改;壳子→页面的**新**通知(如主题 `settings.changed`)统一走 §5 事件,不再往 `window.pet3d` 上堆。气泡暂由壳侧 QLabel 承担(2D/3D 共用,见迁移计划 4.2)。窗口拖动/右键菜单/事件穿透过滤器(pet.py:328、pet3d.py:24)留在壳子侧。

## 10. Python 侧骨架

```python
# desktop_pet/bridge.py
class BridgeHost(QObject):
    event = Signal(str, str)  # name, payload-json

    def __init__(self, app_ctx):
        super().__init__()
        self._ctx = app_ctx          # 持有 store / settings / worker 工厂
        self._jobs: dict[str, threading.Event] = {}

    @Slot(str, str, result=str)
    def invoke(self, method: str, payload: str) -> str:
        args = json.loads(payload or '{}')
        try:
            data = dispatch(self._ctx, method, args, self)  # 纯查表转发
            return json.dumps({'ok': True, 'data': data}, ensure_ascii=False)
        except BridgeError as e:
            return json.dumps({'ok': False, 'error': e.to_dict()}, ensure_ascii=False)
        except Exception:
            log.exception('bridge invoke failed: %s', method)
            return json.dumps({'ok': False, 'error': {'code': 'INTERNAL', 'message': '内部错误'}}, ensure_ascii=False)

    @Slot(str)
    def cancel(self, job_id: str) -> None:
        if (ev := self._jobs.get(job_id)) is not None:
            ev.set()

    def emit_event(self, name: str, payload: dict) -> None:
        self.event.emit(name, json.dumps(payload, ensure_ascii=False))
```

`dispatch` 为模块函数注册表(`TASKS_METHODS`, `CHAT_METHODS`, ...),每个模块文件提供 `handle(method, args, ctx)`,与后端方法一一对应;**禁止在桥层写业务逻辑**,发现缺字段/缺行为时改后端,不改桥。

## 11. 迁移顺序(摘要)

1. **基建**:bridge.py + web/ 脚手架(Vite + bridge.ts + qwebchannel.js vendor),主窗口中央区先放一个空白 WebView 验证握手、事件广播与打包链路。
2. **设置页**(settings.py 1856 行,样式密集、几乎全同步调用,性价比最高):settings/secrets/system/knowledge 四组方法 + 相关事件。
3. **任务页 + 首页**:tasks/drafts 方法 + `reminder.*`/`tasks.changed` 事件,提醒弹窗并入主窗 Web 层。
4. **聊天栏**:chat 方法 + `assistant.*` 事件(流式节流逻辑后端保留)。
5. **宠物窗**:3D 页面并入前端工程,保留 `window.pet3d` 契约;2D 帧动画与气泡暂留 Qt(见 [WEB_MIGRATION_PLAN.md](WEB_MIGRATION_PLAN.md) 4.2/4.3)。
6. 收尾:删除对应 QWidget 代码与 PySide6-Fluent-Widgets 依赖;移除 `ui_shell`,web 成为唯一 UI(已完成)。
