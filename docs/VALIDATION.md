# 验证记录

> 本文记录不同时间点的验证，不能将旧记录直接等同于当前工作区的回归结果。Phase 5 已删除全部主窗口 Qt 页面与 Fluent 依赖；旧 Qt 页面测试条目仅供追溯，当前工作区测试数量、WebEngine 与目标机验收以对应日期的记录为准。桌宠仍使用 Qt 宿主。

日期：2026-10-26；环境：Windows，Python 3.11.9。

## 已完成

- 9 项标准库核心测试通过：时区归一化、非法/过去时间拒绝、任务编辑、到期查询、通知去重、重启恢复、延期完成、消息排序、模型建议校验、兼容请求构造、服务地址限制、本地规则识别。
- 建立独立 `.venv`，不使用原项目虚拟环境。
- 对全部新增 Python 源码做语法编译检查。
- 用户安装依赖后，独立环境完整运行 10 项测试，全部通过，无跳过。
- offscreen 界面流程测试通过：三页窗口构建、模型建议进入草稿且不自动入库、到期提醒窗口创建、延期关闭提醒、完成清除待办。测试使用临时数据，不影响用户当前运行的实例。
- 用户确认应用已成功启动。

## 未通过环境准备 / 未验证

- 沙箱联网安装 `PyQt5==5.15.11` 失败（WinError 10013）。随后正常申请联网安装审批，但审批服务返回 `model_not_found`，安装操作没有执行。没有绕过审批安装或复制原项目环境。
- 上述依赖问题已由用户安装解决。用户确认真实应用启动；自动化已验证 offscreen 界面流程，但尚未验证截图、透明窗口效果、鼠标交互和真实托盘通知。
- 未使用真实 API Key，没有产生模型服务请求或费用。网络协议测试使用模拟响应。
- 未验证 Windows 休眠恢复、通知权限、安装包、macOS。

## 继续验证

