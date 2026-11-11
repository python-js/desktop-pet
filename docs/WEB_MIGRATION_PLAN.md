# 「壳子 + HTML」迁移计划

> 配套协议设计见 [BRIDGE_API.md](BRIDGE_API.md)。
> **进度更新规则**:完成一项,把该项 `- [ ]` 改为 `- [x]`,并在文末「进度记录」表追加一行(日期 / 项 / 备注)。中途取消或改方案的项标记 `~- [ ] ~`(删除线)并写明原因。
> 初期计划曾要求每阶段保留 Qt UI；Phase 5 已移除这一要求及 `ui_shell` 开关。当前 Web 是唯一主窗口界面，迁移收尾项仍需目标机验证。

## 总体策略

- **阶段边界即发布边界**:每阶段应独立审查、提交并验证发行包；当前工作区迁移尚未提交，最近的打包产物早于 Phase 5 收尾。
- **先基建后页面,先简单页后复杂页**:设置页(几乎全同步调用)→ 任务/首页(定时器事件)→ 聊天(流式)→ 宠物窗(透明窗风险)。
- **桥层零业务逻辑**:桥只做转发与编解码;发现能力缺口改后端方法,不改桥(见 BRIDGE_API.md §10)。

---

## Phase 0 — 基建与握手验证(目标:空白 WebView 跑通桥 + 打包链路)

- [x] **0.1 前端工程脚手架**:新建 `web/`,Vite + TypeScript + **React**(用户选型)。目录:`web/src/bridge/`(bridge.ts 客户端)、`web/src/pages/`。构建产物 `web/dist/`。技术约定:函数组件 + hooks,不引重型 UI 库(Fluent 风格自建 CSS)。**实现调整**:qwebchannel.js 不落盘 vendor(PySide6 wheel 里没有该文件),页面运行时从 `qrc:///qtwebchannel/qwebchannel.js` 加载,永远与运行时 Qt 版本匹配;构建采用 `vite-plugin-singlefile` 单文件产物——Chromium 禁止 file:// 页面跨源拉取 ES module,必须内联(与 pet3d 用普通 script 同理)。
- [x] **0.2 bridge.py 骨架**:`desktop_pet/bridge.py` — `BridgeHost`(invoke/cancel/event 三入口)、模块注册表 dispatch、`BridgeError` + 错误码、`system.info`、作业表(`create_job/finish_job/cancel`)。单测 `tests/test_bridge.py` 13 项全过(dispatch 路由、信封编解码、NOT_FOUND、INTERNAL 脱敏、缓冲重放、作业生命周期)。
- [x] **0.3 主窗嵌入 WebView**:settings 白名单新增 `ui_shell: 'qt' | 'web'`(默认 qt)。`ui/webshell.py` 的 `WebShell` 用独立 QWebChannel 挂 `bridge` 对象、file:// 加载 `web/dist/index.html`;QtWebEngine 缺失时回退 qt 模式并提示。qt 模式行为与现状完全一致(全量 176 项测试无回归)。
- [x] **0.4 握手与事件机制验证**:握手 = JS 调 `system.info`,触发桥侧缓冲事件重放(BridgeHost `_pending_events`)。冒烟脚本 `tools/webshell_smoke.py` 实机验证:握手成功、缓冲事件按序重放、截图确认页面渲染(见 `build/webshell-smoke.png`)。
- [x] **0.5 打包与构建链路**:`build_windows.py` 加入 npm 构建前置(node_modules 缺失时自动 `npm ci`)、`--add-data web/dist;web`、web 产物缺文件即构建失败;dev 模式经 `DESKTOP_PET_DEV` → `QTWEBENGINE_REMOTE_DEBUGGING=127.0.0.1:9223`。两次完整打包 + 打包自带 smoke-test 均通过。
- [x] **0.6 阶段验收**:`tools/packaged_check.py` 用隔离数据目录实测打包 exe:qt 模式 2757ms / web 模式 2449ms 出主窗;web 模式截图确认握手成功(`app.launched` 事件重放、数据目录回显正确)。启动耗时无显著差异,无需 WebEngine 预启动。
- [x] **0.6 阶段验收**:打包 exe 两个模式各启动一次,记录启动耗时对比(基线)。基线:qt 2757ms / web 2449ms(`tools/packaged_check.py`,2026-11-06)。