用户可按 README 安装依赖后运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m desktop_pet
```

依次验证：规则生成草稿 → 修改时间保存 → 到期提醒 → 延期 → 完成 → 退出重启恢复。然后使用自己的模型服务配置验证自由聊天与多条任务规划。

当前交付为可继续开发的源码原型，尚未达到已验证的可发行状态。

## 0.2 增量验证

- 用户确认真实 Windows 提醒已经弹出。
- 15 项测试全部通过：13 项核心测试与 2 项 Qt 界面集成测试；无跳过。另完成 Python 语法编译检查。
- 新覆盖：v1 数据库自动备份并保留任务及聊天、草稿编辑/重启恢复、过期草稿不入库、原子保存防止重复、历史搜索、软删除恢复原状态、恢复待办、真实工作线程失败后重试不重复添加用户消息。
- 迁移测试发现备份连接未关闭，导致 Windows 文件锁；已改为显式关闭，并通过回归。
- 在临时数据目录生成 offscreen 待办页预览，检查筛选栏、计数、任务列表与操作栏布局。此检查不连接真实模型、不修改用户数据，不能代替多屏/高 DPI 验收。
- 未确认草稿现在保存到 SQLite，重启恢复；重试仅针对失败请求，尚无流式、中止或正常回复重新生成。

## 0.3 增量验证

- 18 项测试全部通过（15 项核心、3 项 offscreen UI 集成），无跳过；语法编译通过。
- 新覆盖：真实 v2 表结构升级到 v3，旧消息与草稿自动归入默认会话且数据库已备份；各会话的上下文、草稿、未发送文字隔离与重启持久化；自动命名和重命名校验。
- 工作线程测试在回复前切换会话，验证结果及建议只进入原会话；切回恢复草稿；点击独立草稿组件保存后正确写任务并移除草稿。
- 失败重试测试扩展为切换会话后入口隔离，返回原会话重试不重复添加原消息。
- 本轮未连接真实模型，未自动关闭或启动用户桌面实例；更新后需退出旧进程再启动。流式与中止仍待开发。

## 0.4 增量验证

- 27 项测试全部通过（21 项标准库核心/传输测试，6 项 offscreen 界面测试）；无跳过。Python 源码编译通过。
- 新增 SSE 测试：中文分片、usage事件、注释、完整结束、提前断流、截断、大小限制、取消检查、流式请求构造和关闭流式的回退读取。
- 回复预览测试覆盖不完整JSON、换行转义、截断Unicode、代理对表情，确保不展示tasks内部字段。
- 工作线程集成测试覆盖分片预览跨会话恢复、取消时晚到完整回复被丢弃且无草稿、退出等待线程结束后再关闭数据库。
- 临时目录生成流式预览截图检查布局；没有读取用户密钥、连接真实服务或修改当前桌面实例。
- 未验证真实供应商的SSE、代理断线和DNS超时；协作取消在阻塞读取期间可能等待约45秒，不保证服务端立刻停止生成或计费。此限制已写入设计与使用说明。

## 0.5 增量验证

- 34 项测试通过（28 项核心/传输，6 项 Qt 界面），无跳过；语法编译通过。
- 新增7项重复任务测试：闰日跨月、跳过周末与过去日期、每周保持星期、延期/标题编辑保持原时刻、重复完成去重、删除/撤销和关闭重复、重复草稿、非法模型repeat、本地模式解析、日期筛选及schema 3→4备份升级。
- 扩展Qt集成流程：时间筛选、草稿选择每天并确认、完成后列表出现唯一下一次任务。
- 旧schema 1/2升级用例继续通过；本轮未打开用户真实数据库或修改当前运行的桌面实例。
- 固定UTC偏移的重复计划、完成后才生成下一次、周一至五不含法定假日日历的限制已写入说明与界面提示；多日真实运行及真实模型建议仍待联调。

## 0.6 增量验证

- 40项测试全部通过（33项核心/传输/平台适配测试，7项Qt集成）；语法编译通过。
- 新测试使用虚构密钥与可注入加密器，验证密文文件恢复、服务地址匹配、删除、损坏处理、失败保留原文件及不支持平台拒绝保存。
- 启动项使用内存注册表替身，验证带空格路径转义、优先pythonw、缺失启动文件拒绝、删除只影响本应用的值。
- Qt测试覆盖密钥重启恢复、配置不包含明文、改服务地址阻止复用、关闭记住移除文件、保存模型不改启动项、只有显式应用启动设置才调用适配器。
- 原生DPAPI内存探测返回0x2，真实加解密未验证成功。未读取用户真实密钥、未写入真实注册表、未改变当前程序启动状态。需要正常用户桌面会话验收，不能将40项模拟/集成测试等同于真实登录自启已通过。

## 0.7 宠物互动（2026-10-26）

- `python -m unittest discover -s tests -q`：41 项通过。
- `python -m compileall -q desktop_pet tests launch.py`：通过。
- 新增离屏回归覆盖：图片重启恢复、位置与暂停状态持久化、点击反馈、越界坐标校正、动画恢复、隐藏后找回。使用临时目录，不修改真实用户数据。
- 尚需正常桌面验证：真实拖动、多屏拔插和透明窗口效果。图片仍为本地静态形象配浮动动画，未实现自动去背景或 2D/3D 生成。

## 0.8 今日规划（2026-10-26）

- 全量 `python -m unittest discover -s tests -q`：45项通过。
- `python -m compileall -q desktop_pet tests launch.py`：通过。
- 新增：本地日界线与UTC输入、已完成过滤、30条上限及省略数、保留今天任务、空清单、拒绝无时区测试时间。
- 离屏集成：取消无消息写入、无模型本地清单、保留未发送输入、任务数据不变、模拟模型收到快照、生成期间规划入口禁用及结束恢复。
- 未调用真实模型服务、未读取真实密钥；真实供应商效果待验证。测试仅使用临时数据目录。

## 0.9 回复重新生成（2026-10-26）

- 全量 `python -m unittest discover -s tests -q`：51项通过。
- `python -m compileall -q desktop_pet tests launch.py`：通过。
- 新增存储测试：只复制末问题之前上下文、不复制原回复和草稿、保留原输入、未回答问题拒绝生成、上下文最多20条、分支会话重开持久化。
- 新增离屏集成：生成后切回原会话结果不串话、失败重试无重复问题、停止丢弃结果、原回复和草稿保留、本地模式禁用、生成期间按钮禁用。
- 模型为模拟接口，没有发起真实网络请求；供应商效果仍需真实配置验收。原有停止等待连接释放的限制仍适用。

## 0.10 背景移除（2026-10-26）

- 用户确认已接入真实模型；此反馈不等于鉴权失败、超时等异常场景已经验收。
- 全量 unittest：57项通过；compileall通过。
- 新增测试：边缘连通删除、内部同色保留、半透明主体保留、容差边界、透明边界、角落估色、无效输入与取消。
- 离屏集成：参数变更使预览失效、全透明拒绝应用、取消等待线程、预览取消无变更、保存失败删除新结果并保持当前形象、应用后重开恢复与还原原图。
- 合成小熊测试图已渲染对照预览，背景透明与主体保留符合预期。受限环境Qt字体列表为空，截图无法显示文字，因此文字布局仍需真实桌面验收。
- 未测试复杂照片语义分割；该能力没有实现。真实照片去背景效果需要用户在预览中判断。

## 0.11 动作序列（2026-10-26）

- 全量unittest：61项通过；compileall通过。
- 新增验证：自然数字排序、数量/帧率边界、损坏帧回退、外部路径拒绝、导入失败清理。
- 离屏集成：待机循环、一次性点击动作回待机、暂停不触发事件、重启恢复、配置失败保持原动作且清理新文件、动作移除与恢复默认、提醒优先级及无待机时静态回退。
- 使用合成彩色帧与临时目录，无网络请求、不修改真实用户形象。实际桌面动作质量、帧率和到期提醒联动仍需实测。

## 0.12 单图基础动作（2026-10-26）

- 全量unittest：66项通过；compileall通过。
- 新增验证：三类16帧、透明边界、非零幅度变化、零幅度静止、输入图片不变、无效输入拒绝、PNG保存及重载、保存失败清理。
- 离屏集成：幅度更新、切换动作预览、取消停止预览计时器、取消无文件写入、配置失败回退、应用后重开并撤销、恢复之前自定义待机动作。
- `.artifacts/generated-motion.png`为合成小熊最大幅度逐帧检查图，透明背景与主体未裁切符合预期。字体受限问题仍存在，不能以此确认真实桌面文字布局。
- 没有调用模型或上传图片。此功能是整图变换，不是语义动作、Live2D或3D生成。

## 0.13 Windows打包准备（2026-10-27）

- 全量unittest：69项通过；compileall通过。
- 新增：模拟frozen模式的EXE启动命令、无launch.py正常构建命令、缺失EXE拒绝、版本入口、源码离屏自检且不创建用户目录、构建命令固定输出且不添加用户数据、缺失构建依赖时拒绝执行。
- 实际运行源码版 --smoke-test：Qt离屏、内存SQLite和动作生成通过。
- PyInstaller安装失败：网络WinError10013；提权审批服务返回404 model_not_found，安装没有执行成功。
- 实际构建命令确认缺失依赖时明确失败，未生成EXE、ZIP或打包许可证清单。打包后的插件与启动尚未验证。

## 0.14 UI升级（2026-10-27）

- 全量unittest：69项通过；compileall通过。沿用现有聊天、草稿、请求隔离、待办、动作、去背景等回归，未为纯样式增加镜像测试。
- 实际离屏渲染三页、设置页下半部分、较窄窗口与宠物气泡。通过显式注册系统微软雅黑解决此前离屏环境字体列表为空的问题，已能检查中文文字和布局。
- 1000像素宽窗口的设置页horizontalScrollBar最大值为0；检查底部动作控件均可见。导航与页面选中同步。HTML样例按字面显示，未转换成外部图片。
- 预览截图位于.artifacts/ui-chat.png、ui-tasks.png、ui-settings.png、ui-settings-bottom.png及ui-pet.png；截图使用临时数据与示例内容，无真实用户记录或密钥。
- 真实Windows桌面高DPI与字体缩放仍需验收；打包仍受此前构建工具下载限制，不代表已生成新版EXE。

## 0.14 实际打包补充（2026-10-27）

PyInstaller 6.16.0现已安装。构建windows-0.14.0-20261027-100626-725051完成，实际EXE的Qt离屏、内存SQLite和动作生成自检通过，ZIP、许可证及manifest.json已生成。桌面重启时停止旧版PID9928被拒绝访问，提权审批服务404 model_not_found，未结束旧进程或启动新版。实际桌面与高DPI验收仍待完成。

## 0.15 控件升级（2026-10-27）

- 69项回归测试、compileall通过。
- 离屏实际交互：点击步进增减值、下拉框方向键选择、复选框空格切换，均通过；1000像素窗口设置页无横向溢出。
- 设置页与下拉弹层截图已检查，文件.artifacts/controls-settings.png和controls-popup.png。
- PyInstaller实际构建windows-0.15.0-20261027-101142-727930成功，EXE自检通过，ZIP、许可证及清单已生成。没有停止当前用户程序或自动切换版本。

## 0.16 Fluent实际验证

71项测试通过（Fluent模式），compileall通过；专项check_fluent验证通过。修复重载构造递归、方向键选择、设置卡片高度计算和Qt测试Application生命周期问题。实际0.16.0 EXE自检报告ui_backend=fluent，包含完整三页窗口构造及下拉数据映射，仍通过原Qt/SQLite/动作检查。设置页上下部、聊天及弹层截图已检查；1000像素无横向溢出。未自动结束旧程序或覆盖正式用户数据。

## 0.17 整体UI/UX（2026-10-27）

- 73项测试通过，编译检查通过。新增加字面HTML安全展示、系统反馈、清空、流式气泡原位更新及长连续字符串换行回归。
- 修复消息窗口销毁后延迟滚动回调访问已删除Qt对象；延迟回调改为随父对象销毁的QTimer。
- 渲染检查覆盖聊天/系统反馈、待办双行内容、设置上下半部、任务编辑、去背景、动作预览、到期提醒及桌宠。1000像素设置页无横向溢出。
- Fluent的默认ListWidget委托会截断本项目双行任务内容，因此保留原QListWidget并统一QSS，以确保日期和重复规则完整可见。消息采用独立头像组件与纯文本内容，不加载消息内的外部资源。
- 真实Windows高DPI及系统字体缩放、无Python环境机器的验收仍待完成。系统原生标题栏、文件选择器及部分标准消息框保留系统/Qt行为。

0.17最终构建：windows-0.17.0-20261027-112751-908676。PyInstaller完成，实际EXE完整Fluent窗口、Qt/SQLite/动作自检通过，ZIP和清单生成。应用数据未改动，未自动结束旧版。

0.17.1：重复选项默认none，明确重复直接填规则，仅说重复按daily解释；模型提示和本地模式同步。74项测试通过，覆盖默认一次、每天、每周、显式不重复及清理尾部控制词。


0.17.2：对话任务通过校验后直接保存，无需确认。75项测试通过，覆盖默认单次、重复任务、相同待办去重、非法时间不保存、流式取消不保存、会话切换时保存到期提醒和重启保留。旧草稿仅保留兼容入口，不自动提交。

## 0.31 P0 设计基座与外壳（2026-11-02）

- 100项测试通过（`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -q`），包含新增的 `test_shell_theme_and_responsive_layout`：1440 宽度侧栏 232px 且铭牌展开、900 宽度侧栏 68px 且铭牌折叠、导航待办计数随未完成数量更新、主题切换写入 `settings.json` 并在新窗口恢复。
- 新增 `ui/tokens.py`（纸白/夜幕两套 token）、`ui/icons.py`（内联 SVG 转 QIcon）、`ui/components.py`（NavButton、IconButton、LiveBadge）、`ui/pet_tag.py`（32px 斜切、⌀10 穿孔、展开 208×196、折叠 52×112）；`ui/theme.py` 改为 token 生成 QSS 与调色板，`ui/fluent.py` 支持明暗主题；`app.py` 外壳改为 232/68 响应式导航、38px winbar 与铭牌；`settings.py` 持久化 `theme`。
- 实测几何：1440 窗口侧栏 232px、铭牌 208×196；900 窗口侧栏 68px、铭牌 52×112、内容区 832×760；导航四项顺序与选中态正常，待办计数徽标与未完成数量一致。
- 铭牌“说句话”切到对话页，“歇会儿”调用既有 `pet.toggle_animation()` 并同步铭牌与 winbar 状态；主题切换后应用底、侧栏、winbar、通用控件即时变色，重启恢复。
- 截图证据：`.artifacts/p0-shots/p0-{1440,1180,900}-{light,dark}.png`，以及 900 宽度四页截图 `p0-900-{home,chat,tasks,settings}-light.png`；生成脚本 `.artifacts/capture_p0_shell.py`。
- 阶段边界：四页内部仍保留 0.30 内联暖色样式，夜幕主题下页面卡片与部分文字未随主题切换，P2–P5 逐页替换；本轮未验证真实 Windows 高DPI/多显示器与 3D 桌宠联动。本轮记录时尚未提交或推送；对应改动已随 P4 收尾统一提交。
- 收尾复验：补上“主题切换时品牌 logo 同步重绘”后重跑编译与全量测试（100 项通过），并重新生成 12 张截图，结果与上表一致；临时数据目录已清理，仅保留 `p0-shots` 与采集脚本。

## 0.31 P1 数据层与后端能力（2026-11-02）

- 108 项测试通过（同一离屏命令）。新增 `test_v6_upgrade_backs_up_and_adds_v7_columns`、`test_stats_completion_and_cross_midnight`、`test_quiet_hours_wrap_midnight_and_validation`、`test_early_nudge_mute_and_next_day`、`test_export_redacts_and_clear_keeps_restorable_backup`、`test_connection_test_reports_status_without_secrets`，以及界面层的 `test_quiet_hours_suppress_then_auto_postpone`、`test_early_nudge_and_mute_today`；既有 v1/v2/v3 迁移测试的期望版本同步改为 7。
- 迁移：`PRAGMA user_version=7`；v1–v6 打开时先生成 `.v{version}-*.bak` 再迁移。v6 专测确认旧任务保留，新增 `completed_at/source/note/muted_until/early_notified_at` 为 NULL 或默认值，`task_events` 表创建，`drafts.note` 为空字符串。
- 时间口径：`completed_at`、事件 `at`、`notified_at`、`early_notified_at` 统一按 UTC 存储；`today_stats()` 用调用方时区计算本地日半开区间，跨夜用例以 +08 时区验证 23:50 完成与次日 00:05 完成分别计入两天，按时完成率分别为 100% 与 0%。DST 由带 tzinfo 的日期边界承载；Windows 固定偏移时区不做跨 DST 的额外模拟。
- 免打扰：`in_quiet_hours()` 支持跨夜与起止相同（视为关闭）。界面测试把免打扰窗口设在当前时刻前后各 1 小时，`check_due()` 不创建提醒窗口，同一任务同一天只写 1 条 `quiet` 事件；关闭免打扰并开启自动顺延后，关闭提醒卡会把 `due_at` 后移 10 分钟、清空 `notified_at` 并写 `auto_postponed` 事件。
- 提前提点与今天别再说：到期前 10 分钟内的任务写 1 条 `early` 事件并只通过桌宠气泡提示；`mute_today()` 记本地日期，`due()/early_due()` 当日过滤、次日恢复，核心测试覆盖。
- 导出与清空：导出的 JSON 仅含 tasks/task_events/sessions/messages/drafts，测试断言不含 api_key、secret、webhook、authorization、dpapi 字样；`clear_data()` 先备份再在单事务内清空，测试用备份文件重新读取确认任务与消息仍可恢复。
- 连接测试：`test_connection()` 超时 8 秒、`max_tokens=1`；模拟 HTTP 401 时只返回“连接失败：HTTP 401…”，断言 API Key 未出现在错误文本中；成功路径返回整数毫秒耗时。
- 默认值与持久化：`early_nudge=True`、`auto_postpone=False`、`dnd_enabled=True`、`dnd_start=22:30`、`dnd_end=07:30`、`density=comfortable`；主题切换触发写盘后实测上述键与自定义 `density=compact` 均在新窗口恢复。
- 阶段边界：设置页的免打扰/提前提点/自动顺延开关、密度切换、测试连接、导出/清空入口及清空二次确认在 P5 落地；P1 只保证配置键、行为与后端 API 可用。0.30 遗留的已完成任务没有 `completed_at`，统计暂不回溯，P3 展示完成时刻时按“无记录”处理。本轮记录时尚未提交或推送；对应改动已随 P4 收尾统一提交。

## 0.31 P2 首页（2026-11-02）

- 108 项测试通过（`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -q`）。重写 `test_home_overview_and_navigation`，断言：初始空态主卡为空、节奏环 0/0、无安排行、两个空态面板可见、首页仅 1 个 `PrimaryPushButton` 且为“新增待办”；加入今日逾期与更早逾期后主卡选更早任务、正文含“另有 1 件逾期”、行高 58、节奏环 `(done,total)=(0,1)`；密度改为 `compact` 后行高 44；`Enter` 跳转待办页并选中任务；新增 chat 来源任务并完成今日任务后日志卡片出现、空态隐藏、`done==1` 且 `total==len(home_row_widgets)`；删除更早逾期后主卡切到“下一次”；1440 节奏卡在 `(0,1)`、900 在 `(1,0)` 且横向滚动最大值为 0；`toggle_theme()` 后 `tokens().name=='dark'` 且 `home_date` 样式含暗色 token 颜色。
- 修复清单：`due_when()` 接受 `datetime`（此前只接受字符串）；主卡从空态切回任务态时补 `count_widget.show()`；时间块 `ElidedLabel` 设 `QSizePolicy.Preferred` 避免被压成“今天 ...”；居中容器改为单权重 `addWidget(content, 100)`，修复内容只占约 1/3 宽；页内标签改为内联 `font-family/font-size/weight` 并记录 token 名，解决全局 QSS `QLabel{font-size:13px}` 覆盖字号与主题切换不重着色；主卡逾期且 `remind_count==0` 时显示“待处理”，不再显示“已提醒 0 次”。
- 截图证据：`.artifacts/p2-shots/p2-{1440,1180,900}-{light,dark}.png`，生成脚本 `.artifacts/capture_p2_home.py`（临时数据目录，含今日完成、逾期、下一次与免打扰事件）。逐张检查：1440/1180 主卡与节奏卡两栏、900 单列；1440/1180 工作日志三列/单列；三档宽度横向滚动条最大值均为 0；暗色下卡片、状态轨、状态胶囊与文字对比正常；主卡标题、原定时间与状态文案无截断。
- 阶段边界：仅首页替换为 token 内联样式，对话助手、待办事项、偏好设置仍为 0.30 暖色样式，暗色下局部偏亮，由 P3–P5 逐页替换；首页为只读汇总，跳转待办复用既有 `focus_task`；未在真实 Windows 高 DPI/多显示器下验收。本轮记录时尚未提交或推送；对应改动已随 P4 收尾统一提交。

## 0.31 P3 待办事项（2026-11-02）

- 109 项测试通过（同一离屏命令）。新增 `test_tasks_page_groups_bulk_density_and_theme`，断言：未完成视图 3 行且逾期排在今天之前、计数 `3 项未完成`、逾期胶囊文案与 3px 警示轨、已完成视图单行且 `strikeOut` 与 `已完成` 胶囊、时间下拉在已完成视图禁用；紧凑 44 / 宽松 58 且 `settings.json` 落盘 `density=compact`；搜索与时间范围过滤行数；双击调用编辑入口、行内完成环不调用编辑且完成数递增；批量条在选中后可见、`604×42`、`x=(page.width-604)//2`、`y=page.height-62`，取消后隐藏且选择清空；批量完成两项后未完成 0、已完成 4；已完成视图全选删除后 `deleted_batch` 4 项、撤销按钮可见，撤销后 4 项仍为 `done`；1180/900 宽度横向滚动最大值为 0；切换夜幕后行标题颜色取 `tokens().ink_3`。
- 复用既有 `task_refresh_timer`（30 秒）刷新待办与逾期时长，未新增计时器；提醒轮询、钉钉发送、草稿确认、软删除撤销与会话隔离保持原行为。
- 修复清单：`qfluentwidgets` 的 `LineEdit.addAction()` 只接受 `QAction`，搜索图标改为持有单个 `QAction` 并在主题切换时 `setIcon()`，避免重复图标；`_Ring` 的 `set_toolTip` 笔误改为 `setToolTip`；空态爪印底从 13px 圆角改为 20px 正圆；`set_task_density()` 同步分段控件当前项，避免程序化切换后文案落后于行高；聊天删除改用 `register_deleted()`，批量撤销按钮与 `last_deleted` 行为统一；刷新列表时先 `hide()` 旧分组再 `deleteLater()`，消除重建瞬间旧行残影（900 宽度批量条截图复核发现）。
- 截图证据：`.artifacts/p3-shots/p3-{1440,1180,900}-{light,dark}.png`、`p3-bulk-{light,dark}.png`、`p3-bulk-900.png`、`p3-done-{light,dark}.png`、`p3-compact.png`、`p3-empty-{light,dark}.png`，生成脚本 `.artifacts/capture_p3_tasks.py`。逐张检查：三档宽度横向滚动最大值均为 0；批量条 1440 与 900 均为 `604×42`，中心偏差 0，距底 20；紧凑档行高 44 且分段控件选中“紧凑”；已完成行虚线 + 删除线 + 苔绿；空态为苔绿圆底爪印且批量条不出现；暗色下搜索框、行卡片、状态胶囊与批量条反相显示正常。
- 阶段边界：完成项放在“已完成”筛选内单独分组，不与未完成混排；延期任务沿用 `已延期`，不显示实时逾期时长；30 秒整表重建会重置行焦点，交互期间无感；未在真实 Windows 高 DPI/多显示器下验收。旧实现以 `_LEGACY_TASKS_030` 注释块保留在 `ui/tasks.py` 末尾。本轮记录时尚未提交或推送；对应改动已随 P4 收尾统一提交。

## 0.31 P4 对话助手（2026-11-02）

- 113 项测试通过（同一离屏命令）。新增 `tests/test_chat_rail.py` 4 项：1440 右栏宽 296 且右栏开关隐藏、1180 收起且可展开/再收起、回到 1440 恢复常驻；草稿卡“直接创建”后任务入库且草稿清空、草稿区隐藏，“先放着”后任务仍为空、草稿删除；“今天别再说”写入 `muted_until=本地日期`、线程出现“今天不再提醒”；`AssistantWorker` 对 `RuntimeError('SECRET raw provider body')` 只发“请求失败，请检查模型设置后重试。”。既有聊天/流式/UI/规划/重答/自动任务 35 项同时通过，覆盖停止丢弃、跨会话隔离、重试不重复用户消息。
- 几何实测（离屏截图脚本输出）：1440 纸白/夜幕右栏 296、线程横向滚动 0、输入卡 720、草稿卡 720、右栏开关隐藏、侧栏 232；1180 纸白/夜幕右栏收起、开关可见、输入/草稿 720；900 纸白/夜幕紧凑档隐藏 Ctrl+Enter 提示、输入/草稿仍 720；1180 展开右栏 296、输入/草稿 720；900 展开右栏后输入/草稿收缩为 496。所有档位 `thread-scroll-x=0`。
- 修复清单：① `ComposerCard.paintEvent` 用 `self.rect().adjusted(0.5,...)`（QRect 传浮点）触发原生 abort 且无 Python 堆栈，改为 `QRectF(self.rect()).adjusted()`；② `QHBoxLayout` 双侧 stretch + 中间 `stretch=1` 把可用空间三等分，输入卡只剩 404、草稿卡 282，新增 `CenteredHost` 动态 `setFixedWidth(min(720, host_width))`；③ 输入框上限 120 让空输入卡高达约 216px，收紧为 64，贴合设计稿 rows=2；④ `FluentIcon.SYNC` 在透明按钮上渲染成竖线，改用 `icons.py` 自绘 `sync` 图标 + `IconButton`，并为中心偏移与禁用色补处理。
- 截图证据：`.artifacts/p4-shots/p4-{1440,1180,900}-{light,dark}.png`、`p4-1180-expanded-light.png`、`p4-900-expanded-light.png`、`p4-streaming.png`、`p4-error.png`，生成脚本 `.artifacts/capture_p4_chat.py`。逐张检查：两栏/单栏切换正确，右键展开后线程与输入同步收缩；输入卡与草稿卡同宽 720 居中；草稿卡五段信息与三按钮完整；右栏“今天安排”整行可点、逾期胶囊可见；暗色下气泡、输入卡、草稿头与右栏文字对比正常；流式特写为单条占位气泡，错误特写含脱敏原因与“重试/用本地规则记下”。
- 阶段边界：任务表没有 `session_id`，右栏“这段对话落到了什么”取全局最新 `chat/draft` 任务，不宣称按会话归属；模型返回的 `tasks` 仍自动入库以保持既有行为，草稿卡只对 `add_draft()` 生成的草稿确认入库；真实 Windows 高 DPI/多显示器与 3D 桌宠联动未验收。旧聊天组件以 `_LEGACY_CHAT_WIDGETS_030`、旧草稿卡以 `_LEGACY_DRAFT_CARD_030` 注释块保留。本轮记录时尚未提交或推送；对应改动已随 P4 收尾统一提交。