## Phase 1 — 设置页(1,856 行 QWidget → HTML,全同步调用为主)

- [x] **1.1 settings 方法组**:`settings.getAll` / `settings.set`(白名单逐键校验,对齐 settings.py:1298-1302)/ `settings.changed` 事件落盘后广播。**实现**:bridge_modules/settings.py;api_key/tavily_key 永不下发,pet_images/pet_position 只读。
- [x] **1.2 密钥与连接测试**:`secrets.*`(save/status/rememberKey,只入不出)+ 三个连接测试 + `connection.testResult` 事件。**实现调整**:三种测试合并为 `secrets.testConnection {kind: model|tavily|dingtalk}` 单入口(带作业线程),替代原设计的三个方法;`secrets.status` 增 `hasDingtalk`。saveApiKey 同时校验/更新 `base_url` 端点。
- [x] **1.3 知识库面板**:`knowledge.documents/stats/search/importPaths/remove/clear/rebuild` + `knowledge.jobProgress/jobDone` 事件(取消沿用 job Event)。`system.pickFile/pickFolder/pickImage` 原生选择器一并实现。**实现调整**:进度事件 payload 为 `{jobId, message}`(当前文件名),非 `{done,total}`;clear/rebuild 为同步调用(与 Qt 侧一致,SQLite 单事务),仅 importPaths 为作业。
- [x] **1.4 系统项**:`startup.get/set`、`system.openPath`、`settings.exportData`、`settings.clearData`、`system.pickSavePath`。**实现调整**:clearData 为同步方法(先备份后清库、主线程事务,与 Qt 侧一致;两次确认由前端承担),导出走「pickSavePath → exportData {path}」两步;`dingtalk.sendPreview` 并入 `secrets.testConnection {kind:'dingtalk'}`(Qt 侧本就只有测试发送,无预览功能)。
- [x] **1.5 HTML 设置页 UI**:模型与密钥 / 联网搜索 / 知识库 / 钉钉 / 提醒偏好(提前提点、勿扰时段、自动顺延、声音)/ 启动项 / 数据管理(导出、清空)。主题(light/dark)、密度切换即时生效(纯前端状态 + `settings.set`)。**实现调整**:UI 栈改为 **HeroUI v3 + Tailwind CSS v4**(原「自建 CSS」约定作废,`web/src/ui.tsx` 为 v3 复合组件薄封装);Tailwind 走 `@tailwindcss/vite`,主题变量经 `@theme inline` 映射 HeroUI 运行时 CSS 变量,无 `tailwind.config.js`/PostCSS。
- [x] **1.6 宠物外观入口**:选图/去背景/还原暂留壳侧(原生对话框),设置页只放按钮 + 预览,经 `pet.*` 方法触发、**`pet.changed`** 刷新预览。**实现**:`bridge_modules/pet.py`(`pet.gallery/select/chooseImage/removeImage/removeBackground/restoreOriginal/resetPosition`);默认宠物由代码绘制,故缩略图/预览以 base64 PNG data URL 下发,历史图同样走 data URL,不暴露本地路径。
- [x] **1.7 阶段验收**:`ui_shell=web` 下完成一次「保存 API Key → 测试连接 → 导入知识库 → 改主题 → 重启设置留存」全流程;qt 模式无回归。**验收**:HeroUI v3 产物经 `tools/webshell_settings_check.py` 离屏实测——9 张卡(含「宠物形象」)、26 按钮、9 开关、宠物瓦片渲染,控制台零报错,截图 `build/webshell-settings-v3.png`;`npm run build` 通过(dist/index.html 997.84 kB);全量 203 项 Python 测试通过。

## Phase 2 — 任务页 + 首页 + 提醒

- [x] **2.1 tasks 方法组**:`tasks.list/history/add/edit/complete/reopen/delete/undoDelete/snooze/setDingtalk/muteToday/stats/todayEvents/parseDue/dismissReminder`(对齐 core.py TaskStore 签名,dict(row) 直出)。
- [x] **2.2 drafts 方法组**:`drafts.list/save/confirm/discard`。
- [x] **2.3 提醒事件桥接**:2s `check_due` / 提前提醒定时器留在壳子,命中时发 `reminder.due` / `reminder.early`;`REMIND_LIMIT` 顺延、静默时段、声音/托盘/钉钉推送全部留壳子,状态变化发 `tasks.changed`。
- [x] **2.4 HTML 首页**:统计卡(today_stats)+ 今日事件流(today_events)+ 到期任务 hero 卡(完成/稍后/免打扰今日)。
- [x] **2.5 HTML 任务页**:待办/历史列表、搜索、筛选、新增/编辑表单(`parseDue` 实时解析回显)、多选完成/删除、撤销删除、钉钉开关。
- [x] **2.6 提醒卡回到壳子层**:原 QWidget 主窗内提醒改为宠物头顶的 `ReminderPopup`(`desktop_pet/ui/reminder_popup.py`),无边框置顶、跟随宠物拖动、多张纵向堆叠;按钮直接调壳侧 `resolve_reminder`(完成/10 分钟后/今天别再说/打开待办),主窗不再渲染提醒卡。托盘 notify 仅在宠物隐藏时使用,避免与头顶卡片重复。
- [x] **2.7 阶段验收**:新建 1 分钟后到期的任务,验证提醒弹出、三种解决方式、重复任务 complete 后 next_id 链;勿扰时段内静默;qt 模式无回归。

## Phase 3 — 聊天

- [x] **3.1 chat 方法组**:`chat.sessions/session/createSession/renameSession/saveInput/messages/send/retry/regenerate/stop/chooseTask/planToday`。AssistantWorker 信号 → BridgeHost 事件(`assistant.state/chunk/result/failed` + `plan.result`),100ms 流式节流保留在壳子侧。**实现**:`bridge_modules/chat.py`;`chat.retry` 为补充分支(失败/停止后重放);`worker_factory` 可注入供离屏验收。
- [x] **3.2 HTML 会话栏 + 消息流**:会话切换、未发送草稿保存(`saveInput`,400ms 防抖)、流式渲染、停止按钮、重新生成(branch 逻辑留后端)。**实现**:`web/src/pages/ChatPage.tsx` + `components/Markdown.tsx`(仅生成 React 节点,不用 innerHTML)。
- [x] **3.3 任务指令回执**:`result` 中 `reply/tasks/errors/choice/note/notices` 的渲染;多义任务序号按钮(`chooseTask`);任务变更后刷新任务页(前端内跳转)。
- [x] **3.4 显式草稿卡**:独立草稿记录的 `drafts.confirm/discard` HTML 组件。**边界**:它只处理显式保存的草稿；聊天中通过校验的待办操作由后端直接执行，不要求再次确认或保存。
- [x] **3.5 当日规划**:`planToday` 入口(先只读预览,确认后再发) + `plan.result` 渲染(daily_snapshot 卡片)。
- [x] **3.6 阶段验收**:联网搜索意图、知识库命中、流式 + 停止、重新生成、任务指令「明天 9 点提醒我开会」落库全链路;qt 模式无回归。**验收**:`tools/webshell_phase3_check.py` 离屏 24 项全过(真实 MainWindow + 脚本化模型流),截图 `build/webshell-chat-*-phase3.png`(需去掉 `QT_QPA_PLATFORM=offscreen` 运行,离屏 WebEngine 不参与 `QWidget.grab`);全量 224 项 Python 测试通过。

## Phase 4 — 宠物窗