## 0.31 P5 偏好设置（2026-11-02）

- 119 项测试通过（同一离屏命令）。新增 `tests/test_settings_page.py` 6 项，断言：六张卡标题按“模型与对话 / 提醒与免打扰 / 外观与密度 / 数据与隐私 / 宠物形象 / 钉钉群通知”排列且每组结论非空；1440/1180 的 `PrefRow` 均非折叠、900 全部折叠，三档 `settings_content` 宽 760、页边距 32/20/20、横向滚动最大值 0；切换主题/密度、勾选提前提点/提示音/自动顺延、关闭免打扰与改开始时间后 `settings.json` 即时更新且状态胶囊变为“已关闭”；“恢复默认”后 theme=light、density=comfortable、early_nudge/sound_enabled=True、auto_postpone=False、dnd_enabled=True、22:30–07:30，同时 API Key、钉钉 Webhook 与输入框内容保持不变；连接测试成功显示“连接成功”与毫秒数、失败只显示 `ValueError` 文案、空字段不发起请求，状态文本不含 Key；导出文件含任务且不含 `api_key`/`secret`、`openUrl` 指向数据目录、清空需两次确认并生成 `.backup-*.bak` 且设置保留；Key/Webhook/Secret 均为密码模式且 `settings.json` 不含明文 Key。
- 布局实测（离屏截图脚本输出）：1440 内容 760 / 单行 `158+1fr` / pad 32 / 横向滚动 0 / 纵向最大 1432；1180 内容 760 / 单行 / pad 20 / 横向滚动 0 / 纵向最大 1432；900 内容 760 / 全部折叠单列 / pad 20 / 横向滚动 0 / 纵向最大 1848。三档侧栏分别为 232/68/68，属于既有外壳断点行为。
- 截图证据：`.artifacts/p5-shots/p5-{1440,1180,900}-{light,dark}.png`、`p5-1440-{light,dark}-bottom.png`，生成脚本 `.artifacts/capture_p5_settings.py`（临时数据目录与示例端点，无真实密钥）。逐张检查：1440/1180 左标题右控件、900 标题与控件上下排列；六张卡均有图标、标题与一行结论；按钮行左对齐，宠物图库左对齐且选中项品牌色描边；底部“数据与隐私 / 宠物形象 / 钉钉群通知”不裁切；暗色下卡片、分隔线、输入框、胶囊与文字对比正常。
- 修复清单：① 设置页在隐藏 tab 中几何不刷新，宽度断言前先 `setCurrentIndex(3)`；② `_pref_actions` 的按钮行被 `QHBoxLayout` 均分剩余空间而居中，改为在按钮添加完成后追加 `addStretch(1)`；③ 宠物图库单列时网格列均分导致图块居中，重置列 stretch 并在末列加弹性列，使图块靠左；④ 构建期 `self.pet` 尚未创建，直接绑定 `pet.reset_position` 会崩溃，新增 `reset_pet_position()` 并以 `hasattr` 保护。
- 阶段边界：P6 的待办编辑、提醒卡、今日规划与去背景预览在本轮仍使用 0.30 暖色内联样式，暗色下局部偏亮（已由 P6 替换）；“恢复默认”只覆盖主题、密度、提醒开关与免打扰时段，不含数据与凭证；开机启动受 `StartupManager.supported` 限制；真实 Windows 高 DPI/多显示器未验收。旧 Fluent 设置页以 `_LEGACY_SETTINGS_030` 注释块保留在 `ui/settings.py` 末尾。

## 0.31 P6 弹窗与收尾（2026-11-02）

- 125 项测试通过（`QT_QPA_PLATFORM=offscreen PYTHONPATH=tests .venv/Scripts/python.exe -m unittest discover -s tests -q`）。新增 `tests/test_dialogs.py` 6 项：待办弹窗保留标题/时间/重复/钉钉字段且标题、说明对象名存在；规划弹窗回显完整快照、模型/本地两种主按钮文案；最终提醒 `snooze_button` 禁用、tooltip 含“不再重复提醒”、提示含“延期”，点击完成回调生效；普通提醒仍可延后；模拟 1920 起始的副屏可用区，提醒卡移动到副屏并夹紧在可用区内；离屏 `ImagePreview` 在纸白/夜幕下分别取 `surface` token，去背景弹窗最小尺寸不超过实际尺寸。
- 屏幕夹紧实测（离屏单屏 800×600）：提醒卡 1×、1.25×、1.5× 下 `frameGeometry` 均完全位于可用区，分别为 `(367,297,420,276)`、`(207,177,420,276)`、`(100,107,420,266)`；副屏用例覆盖 `screenAt(anchor)` 返回第二屏时的坐标偏移。
- DPI 几何（100/125/150%，纸白与夜幕各一组）：待办 `520×441`（最小 329×396）、规划 `650×540`（最小 208×301）、去背景 `700×510`（最小 420×472）、提醒 `420×276`（1.5× 为 `420×266`，最小 319×261）；四类弹窗所有可见标签与按钮边界均在弹窗矩形内，`clipped=none`。
- 透明边缘：提醒卡窗口 `WA_TranslucentBackground` + 20px 内缩；截图角点 alpha=0，卡片圆角 18–21px 处 alpha 为 1–3（抗锯齿），无实色外框或白边。离屏环境不渲染真实桌面壁纸；浅/深壁纸对比依赖卡片 `surface` 与 `border` token，深色卡片在夜幕下使用 `#1F2124`。
- 明暗与焦点：待办、规划、去背景弹窗的标题/说明/字段/提示卡由 QSS 对象名分主题着色；提醒卡标题、提示、关闭/打开按钮同样走 QSS，主题切换后即时变色。输入框聚焦显示品牌色下划线；`QPushButton` 保持 Fluent 焦点样式；`QToolButton#reminderClose/#reminderLink` 与 `QSlider` 有 1px 品牌色焦点边框。
- 截图证据：`.artifacts/p6-shots/p6-{task,plan,cutout,reminder}-{light,dark}-{1,1.25,1.5}x.png` 共 24 张，生成脚本 `.artifacts/capture_p6_dialogs.py`（临时数据目录、合成图片与示例端点，无真实密钥）。逐张检查：眉标/标题/说明层级正确；待办时间与重复双列不截断；规划预览与底部说明不裁切；去背景双预览棋盘随主题变色、按钮右对齐；提醒卡最终提醒胶囊、逾期胶囊与“10 分钟后”禁用态清晰；暗色下卡片、提示卡、按钮与文字对比正常。
- 修复清单：① 提醒卡主体、关闭与“打开待办”原本为固定 0.30 暖色内联样式，改用 `reminderCard`/`reminderClose`/`reminderLink` QSS 对象名，关闭与打开改用 `QToolButton` 规避 Fluent 按钮样式覆盖；② `TaskDialog` 固定 470 高导致底部留白偏多，收为 `sizeHint` 高度 441；③ `ImagePreview` 棋盘原为 `#dddddd/#ffffff` 硬编码，改为绘制时读取 token 并加 12px 圆角与描边；④ 提醒卡“打开待办”去掉旧 `QPushButton` 透明样式，焦点边框由 `QToolButton#reminderLink:focus` 统一提供。
- 收尾：`docs/UI_DESIGN_SYSTEM.md` 的 P6 复选框、阶段表与进度行已置为完成；`docs/IMPLEMENTATION.md` 与 `docs/DESIGN.md` 增加本阶段说明。四页与弹窗在同一主题下使用同一 token 源，P0–P6 视觉重构收口。

## 0.31 P6 后续：对话页可读性与全宽（2026-11-02）

- 127 项测试通过（`QT_QPA_PLATFORM=offscreen PYTHONPATH=tests .venv/Scripts/python.exe -m unittest discover -s tests -q`）。新增覆盖：带换行的系统回执 `display_text()` 不含换行；900 宽线程下用户气泡 <200px 且助手气泡 >700px；首页刷新后旧行在 `deleteLater()` 前已隐藏。
- 宽度实测（离屏 `QTest`，gutter=20，视口 900）：线程行宽 836；用户“今日金价查询”气泡 113px、“18.08分，提醒我喝水”161px；助手回复气泡铺满 782px；系统回执压平后单行显示。
- 主窗口实测：1180×820 收起右栏时输入卡 1072、线程 1112；1440×820 右栏常驻时输入卡 848、线程 912，均与 `apply_chat_layout()` 的页边距一致，无 720 居中留白。
- 闪烁修复：首页安排行与工作日志卡在移除时先 `hide()` 再 `deleteLater()`；`set_theme()` 用 `setUpdatesEnabled(False/True)` 合并整套 token 重建的绘制；设置页宠物图库同样先隐藏。
- 截图证据：`.artifacts/chat-fix-{light,dark}-{1180,1440}.png`，生成脚本 `.artifacts/chat_fix_shots.py`（临时数据目录）。逐张检查：线程与输入卡同宽铺满；助手气泡全宽、用户气泡贴合文字；系统回执为中性灰底深色文字，单行不叠字；暗色下回执、气泡、输入卡与右栏对比正常。
- 历史说明：P4 的 720 居中线程/输入列与 `CenteredHost` 已由本轮全宽方案取代，P4 记录仅作回退参考。

## 0.31 P6 后续：闪烁修复（2026-11-03）

- 128 项测试通过（`QT_QPA_PLATFORM=offscreen PYTHONPATH=tests;. .venv/Scripts/python.exe -m unittest discover -s tests -q`）。新增 `test_refresh_skips_rebuild_and_theme_restyles_in_place`：数据不变时连续 `refresh_home()` / `refresh_tasks()` 不替换行对象；`toggle_theme()` 后首页行与待办行仍是同一对象，首页行标题颜色切到 `tokens().ink`。
- 重绘探针（真实窗口，`.artifacts/flicker_probe.py`，统计主窗口及其子控件的 `QEvent.Paint`）：切回首页 49 次绘制集中在 1 帧（15ms）；聊天→首页 1 帧；密度紧凑/宽松各 1 帧（31ms）；主题切亮 1 帧，切暗 1–2 批绘制但两批都是原地重样式完成后的同一最终画面。
- 离屏截图（`.artifacts/flicker-{home,tasks}-{light,dark}.png`，脚本 `.artifacts/flicker_shots.py`，临时数据目录含逾期/今天/已完成/未来/对话来源任务）：主题切换后首页主卡、节奏卡、4 条安排、2 张日志卡及待办页分组、筛选、密度分段、行内胶囊均完整显示，无空白页或残留旧色。
- 关键修复：① 冻结嵌套时子控件 `updatesEnabled()` 跟随父窗口为 `False`，解冻必须显式恢复，否则首页在首次切主题后永久不刷新；② 首页/待办用数据签名跳过无变化重建；③ 主题切换改为原地重样式；④ `apply_theme()` 不再每次重建 `Fusion` 样式与字体。
- 历史说明：上一轮“旧控件先 `hide()` 再 `deleteLater()`”与 `set_theme()` 窗口冻结仍然有效，本轮在其上补充签名跳过与原地重样式；旧方案不删除。

## 0.31 P6 后续：缩放与侧栏（2026-11-03）

- 129 项测试通过（`QT_QPA_PLATFORM=offscreen PYTHONPATH=tests;. .venv/Scripts/python.exe -m unittest discover -s tests -q`）。新增 `test_sidebar_toggle_and_resize_keep_widgets`：默认展开 232px，`toggle_sidebar()` 后 68px、品牌区折叠且写入 `settings.json`，再切回 232px；连续 resize 900→1500→1180 跨三个断点后首页行与宠物图库仍是同一批对象；920px 窄窗下侧栏保持用户手动展开状态。
- 缩放探针（真实窗口，`.artifacts/resize_probe.py`，900↔1500 往返 50 步）：扫动期间 `StatusRow`/`LogCard` 构造次数为 0，首页行对象与 `_pet_tiles` 图库对象保持 True；侧栏收起/展开绘制 138/172 次，重建 0。
- 离屏截图：`.artifacts/resize-sidebar-expanded.png`（232px）、`.artifacts/resize-sidebar-collapsed.png`（68px，铭牌折为竖排、版本号隐藏、主题按钮保留）、`.artifacts/resize-narrow-expanded.png`（920px 仍按用户选择展开）。三张均无空白页、导航选中态与待办计数正常。
- 历史说明：P0 的“≥1280 自动展开、<1280 自动收起”已由 winbar 手动开关取代，仅作历史；页面内容断点（1080/1280/1400）与页面内响应式布局保持不变。

## 0.31 P6 后续：发送/流式/完成待办闪烁（2026-11-03）

- 132 项测试通过（`PYTHONPATH="tests;." QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -q`，约 91s）。新增覆盖：`test_session_refresh_updates_in_place`（`add_message` 后右栏 `_rebuild` 调用 0 次、同一“消息”标签改为“1 条”，新增对话任务后重建 1 次）；`test_stream_append_matches_full_render`（同一历史区内增量行与整篇行最终文本相同、高度相等）；`test_render_stream_skips_unchanged_content`（相同正文第二次 `render_stream()` 不再刷新行）。
- 发送消息探针（真实窗口）：2 个绘制批次 / 72 次绘制，`ChatRail._rebuild` 调用 0 次，此前为整栏销毁重建。
- 流式探针（`.artifacts/stream_mode_probe.py`，真实窗口 1180×820，统计主窗口及子控件 `QEvent.Paint`）：old 口径总计 1025 次、非滚动条 880 次、整窗层 183 次（每帧约 34 次）；new 口径 1017 / 867 / 186（每帧约 33 次）。历史区每帧重绘面积约为视口的 12.7 倍，两口径接近——主导开销来自消息增长导致的内容整体重排；本轮消除的是文档整体重置、透明背景逐层上报与右栏重建，重排本身无法避免。
- 完成待办探针（`.artifacts/stream_probe.py`）：待办页 3 个批次（+16/+32/+63ms，46/47/14 次，每批整窗层仅 3 次小区域重绘）；首页 2 个批次（+31/+47ms，81/15 次）。此前同一变化会分多帧逐块闪现。
- 截图证据：`.artifacts/flicker-chat-light.png`、`.artifacts/flicker-chat-dark.png`（脚本 `.artifacts/flicker_shots.py`，临时数据目录）：流式结束后纸白/夜幕下气泡、正文、输入卡与右栏完整，无白带、无空白页。离屏环境不产生 `QEvent.Paint`，闪烁判断以真实窗口探针的批次与重绘次数为准。
- 历史说明：本轮试过在 `render_stream()` 中用 `frozen_updates(history.content)` 冻结历史区，真实窗口反而升到 1140 次/44 批次（冻结使整块 content 每帧重绘），已放弃；`append_plain()` 内同步 `_apply_height()` 同样让绘制回升（1278/67），一并撤销。两项仅作历史备查。