- [x] **4.1 HTML 并入前端工程**:把 `assets/pet3d/index.html` 迁为 `web/` 页面(独立入口),壳子改加载新产物;`window.pet3d` 契约(setPaused/lookAt/react/setDragging/setWalking)保持不变,pet.py 调用零改动。**实现调整**:页面与 three.js/GLTFLoader/两个模型移到 `web/public/pet3d/`,由 vite 构建原样复制到 `web/dist/pet3d/`(保留普通 script,不引入 npm three,避免 r147 API 与 file:// 加载方式变化);`pet3d.scene_path()` 源码运行读 `web/public/pet3d`,冻结后读 `_MEIPASS/web/pet3d`,`DESKTOP_PET_WEB_DIST` 仍可覆盖;打包校验改查 `_internal/web/pet3d`。
- [x] **4.2 桌宠窗口评估**:决定保留 QWidget + QWebEngine 混合模式；2D 图片、气泡、拖拽、右键菜单和位置由 Qt 宿主管理，3D 场景由独立的本地 WebEngine 页面渲染。本项评估已完成；若未来迁移整只宠物窗，仍需单独验证透明窗口输入和多屏逻辑。
- [x] **4.3 2D 模式决策与处理**:保留混合边界，避免在主窗口迁移中同时重写桌宠窗口输入、多屏定位和气泡逻辑。旧条目中动作帧和 QPixmap 细节仅作历史记录。
- [x] **4.4 拖动/右键菜单/穿透回归**:事件过滤器(pet3d.py:24)在新技术栈下逐一验证:拖动窗口、双击、右键菜单、`lookAt` 鼠标跟随、走动模式。**验收**:`.artifacts/pet3d_phase4_check.py` 真实窗口 18 项检查全部符合预期——页面指向新产物、`window.pet3d` 存在;单击触发 `react` 且气泡可见;拖动位移 40×30 并写入位置;双击打开主窗 1 次;右键菜单 7 项完整;`setWalking`/`setPaused` 到达页面;巡逻 1.2s 实际位移;2D/3D 往返后尺寸与定时器正常。
- [ ] **4.5 阶段验收**:打包版常驻 30 分钟——内存稳定、无 crash reload、多屏 `ensureVisible`、休眠唤醒后正常。**当前进度**:PyInstaller 打包通过自带 smoke-test,打包 exe 用临时数据目录启动并截图确认 3D 页面来自 `_internal/web/pet3d`;打包实例 5 分钟常驻主进程 262.3→212.9 MB、渲染子进程稳定,无退出或重载。源码版真实数据 30 分钟常驻进程树 487.0→442.2 MB(中段峰值 512.6 MB),两个渲染子进程 PID 未变、窗口持续响应。打包版 30 分钟常驻、多屏 `ensureVisible` 与休眠唤醒需在目标机器补测(本轮单屏 2560×1440@1x)。

## Phase 5 — 收尾

- [x] **5.1 删除迁移完成的 QWidget 代码**:ui/settings.py、ui/tasks.py、ui/home.py、ui/chat_*、ui/reminder.py、ui/draft_card.py 及对应 mixin;requirements 移除 `PySide6-Fluent-Widgets`。**实现**:新增 `desktop_pet/shell.py`(`ShellMixin`:配置持久化、密钥恢复、宠物图片/主题/位置等壳侧动作),`app.py` 只保留 `AssistantWorker`、任务操作、提醒调度、托盘与宠物窗;删除 15 个 Qt 页面/控件模块及 `ui/motion.py`、`tools/check_fluent.py`、`requirements-fluent.txt`、`launch-fluent.ps1`;`diagnostics.py` 改为 web 自检(不再创建 MainWindow);桥模块移除 `refresh_*`/`register_deleted` 死钩子。
- [x] **5.2 移除 `ui_shell` 开关**:web 成为唯一 UI。**实现**:`shell.persist_settings`、`bridge_modules/settings.py` 白名单、`web/src/api.ts` 均删除 `ui_shell`/`sidebar_collapsed`;`main()` 启动时缺少 QtWebEngine 直接提示并退出,不再回退 Qt。
- [x] **5.3 文档**:README 更新到 React + QWebChannel 唯一界面、当前任务自动执行语义及源码启动；构建说明更新版本、目录结构、分发方式和验收边界；BRIDGE_API 按当前代码核对；本计划修正初期 Qt 双栈要求及桌宠窗仍采用混合渲染的现状。
- [ ] **5.4 回归清单过一遍**:Win10/Win11、125%/150% DPI、双屏、暗色主题、静默启动、单实例锁、数据从旧版升级(scheme v7 兼容)、知识库/密钥迁移。

---

## 风险与预案

| 风险 | 触发点 | 预案 |
|---|---|---|
| WebEngine 透明窗渲染异常(新版驱动/系统) | Phase 4 | pet3d 现方案已验证过;异常时宠物窗保留现有加载方式不迁移 |
| 流式渲染事件过载 | Phase 3 | 节流留在壳子侧(现状 100ms);仍卡则 chunk 合并为增量包 |
| PyInstaller 未带上 web/dist 或 qwebchannel.js | Phase 0.5 | 0.5 即验证打包链路,不拖到最后 |
| 启动耗时显著增加(>2s) | Phase 0.6 | WebEngine 改为预启动(后台进程提前拉起),或主窗先显示骨架 |
| 桥信封类型边角(QVariant/日期序列化) | 各阶段 | 信封全用字符串;ISO 字符串日期不经 QVariant 转换 |

## 进度记录

| 日期 | 项 | 备注 |
|---|---|---|
| 2026-11-06 | 计划创建 | 基于 BRIDGE_API.md v1 |
| 2026-11-06 | 0.1 决策更新 | 前端框架定为 React(Vite + TS),原 Vue 3 方案作废 |
| 2026-11-06 | 0.1–0.4 完成 | qwebchannel 走 qrc://、改 singlefile 构建(file:// 禁跨源 module);bridge 13 单测、全量 176 测试无回归;冒烟截图确认握手与事件重放 |
| 2026-11-06 | 0.5 进行中 | build_windows.py 已接入 npm 构建与 web 产物校验,打包实测运行中 |
| 2026-11-06 | Phase 0 完成 | 0.5/0.6 验收通过:打包版 qt 2757ms / web 2449ms 出窗,web 模式握手截图确认;补 `load_configuration` 读取 `ui_shell` |
| 2026-11-06 | 1.1–1.4 完成 | bridge_modules 包(settings/secrets/system/knowledge)接入 app.py;BRIDGE_API.md 按实现修订(连接测试合并为 secrets.testConnection、jobProgress payload、export/clear 流程);24 项桥模块单测 + 全量 197 测试通过 |
| 2026-11-09 | 1.5 完成 | 设置页 9 张卡全部落地;前端 UI 栈切换为 HeroUI v3.2.7 + Tailwind CSS v4(React 19),移除 framer-motion 与 PostCSS 配置,主题变量改走 `@theme inline` |
| 2026-11-09 | 1.6 完成 | `pet.*` 桥接模块(7 方法 + `pet.changed`);原生选图/去背景/还原仍留壳侧,缩略图与预览改用 base64 PNG data URL;桥模块单测 27 项通过 |
| 2026-11-09 | 1.7 完成 | v3 产物离屏实测:9 卡 / 26 按钮 / 9 开关 / 宠物瓦片渲染,控制台零报错;截图 `build/webshell-settings-v3.png`;dist 997.84 kB;全量 Python 测试通过 |
| 2026-11-09 | 2.1–2.3 完成 | `tasks.*`(15 方法,含 `parseDue`/`dismissReminder`)与 `drafts.*`(4 方法)接入;web 模式 `check_due_web` 发 `reminder.due/early` + `tasks.changed`,静默记录、REMIND_LIMIT、自动顺延仍留壳子;桥模块单测 37 项 |
| 2026-11-09 | 2.4–2.6 完成 | React 首页/任务页/提醒卡落地(侧边栏 4 入口);任务表单支持 `parseDue` 实时回显、重复/钉钉开关、批量完成/删除/撤销;提醒卡支持完成/顺延/今日免打扰/打开待办,关闭自动顺延 |
| 2026-11-09 | 2.7 完成 | `tools/webshell_phase2_check.py` 离屏 18 项全过(提醒三路径、重复任务 next_id、勿扰静默、提前提点、表单解析落库);设置页回归 9 卡/30 按钮/9 开关零报错;dist 1,025.96 kB;全量 Python 213 测试通过 |
| 2026-11-10 | 3.1–3.5 完成 | `bridge_modules/chat.py`(11 方法 + retry 补充)与 11 项桥单测;`AssistantWorker` 信号经 `_Relay`(以 BridgeHost 为父、主线程投递)转 `assistant.state/chunk/result/failed` + `plan.result` + `chat.changed`;100ms 节流留在桥内;`quit_app` 同时取消 web 侧 worker |
| 2026-11-10 | 3.2–3.5 前端 | `ChatPage.tsx`(会话栏/流式/停止/重试/重新生成/序号按钮/草稿卡/规划预览与快照)+ `Markdown.tsx`(纯 React 节点渲染,链接仅 http(s));`App.tsx` 以 `ChatPage` 替换占位符 |
| 2026-11-10 | 3.6 完成 | `tools/webshell_phase3_check.py` 离屏 24 项全过:本地规则「明天 09:00 提醒我开会」落库、搜索/知识来源渲染、流式中途可见且终态不重复、停止不落库且可重试、重新生成分支、多义序号、规划预览→快照、草稿确认后跳任务页;控制台零报错;`npm run build` 通过;全量 224 项 Python 测试通过(qt 模式聊天 UI 用例在内);截图以非 offscreen 平台重跑生成,三张均为真实界面 |
| 2026-11-10 | 5.1–5.2 完成 | 删除 15 个 Qt 页面/控件模块与 Fluent 依赖,新增 `shell.py` 承载壳侧配置/密钥/宠物动作;`ui_shell`、`sidebar_collapsed` 从设置白名单、持久化与前端类型中移除;测试改为注入无头 `WebShell` 桩,避免 offscreen 下 QtWebEngine 退出崩溃;全量 169 项测试通过 |
| 2026-11-11 | 5.3 文档收尾 | README、Windows 构建说明、迁移计划与桥接协议同步到当前 React/QWebChannel、聊天待办直接执行语义及显式草稿 API 边界；明确旧 Qt 页面已删除、旧发行包早于本次迁移及目标机验收边界 |
| 2026-11-10 | 5.5 回归 | 全量 169 项测试通过;`npm run build` 1,050.77 kB;设置/Phase 2/Phase 3 真实 WebEngine 检查全过、控制台零报错;PyInstaller 构建 `windows-0.30.1-20261110-133335-429837` 与打包 smoke-test(5 项)通过;打包 exe 隔离数据启动 1,098ms 并渲染首页 |
| 2026-11-10 | 5.4 待办 | 需在目标机器验证 Win10/Win11、125%/150% DPI、双屏、暗色、静默启动、单实例锁、schema v7 升级与知识库/密钥迁移 |
| 2026-11-10 | 4.1 完成 | pet3d 页面与模型移入 `web/public/pet3d/`,vite 构建复制到 `web/dist/pet3d/`;`scene_path()` 支持源码/冻结/环境覆盖,打包校验与文档路径同步;实机截图确认新页面正常渲染哈士奇 |
| 2026-11-10 | 4.2/4.3 决策 | 2D 帧动画暂留 Qt;气泡保留 QLabel,4.2 取消并写明原因 |
| 2026-11-10 | 4.4 完成 | 真实窗口契约回归 18 项全过;全量 224 项测试通过 |
| 2026-11-10 | 4.5 部分完成 | 打包实例 5 分钟 + 源码版 30 分钟常驻内存稳定、渲染进程未重载;打包版 30 分钟/多屏/休眠唤醒待目标机器补测 |
| 2026-11-10 | 提醒回壳 + 交互修正 | 提醒卡改为宠物头顶 `ReminderPopup`(跟随拖动/纵向堆叠/四按钮),删除 Web 侧 `ReminderStack` 与对应 CSS,新增 `ui.navigate` 支持「打开待办 →」跳页;对话页去掉滚动条(`.content-chat` 全量隐藏,滚轮仍可滚);侧栏可在底部按钮手动收起/展开(68px↔232px,`localStorage: pet.railCollapsed`);Phase 2 23 项、Phase 3 25 项、全量 169 项测试通过 |