## 0.31 联网搜索：Tavily（2026-11-03）

- 147 项测试通过（`PYTHONPATH="tests;." QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -q`，约 99s），较上一轮新增 15 项。
- 客户端测试 `tests/test_websearch.py` 8 项：意图正例（“帮我查一下最新金价”“今天天气怎么样”）与反例（“明天15:00提醒我交报告”“帮我记个待办”“你好呀”）；请求头为 `Bearer`、body 含 `search_depth=basic/max_results=5/include_answer`、query 原样；结果清洗丢弃非 http(s) 与非 dict、标题回退 URL、正文截断 500 字、最多 5 条；60 秒缓存命中不再发请求；401/403、429、432–434、400 与超时分别映射中文文案；空结果不报错；取消与空 Key 抛 `WebSearchError`；`format_context` 含本地时间、编号来源与“不得改变”限制；`ask()` 仅在传入 `search_context` 时把资料追加到 system prompt。
- 界面测试 `tests/test_websearch_ui.py` 3 项：真实问题触发检索并在助手行显示来源条（`https://example.com/gold` 可见、正文正常）；任务措辞不触发检索且不注入上下文；无 Key 时开关禁用并取消勾选，手动关闭写入 `settings.json`。
- 其余新增：`tests/test_windows_settings.py` 的 `test_tavily_secret_roundtrip`（DPAPI 保存/读取/删除）；`tests/test_chat_widgets.py` 的 `test_sources_only_keep_web_links_and_follow_theme`（过滤非 http(s)、最多 5 条、链接色随主题）；`tests/test_settings_page.py` 新增卡标题断言与 `test_tavily_key_is_encrypted_and_toggle_persisted`（掩码、`settings.json` 不含明文、开关落盘）。
- 截图证据：`.artifacts/websearch-shots/websearch-settings-{1440,900}-{light,dark}.png`、`websearch-chat-1180-{light,dark}.png`，生成脚本 `.artifacts/websearch_shots.py`（临时数据目录与示例端点，无真实 Key）。逐张检查：设置页“联网搜索”卡在 1440/900 与纸白/夜幕下布局正常；聊天页联网开关为激活态、来源条显示两条链接、助手正文内联链接在夜幕下为橙色（`#ee8454`），无蓝链残留。
- 真实调用边界：本轮未使用真实 Tavily Key 发请求，联网结果质量、配额与 RPM 未实测；代码路径以 mock 的 HTTP 响应与错误码覆盖，真实调用需在“偏好设置 → 联网搜索”填写 Key 后点“测试连接”验证。
- 历史说明：暗色 Markdown 链接最初固定为蓝色，`palette` 与 document default stylesheet 对 `setMarkdown` 无效；最终在 `MessageText.setMarkdown()` 后逐字符 `mergeCharFormat` 重着色，来源条同步改用 `brand_hover`。

## 0.31 实时性修复与本地知识库（2026-11-04）

- 163 项测试通过（`PYTHONPATH="tests;." QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -q`，约 105s）。
- Tavily 时效：`tests/test_websearch.py` 11 项通过——行情类 `time_range=week`（“实时/现在/今天/多少钱”时为 `day`）、新闻类 `topic=news&days=3`、普通问题不带时效参数；`published_date` 保留并在 `format_context` 中显示“发布于”；任务措辞仍不触发检索。
- 知识库核心：`tests/test_knowledge.py` 11 项通过——utf-8/gb18030 文本、docx（含表格）、xlsx、txt 提取；不支持格式与空文本报中文错误；600/80 切块重叠；Wiki 与原文同时可检索；2 字短查询走双字扫描；同路径同内容跳过、`force=True` 重建、文件变化替换旧索引；Wiki 生成失败保留原文并记录错误；移除/清空清理文件与 Wiki 目录；注入上下文含“资料名称”和“不得改变”约束。
- 对话接入：`tests/test_knowledge_ui.py` 2 项通过——本地文档命中后 `ask` 收到含文档名与“600 元”的上下文，助手气泡下“资料：《差旅制度.txt》”可见；“一线城市住宿标准是多少”在关闭知识库后不注入上下文。
- 设置页：`tests/test_settings_page.py` 8 项通过——新增 `test_knowledge_toggle_import_list_and_clear`：开关即时写入 `settings.json`、无资料时对话开关禁用、后台导入 1 份 txt 后清单出现且状态含“新增 1”、清空后清单为空并再次禁用；卡片标题断言加入“本地知识库”；1440/1180/900 三档仍无横向滚动（知识库卡窄窗按可用宽度收缩）。
- 截图证据：`.artifacts/knowledge-shots/settings-knowledge-{1440,900}-{light,dark}.png`、`chat-knowledge-materials-{light,dark}.png`，生成脚本 `.artifacts/capture_knowledge.py`（临时数据目录，导入两份合成资料，示例端点，无真实密钥）。逐张检查：1440/900 资料卡在纸白/夜幕下标题、开关、清单与六个按钮完整，900 宽六按钮仍单行且横向滚动为 0；聊天页助手气泡下资料条与来源条同时存在时层级正常，暗色下资料条为 `ink_3`、正文对比正常。
- 真实 Wiki 边界：使用本机已配置的模型与 DPAPI 密钥做真实导入冒烟（合成《差旅报销简则》，不涉及用户资料），该端点当前对本机 Python 3.11 OpenSSL 返回 `SSL: UNEXPECTED_EOF_WHILE_READING`（curl 直连可建立 TLS），`test_connection` 同样报“20 秒内无法连接服务”，因此本轮未能取得真实 Wiki 文本；失败路径已验证会保留原文索引并记录 `wiki_error`。需在可连通的网络或更换端点后复测 Wiki 生成质量与耗时。

## web 模式提醒卡点击抖动修复（2026-11-10）

- 根因：`bridge_modules` 在任务变更后调用 `window.refresh_tasks()`；web 模式下该方法仍渲染隐藏的 Qt 待办页，并用 `frozen_updates(self)` 冻结整个主窗口。待办较多时冻结约 0.78s，期间 WebEngine 画面停住，解冻后整块重绘，表现为点击提醒卡后页面抖动。
- 修复：`TasksPageMixin.refresh_tasks()` 在 `web_shell` 挂载时直接返回，HTML 侧继续依赖 `tasks.changed` 自取数据；qt 模式行为不变。
- 证据：真实窗口探针 `.artifacts/reminder_jitter_probe.py`（980×640、8 条待办）显示点击后整窗 `setUpdatesEnabled(False)` 调用从 1 次降为 0，`refresh_tasks` 耗时约 770ms 降为 0ms；`aside/main` 坐标与滚动宽度全程不变，布局位移仅卡片移除带来的 CLS 0.009/0.017。
- 三个按钮逐一复测（同一探针，按卡片标题定位）：完成 → `status=done`；10 分钟后 → `status=pending`、`due_at` 为当前 +10 分钟、`notified_at=NULL`；今天别再说 → `status=pending`、`muted_until` 为当天本地日期。三者均无整窗冻结、`refresh_tasks` 均为 0ms、`aside/main` 坐标与滚动区稳定，点击后提醒卡都从 DOM 移除；仅完成时主列表任务行上移产生 0.017 的 CLS，顺延/免打扰的位移为 ≤0.00002/0。
- 二次复测（用户反馈顺延仍闪烁）：DOM 坐标稳定不代表不卡顿。用真实数据库副本、1180×820 的 `.artifacts/reminder_lag_probe.py` 测得点击时 Qt 主线程事件循环最长阻塞 102ms，其中 `refresh_home()` 重绘隐藏 Qt 首页独占 91ms，WebEngine 呈现随之停顿后跳帧。首轮修复只挡住了 `refresh_tasks()`，遗漏了同一路径上的 `refresh_home()`。
- 修复：`HomePageMixin.refresh_home()` 在 `web_shell` 挂载时同样直接返回；`refresh_pet_tag()` 仍由 bridge 单独调用（实测 1.6ms），不受影响。qt 模式行为不变。
- 证据：修复后同一探针 `refresh_tasks=0ms`、`refresh_home=0ms`、`refresh_pet_tag=1.6ms`，主线程最长延迟 102ms→22ms；点击附近渲染帧最大间隔 28ms（此前抓帧探针显示约 295ms，但抓帧本身会干扰渲染），数据库状态与按钮语义一致。注意：探针窗口使用临时数据目录（假待办），不是用户的数据实例。
- 回归：`tests/test_ui.py` + `tests/test_bridge_modules.py` 共 63 项通过（含 web 模式动作与任务桥）；Phase 2 web 提醒 18/18、Phase 3 聊天 24/24 通过；qt 模式 `test_ui.py` 15 项通过；全量 224 项测试通过，收尾无 closed database 报错。

## 宠物窗并入 web 工程（Phase 4，2026-11-10）

- 迁移：`desktop_pet/assets/pet3d/`（页面、three.js r147、GLTFLoader、husky/fox 模型与许可证）整体移到 `web/public/pet3d/`，由 vite 构建原样复制到 `web/dist/pet3d/`。3D 页面保持普通 script（不引入 npm three），`window.pet3d` 的 `setPaused/lookAt/react/setDragging/setWalking` 契约与 `pet.py` 调用未改。`ui/pet3d.py` 的 `scene_path()` 源码运行读 `web/public/pet3d`、冻结后读 `_MEIPASS/web/pet3d`、`DESKTOP_PET_WEB_DIST` 可覆盖；`tools/build_windows.py` 去掉 `desktop_pet/assets` 打包项并改查 `_internal/web/pet3d`。
- 决策：2D 帧动画与气泡保留 Qt（计划 4.2 取消、4.3 结论）。2D 动作帧是数据目录 `animations/` 下的 256×256 PNG（每动作最多 24 帧），迁 HTML 需额外提供本地图片服务/data URL、透明留白补偿与逐帧计时；气泡是 2D/3D 共用 QLabel，位于窗口顶部 0–88px 的 3D 画布之外，迁页面需要把 WebEngine 扩到全窗并分叉两套截断逻辑。
- 交互回归：`.artifacts/pet3d_phase4_check.py`（真实窗口 + 桩 owner，临时目录）18 项检查全部符合预期——页面 URL 指向 `web/public/pet3d/index.html` 且 `window.pet3d` 为对象；单击触发一次 `react` 并显示气泡“摸摸收到…”；拖动事件过滤器使窗口位移 40×30 且 `pet_position` 同步写入；双击转发 `show_main` 1 次；右键菜单 7 项完整；`setWalking(true,-1)`、`setPaused(true/false)` 均到达页面；巡逻 1.2 秒产生实际位移并可停止；切 2D 后 220×260 且动画定时器运行，切回 3D 后 220×340、视图可见。结果存 `.artifacts/pet3d-phase4-check.json`。
- 构建与冻结路径：`npm run build` 产物包含 `dist/pet3d/index.html` 与 three.js/GLTFLoader/husky.glb.js；用临时 `_MEIPASS` 验证冻结路径与三个资产存在。完整 PyInstaller 构建（`.artifacts/buildenv` 安装 PyInstaller 6.16.0，复用 pyenv 的 PySide6）通过自带 smoke-test，产物 `dist/windows-0.30.1-20261110-121945-894252`；用临时数据目录启动打包 exe，截图确认 3D 哈士奇与启动气泡均由 `_internal/web/pet3d` 渲染（`.artifacts/pet-packaged-3d.png`）。
- 回归：全量 224 项 Python 测试通过（`QT_QPA_PLATFORM=offscreen PYTHONPATH=tests python -m unittest discover -s tests`，381s）。
- 稳定性与常驻：打包实例（隔离数据目录）5 分钟取样，主进程工作集 262.3→212.9 MB、渲染子进程 80.7 MB 稳定，进程树约 343→299 MB，无退出或重载；源码版真实数据运行 30 分钟，进程树 487.0→442.2 MB（12:49 中段峰值 512.6 MB，属 WebEngine 分配回收波动），主进程 313.7→260.2 MB，两个渲染子进程 PID 自启动（12:33:26）未变，`Responding=True`，宠物窗持续正常渲染（`.artifacts/pet-live-source-p4.png`）。
- 未覆盖边界：打包版 30 分钟常驻、多屏 `ensureVisible` 与休眠唤醒需在目标机器补测；本轮为单屏 2560×1440@1x。

## Phase 5 收尾：删除 Qt 页面、web 成为唯一界面（2026-11-10）

- 代码：新增 `desktop_pet/shell.py`（`ShellMixin`：配置持久化、DPAPI 密钥恢复、宠物图片/去背景/动作清理、主题与位置），`app.py` 仅保留 `AssistantWorker`、任务操作、提醒调度、托盘与宠物窗；删除 `ui/{home,tasks,settings,chat_rail,chat_widgets,draft_card,reminder,pet_tag,components,controls,fluent,motion,common,icons}.py` 及 `tools/check_fluent.py`、`requirements-fluent.txt`、`launch-fluent.ps1`。桥模块同步移除 `refresh_*`/`register_deleted` 等 Qt 页面钩子，web 侧统一依赖 `tasks.changed` / `chat.changed` 事件重拉。
- 开关与依赖：`shell.persist_settings`、`settings.getAll` 白名单、`web/src/api.ts` 删除 `ui_shell` / `sidebar_collapsed`；`requirements.txt` 只保留 PySide6/pypdf/python-docx/openpyxl；`diagnostics` 改为 `ui_backend: web` 的 5 项自检（qt-offscreen、sqlite、pet-image、pet3d-assets、web-bundle），不再创建 MainWindow。
- 测试适配：删除 9 个 Qt 界面专项测试；`tests/qt_support.py` 注入无头 `WebShell` 桩（真实 QtWebEngine 在 offscreen 退出时会崩溃），桥/壳/宠物/任务行为仍走生产代码。`test_auto_tasks` 改为 `decode_response` + `run_task_ops`；重新生成的两条路由保证（结果写回分支、重试不重复提问）并入 `test_bridge_modules`。全量 `169` 项通过。
- web 构建：`npm --prefix web run build` 通过，`web/dist/index.html` 1,050.77 kB（gzip 226.68 kB）。
- 真实 WebEngine 检查：设置页 9 卡 / 30 按钮 / 17 输入 / 9 开关、控制台零报错；Phase 2 首页/任务页/提醒/表单 全过；Phase 3 流式、停止、重试、重新生成、多义序号、规划快照、草稿 全过，控制台零报错。
- 打包回归：`.artifacts/buildenv`（PyInstaller 6.16.0）构建 `dist/windows-0.30.1-20261110-133335-429837`，自带 smoke-test 通过；打包 exe 用隔离数据目录启动，主窗 1,098ms 出现并渲染首页（`.artifacts` 外 `build/packaged-check/web-mode.png`）。首次冷启动截图停在“正在连接桥…”，第二次即正常，判断为首次加载 WebEngine 缓存/杀软扫描的冷启动延迟，未复现为桥故障。
- 未覆盖：Win10、125%/150% DPI、双屏、休眠唤醒、静默启动与真实单实例锁需在目标机器验证；本机为 Win11 单屏 2560×1440@1x。数据升级（v1/v2/v6→v7）与密钥/知识库迁移由 `tests/test_core.py`、`tests/test_windows_settings.py`、`tests/test_bridge_modules.py` 覆盖。

## 提醒卡回到宠物头顶 + 对话页无滚动条 + 侧栏手动收起（2026-11-10）

- 提醒位置：新增 `desktop_pet/ui/reminder_popup.py`（无边框、置顶、`WA_ShowWithoutActivating`、304px 卡宽 + 14px 阴影余量）。`show_at_pet()` 以宠物窗 `frameGeometry` 为锚，卡片底边贴 `BUBBLE_BOTTOM(84)` 上方，横向与宠物中心对齐并夹紧在屏幕可用区内；宠物贴屏幕顶时翻到下方。120ms 跟随定时器让卡片随宠物拖动移动，多张卡按 `slot` 纵向堆叠（间距 6px）。删除 `web/src/components/ReminderStack.tsx` 与 `styles.css` 的 `/* reminders */` 整段，主窗不再渲染提醒卡。
- 行为不变项：`REMIND_LIMIT=3` 的 deferred、静默时段、重复任务 next_id 链仍留 `check_due_web`；四按钮走壳侧 `resolve_reminder`（完成 / 10 分钟后 / 今天别再说 / 打开待办）。「打开待办 →」调 `show_main()` 并发 `ui.navigate {page:'tasks'}`，React 侧用 `onNavigate` 切页。托盘 notify 改为仅在宠物隐藏时触发，避免与头顶卡片重复。
- 对话页：`.content-chat` 设 `overflow:hidden`，自身与子元素 `scrollbar-width:none` 且 `::-webkit-scrollbar { width:0; height:0 }`，`.chat-page` 改为 `flex:1; min-height:0` 填满内容区，滚轮滚动不受影响。
- 侧栏：底部新增 `panel` 图标按钮，切换 `.shell.rail-collapsed`（`--rail-w` 232px↔68px），状态写入 `localStorage['pet.railCollapsed']`，初始值在无存储时按 `innerWidth < 1280` 判断。原 `@media (max-width:1279px)` 自动收缩块已移除，改为纯手动；折叠态隐藏文字、居中图标、宠物卡缩为头像列。
- 证据：`tools/webshell_phase2_check.py` 23/23（新增卡片存在/位于宠物上方/三按钮/完成/顺延/免打扰/关闭自动顺延/重复任务/「打开待办」跳页、侧栏折叠宽度 68↔232 两段断言），`tools/webshell_phase3_check.py` 25/25（新增对话页无滚动条且填满断言），设置页检查通过，全量 169 项单测通过，`npm run build` 341.66 kB 通过。真实窗口截图（临时脚本，已清理）确认：1320px 宽对话页无可见滚动条、侧栏收起为 68px、提醒卡位于宠物头顶且无重复 Windows toast。
- 未覆盖：多屏跨屏拖动时的卡片跟随、125%/150% DPI 下的卡片夹紧需在目标机器补测；当前运行中的实例为旧构建，需重启后生效。

## 主窗长时间隐藏后白屏修复（2026-11-10）

- 复现：主窗关闭（隐藏到托盘）→ 结束主进程下的 `QtWebEngineProcess.exe` 渲染进程（模拟 Chromium 长时间隐藏后回收渲染器 / 休眠唤醒丢失）→ 双击宠物打开主窗，`main` 可见但 WebEngine 区域纯白；此前没有任何恢复逻辑，只能重启应用。
- 修复：`desktop_pet/ui/webshell.py` 记录 `render_lost` 并连接 `renderProcessTerminated`；主窗重新显示时 `ensure_alive()` 先用 `document.readyState + #root 子节点数` 做存活探测（1.5s 无回调或返回异常即判定渲染器失效），失效则 `reload()`。`MainWindow.showEvent` 与 `show_main()` 都会调用，覆盖托盘双击、任务栏、宠物双击与提醒卡「打开待办」各条路径；连续失败时重载间隔按 300ms→5s 退避，加载成功复位；`QApplication.closingDown()` 时不再重载。
- 验证（真实 WebEngine 窗口，源码实例）：① 隐藏后杀掉两个渲染进程，双击宠物重开——窗口恢复，新渲染进程启动，CDP 读到 `readyState=complete`、`.shell` 与 `aside nav` 存在，正文为首页内容（非「正在连接桌面桥…」），即桥在重载后重新握手；② 窗口可见时杀掉渲染进程——约 300ms 后自动重载恢复，正文时间戳随重载更新；③ 回归：全量 169 项单测、Phase 2 23/23、Phase 3 25/25、设置页检查全部通过，控制台无报错。
- 说明：重载会丢失未提交的输入框草稿与滚动位置，只在渲染器确实失效时触发；页面正常显示时不重载。GPU 上下文丢失但渲染器仍响应的情况未单独覆盖，若目标机器仍出现白屏可再补强制重绘。

## 后台启动首帧白屏修复（2026-11-11）

- 复现：用户双击宠物打开主窗仍白屏。`desktop_pet/startup.py:38` 的自动启动带 `--background`，`app.py` 因此不调用 `window.show()`；页面在从未显示过的窗口里加载完成，合成器没有绘制首帧。此时 DOM 完全健康（CDP 读到 `readyState=complete`、`#root` 有子节点），上一轮的存活探测必然通过，不会触发重载，于是首次显示只剩白底。
- 修复：`WebShell` 在 `loadFinished` 时记录 `_loaded_hidden = not self.isVisible()`；`ensure_alive(hidden_seconds=0)` 在 `render_lost`、`_loaded_hidden` 或隐藏时长 ≥ `HIDDEN_RELOAD_SECONDS`(120s) 时直接 `reload()`，否则才做 JS 存活探测。`MainWindow` 新增 `hideEvent` 记录 `time.time()`，`showEvent` 取出隐藏时长并在 `singleShot(0)` 中传给 `_wake_shell`，`show_main()` 走同一入口；时长为一次性消费，避免 `showEvent` 与 `show_main` 重复处理。
- 验证（真实 WebEngine，源码实例，`DESKTOP_PET_DEV=1` + CDP）：① `python launch.py --background` 启动，主窗隐藏、页面已加载完成（`origin=1794363512253`、`#root=1`、标题“上午好”）；双击宠物头部后主窗可见，`performance.timeOrigin` 变为 `1794363596348`（确认重载），截图渲染完整首页；② 短时隐藏 2.5s 后双击宠物重开，`timeOrigin` 不变（未多余重载），页面保持原状态；③ 隐藏 125s 后重开（见下条验证），强制重载生效；④ 回归：全量 169 项单测、Phase 2 23/23、Phase 3 25/25、设置页检查通过。
- 说明：重载会回到首页并丢失滚动位置，仅在隐藏加载、隐藏 ≥120s 或渲染器失效时触发；120s 内的快速开合不重载。若目标机器上短时开合仍白屏，可把 `HIDDEN_RELOAD_SECONDS` 调小或改为每次显示都重载。


## 当前提交前的验证状态（2026-11-11）

当前代码版本号为 0.32.0。最新 Windows 发行构建及其 smoke-test 结果见下节；该 0.31.0 构建早于 0.32 UI 变更。此前 169 项 Python 测试、React/Vite 构建、设置/任务/聊天的真实 WebEngine 检查、打包 EXE 自检与隔离数据启动，均对应各自记录的 2026-11-10 回归，不能据此推断之后代码变更重新通过了测试。

Windows 10、125%/150% DPI、双屏/跨屏宠物、休眠恢复、干净机器首次启动和目标机上的登录启动/DPAPI 密钥恢复仍未完成验收；macOS 也未验证。提交工作区不代表以上平台或运行场景已验收。

## 0.31.0 Windows 发行构建（2026-11-11）

- 构建目录：`dist/windows-0.31.0-20261111-113751-946102/`；ZIP：`DesktopPet-0.31.0-windows.zip`（177.72 MiB）。
- 前端：TypeScript 检查通过；Vite 单文件生产构建通过（341.66 kB，gzip 103.42 kB）。
- 打包：PyInstaller 6.16.0，Python 3.11.9，AMD64；EXE `--smoke-test` 通过：Qt offscreen、SQLite、宠物图片、3D 资源和 Web bundle。
- SHA256：`FCA9C7AC0C54BAD1E85897E645F412D039E7E1022925E2E853499DE26E74D41D`。ZIP 内含 manifest、项目与运行依赖许可文件；未签名。
- 边界：未在干净 Windows、Win10、不同 DPI/多屏或休眠恢复场景验收；smoke-test 不是完整 GUI 安装验收。

## 0.32 UI 视觉升级（2026-11-11）

- 将浅色主题调整为暖纸白/陶土色的编辑式风格，将深色主题调整为午夜蓝紫/暖金光晕的星夜风格；保持两套主题使用同一页面结构和交互。
- 首页焦点待办改为宽幅舞台，并从宠物图库读取当前形象展示；重整今日时间线与周边信息层级。同步调整导航、聊天输入区、任务列表、设置卡片和响应式间距。
- TypeScript 检查与 Vite 生产构建通过（`web/dist/index.html` 357.67 kB，gzip 106.71 kB）。尚未生成 0.32 Windows 包，未做真实桌面多 DPI/多屏视觉验收。

## 发送消息后整页刷新与输入回填修复（2026-11-17）

- 根因与改动见 [IMPLEMENTATION.md](IMPLEMENTATION.md) 同名条目；仅改 `web/src/pages/ChatPage.tsx`（发送后立即持久化空输入、同会话同步不回写输入框、当前会话 `chat.changed` 不再整栏重取）。
- 静态检查：`./node_modules/.bin/tsc --noEmit` 退出 0。
- 真实窗口验证（`start-dev` 热更新模式，Vite 5174，CDP `127.0.0.1:9223`）：发送前在输入框填入文本并点击发送，读回 `input=""`、`skeleton=false`、`refreshing=false`，页面标记 `window.__petNoReload='alive'` 在发送前后一致，确认未发生整页刷新。
- 提交：`0a39190`（分支 `revision`，仅该文件）；前端改动由 HMR 生效，Python 改动仍需重启窗口。
