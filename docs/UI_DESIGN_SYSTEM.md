# Desktop Pet 全局界面规范与实现

版本0.30.1，2026-10-30。设置页“宠物形象”图库可切换默认/历史图片并去背景；桌宠默认显示内置 3D 哈士奇（Quaternius，骨骼动画：Idle 待机、Walk 走动、Gallop_Jump 单击反应），头部跟随鼠标、拖拽晃动，并会偶尔沿屏幕水平巡逻，也保留原图 2D 模式并保留轻微上下浮动，气泡按内容自适应宽高，沿用暖奶油底色与珊瑚橙强调色；对话改为 Markdown 正文加末尾 tasks 任务块协议，助手消息原生渲染 Markdown，流式内容在历史占位消息中原地更新；新增按任务标记的钉钉群通知；对话支持修改、完成、删除待办，同标题多条时以序号列表二次确认；同一待办最多提醒3次，之后标记为延期并停止提醒；侧栏去掉“工作空间”小标题并放大导航项。

## 1. 设计变量

| 用途 | 规范 |
| --- | --- |
| 字体 | Microsoft YaHei UI；其他平台使用系统无衬线 |
| 标题/分组 | 页面标题22px，分组16px，600～700字重 |
| 正文 | 14px，暖黑#2B2622 |
| 辅助 | 13px，暖灰#8A8178；版本号#B9AEA2 |
| 页面 | 暖奶油#FAF7F2；侧栏#FFFDF9 |
| 内容卡片 | #FFFFFF，16px圆角 |
| 主色 | 主操作#C9563F；高亮、焦点与图标#E8735A |
| 用户气泡 | 柔光珊瑚#FFF0EA |
| 输入/按钮 | 10px圆角，至少36px高；输入卡片16px圆角 |
| 消息间距 | 常规轮次24px，用户接助手12px |
| 阴影 | 暖灰rgba(120,82,60,0.09)，模糊30px，下偏移6px |

Qt QSS不支持浏览器级通用line-height和box-shadow，不能照搬CSS。聊天正文用QTextBlockFormat的150%行高，卡片使用QGraphicsDropShadowEffect，文字和图标由Qt布局与Fluent资源负责。单行控件通过高度与内边距获得呼吸感，不强制1.5倍行高导致截字。

## 2. 全局主题与Fluent边界

ui/theme.py集中配置字体、调色板和页面QSS；ui/fluent.py通过Fluent的setTheme、setThemeColor及setCustomStyleSheet调整组件，避免直接覆盖整份库QSS。自定义QSS只保留页面结构、标题、背景与必要的原生时间控件。

示例：

```python
setTheme(Theme.LIGHT)
setThemeColor('#C9563F')
setCustomStyleSheet(control,
    'LineEdit { border-radius:10px; }',
    'LineEdit { border-radius:10px; }')
```

导航使用NavigationInterface自带图标、hover及选中指示条，顺序为首页、对话助手、待办事项、偏好设置。0.24.1起侧栏不再显示“工作空间”小标题，导航项行高40px、字号15px、项间距8px，展开宽度164px。侧栏使用极浅暖白底和细分隔线，品牌区由爪印图标、名称和副标题组成；版本号单独弱化。设置使用SettingCardGroup + CardWidget，并给内容卡片添加暖灰低透明度阴影。

项目级QSS选择器必须限定到自有控件：待办列表为`QListWidget#taskList`，原生轮子为`QComboBox#nativeCombo`。Fluent的下拉弹层内部是MenuActionListWidget，宽泛的`QListWidget::item`或`QComboBox QAbstractItemView::item`会给菜单项叠加内边距，导致文字上移、行高翻倍。

## 3. 聊天消息组件

ui/chat_widgets.py包含Surface、MessageText、MessageRow、MessageHistory。独立QWidget气泡替代QTextBrowser表格，才能实现头像、12px圆角和真实阴影。

- AvatarWidget用于圆形头像；AI使用珊瑚橙爪印，用户使用Fluent默认人物图标。
- 用户右对齐、柔光珊瑚底；AI左对齐、白底暖灰阴影；气泡16px圆角。
- MessageText仍用QTextBrowser承载可选择文本，setPlainText禁止消息HTML执行和外部资源加载。WrapAtWordBoundaryOrAnywhere支持长链接与连续字符串。
- 0.21起助手消息走MessageText.setMarkdown，使用QTextDocument.MarkdownDialectGitHub渲染标题、列表、表格、引用与代码块；用户消息与系统反馈仍为纯文本。Markdown解析会丢弃裸露HTML块，整段变空时退回setPlainText，避免消息消失。
- 协议：模型输出Markdown正文，任务建议放在末尾```tasks代码块（JSON数组）；core.decode_response先剥离任务块并校验任务，再兼容旧JSON信封（含转义损坏的容错恢复），最后按纯文本处理。任务对象可带dingtalk布尔值，仅当用户明确要求钉钉群通知时为true；0.23起任务对象还可带action与id：缺省action表示创建，update只覆盖给出的title/due_at/repeat/dingtalk字段，complete与delete仅需id；旧数据库中的信封消息在加载和发送给模型前都会解码为正文。
- 文档尺寸变化延迟到事件循环再更新高度，避免布局重入。聊天外层使用Fluent平滑滚动区域。
- 系统反馈居中显示为浅暖灰胶囊，不占用头像气泡。兼容旧数据库“已保存：”消息，无需迁移数据。
- 流式：请求开始时在历史中追加一条“正在思考…”助手占位消息，每60ms由MessageHistory.update_row原地更新正文；完成后同一条消息切换为Markdown正式回复，停止/失败也更新同一条，避免独立预览面板出现、增长、消失造成的页面跳动。旧预览面板代码以注释保留备查。
- 滚动：发送请求时调用scroll_to_end跳到最新内容；update_row与append_message只在距离底部60px内才跟随，用户上滚阅读历史时不再被流式更新反复拉回，手动回到接近底部后恢复跟随。

```python
block = QTextBlockFormat()
block.setLineHeight(150, QTextBlockFormat.ProportionalHeight)
cursor.select(QTextCursor.Document)
cursor.mergeBlockFormat(block)
```

消息跟随底部使用属于MessageHistory的QTimer，随窗口销毁自动取消；用户远离底部阅读时新增消息不强制跳到底部。

## 4. 输入卡片与顶部操作

输入框、状态、生成另一版、停止/重试与发送统一放进Surface。编辑器本体无边框，卡片16px圆角；FocusIn/FocusOut通过eventFilter切换卡片focused属性，QSS只显示珊瑚色外边框。输入区高度限制在72～96px，长文本由内部滚动承载。发送使用PrimaryPushButton，其他操作保持次级样式。

对话页顶部为双行结构：首行左侧标题与副标题，右侧为新对话（主按钮）、重命名、今日规划；次行为“当前对话”小标签 + 280～360px的会话下拉，避免下拉拉满整行后把操作挤到边缘。

```python
editor.installEventFilter(composer)
composer.setProperty('focused', focused)
composer.style().unpolish(composer)
composer.style().polish(composer)
```

Surface的阴影颜色在Enter/Leave之间以160ms QPropertyAnimation过渡。Fluent按钮、导航和弹层沿用组件自带状态反馈，避免重新实现一套鼠标事件。

## 5. 其他页面与窗口

| 界面 | 已调整内容 |
| --- | --- |
| 首页 | 问候总结、四张统计卡、更早逾期提示、今日时间线、快捷操作；点击时间线条目跳转待办并选中 |
| 待办 | 无边框列表 + QStyledItemDelegate自绘任务卡：圆形状态、标题、时间/重复元信息，逾期暖红强调；居中空状态、主新增操作、统一筛选控件 |
| 设置 | 四组16px圆角卡片、暖灰柔和阴影、Fluent表单和滚动区域、弱化说明；宠物组内为可点选缩略图 |
| 待办编辑 | 24px留白、16px行距、明确标题、Fluent取消/主保存按钮、圆角时间输入 |
| 任务草稿 | 浅色卡片、阴影、统一输入与确认按钮 |
| 今日规划预览 | 24px留白、16px控件间距、清晰的确认/取消入口 |
| 去背景预览 | 统一24px留白、16px间距，应用操作使用主按钮 |
| 到期提醒 | 无边框圆角提醒卡，跟随桌宠上方弹出，含时间/重复胶囊与完成、延后、打开待办三个入口；第3次为最终提醒，禁用延后并提示转入延期 |
| 桌宠气泡 | 白色18px圆角、13px字号、暖色细边框、低透明阴影、纯文本和长文字悬停提示 |

### 今日首页

ui/home.py的HomePageMixin复用现有TaskStore，不新增表结构。today_overview在内存中按本地日期分组：今天到期的未完成与已完成任务进入时间线；早于今天且未完成的任务计入逾期提示；下一次提醒取最早的未来待办。

- 结构：问候标题与一句话总结、今日待办/已完成/已逾期/下一次提醒四张卡片、更早逾期提示条、今天安排时间线，以及继续对话、今日规划、新增待办三个入口。
- 时间线：HomeTaskRow使用QFrame承载圆形状态、时间、标题与重复/完成元信息；点击切换到待办页，复用focus_task重置筛选并选中任务。
- 刷新：切到首页、refresh_tasks结束后以及既有30秒任务定时器都会刷新；首页不修改任务状态，全部为只读汇总。

### 宠物形象

设置页将原“宠物形象”和“动作工作室”合并为“宠物形象”。ui/settings.py的PetImageTile以96px圆角缩略图展示默认形象与pet_images历史；选中项使用2px珊瑚描边。默认缩略图由default_pet_image()按桌宠同一套绘制逻辑渲染并填满画布。

- 数据：pet_images保存历史记录（image当前图、original去背景前原图），pet_image继续表示当前选中项；旧版单图配置在加载时自动迁移为一条记录，仅在文件仍存在时保留。
- 展示：0.20起上传、切换、去背景或恢复原图只调用apply_pet_image更新图片，不再生成动作；Pet直接按165×140平滑缩放原图，避免动作帧反复缩放导致的模糊，并保留轻微上下浮动。
- 清理：启动时移除旧pet_animations/pet_animation_backup配置并删除animations/auto-*目录，手动导入目录保留；apply_pet_image也会清理上一组auto目录并清空内存中的动作序列。
- 气泡：0.20.1起由Pet.fit_bubble按文字实际尺寸设置宽高，宽度随最长行收缩（上限210），底边固定在y=84停于宠物头顶上方，超过3行用省略号截断，完整内容保留在tooltip中；样式仍为白色圆角、18px半径与暖灰阴影。
- 删除：仅当前选中的自定义图可移除，确认后切回默认形象并删除该图及其去背景副本（仍被其他记录引用时保留）。
- 已停用备查：0.19的动作帧生成（四类动作、hover 12帧/12fps、SUBJECT_BOTTOM尺寸补偿）仍保留在motion.py、animations.py与Pet的动作方法中，但没有任何调用入口；设置页旧动作工作室实现以注释保留在settings.py末尾。恢复动作需同时还原apply_pet_image的生成块与Pet.load_animations调用。

### 3D 桌宠（0.25）

桌宠默认使用内置 3D 形象，2D 图片模式完整保留，可在右键菜单互相切换。

- 窗口：2D 为220×260，3D 为220×340；3D 画布从 y=88 开始，顶部 84px 继续留给气泡，两者不重叠。切换时保持窗口底边不变（3D 顶边上移80px），并写入 pet_position 与 pet_mode。
- 渲染：ui/pet3d.py 创建透明 QWebEngineView，加载 assets/pet3d/index.html；three.js r147（MIT）、GLTFLoader 与哈士奇 glb 随程序打包，不访问网络。页面背景设为透明，窗口继续使用 FramelessWindowHint + WindowStaysOnTopHint + WA_TranslucentBackground。0.30 起场景为 Quaternius 哈士奇（CC0）：GLB 以 base64 内嵌为 husky.glb.js，经 GLTFLoader.parse 加载，避开 file:// 下 fetch/XHR 的 CORS 限制；相机 24° 视场、距离 10，模型按高度缩放至 2.4 个单位、脚底对齐 y=0，保留柔和三点光与落地阴影。0.29 的 Khronos 狐狸（fox.glb.js）保留作回退。模型署名见 HUSKY_LICENSE.txt / FOX_LICENSE.txt。
- 交互：WebEngine 内部渲染控件会直接接收鼠标，create_view 对其全部子控件安装事件过滤器，由 Pet 统一处理拖动、单击反馈、双击打开主窗与右键菜单；3D 模式下暂停 2D 动画定时器与动作帧。
- 待机动画（0.26）：requestAnimationFrame 驱动呼吸（3.6秒周期，卫衣缩放约 ±1.2%/±1.8%，整只宠物上下浮动0.012）、随机眨眼（间隔2.6–5.4秒，闭合0.13秒，眼睛与高光同步压缩）、尾巴左右摆动（4.8秒）与气球绕右手轻摆（5.2秒，绕 X/Z 轴）。页面暴露 `window.pet3d.setPaused(bool)`：暂停时 `setAnimationLoop(null)` 并只渲染一帧，恢复时重置 Clock 后继续。（0.29 换成骨骼模型后，程序化模型与呼吸/眨眼/气球动作已移除，暂停接口保持不变。）
- 骨骼动画（0.30）：AnimationMixer 管理 Idle（待机循环，3.3 秒）、Walk（走动循环，1.04 秒）、Gallop_Jump（LoopOnce，0.92 秒）三段动画；切换用 fadeIn/fadeOut 交叉淡入。单击触发 Gallop_Jump，播放约一个片段时长后由时间兜底回到当前状态（走动中则回 Walk）。待机时模型朝向固定 0.35 弧度，走动时目标转为 ±0.62 弧度朝向行进方向，并叠加 0.015 的步频起伏（周期与该片段一致）；点击反应保留 0.9 秒小跳，拖拽时离地 0.05 并轻微倾斜。头部跟随改用颈部骨骼 Neck3（耳朵是 Head 的兄弟节点，只转 Head 会只剩鼻子动）：在 `mixer.update(delta)` 之后把世界坐标的偏航/俯仰（约±0.32/±0.18 弧度）换算到父骨骼空间再叠加，整个头连同耳朵一起转向。
- 鼠标互动（0.27）：Pet 以80ms轮询全局鼠标位置，换算为相对 3D 画布中心的归一化方向（阈值0.02避免频繁跨进程调用），调用 `window.pet3d.lookAt(x, y)`；页面把方向平滑插值后作用于颈部骨骼，旋转整个头。单击（未拖动）调用 `window.pet3d.react()`：播放 Gallop_Jump 并小跳。拖拽越过系统阈值时调用 `setDragging(true/false)`，页面让宠物轻微离地并左右晃动，松手回正。
- 偶尔巡逻（0.28）：3D 模式下静止随机20–40秒后开始走动，时长随机3–6秒、速度45像素/秒，沿当前屏幕水平移动；到 availableGeometry 左右边缘立即掉头并继续走完剩余时长。窗口位置由40ms定时器按时间差推进，Walk 骨骼动画与小幅上下起伏配合，模型转向行进方向。鼠标移入、按下、暂停动画、切回2D或打开右键菜单时立即停止，脚下位置在停止时写入设置；右键“暂停走动/恢复走动”写入 pet_walking，下次启动恢复。
- 暂停联动：右键“暂停动画/恢复动画”在两种模式都显示；3D 调用 setPaused，2D 启停定时器，状态统一写入 pet_paused。加载完成、启用 3D、切回 2D 时都会同步暂停状态，切回 2D 会先停掉 3D 渲染循环。暂停时同时停止视线轮询与走动，恢复后重新开始。
- 回退：未安装 PyQtWebEngine、平台为 offscreen 或视图创建失败时自动保持 2D，不阻塞启动；状态栏给出提示。

### 钉钉群通知

0.22起到期提醒可额外推送到钉钉自定义机器人，默认关闭，按任务单独启用。

- 数据：tasks新增dingtalk标记（默认0），数据库版本升到5并自动备份；重复任务生成下一次时继承标记，edit未显式传值则保留原状。
- 创建：任务块支持"dingtalk":true，系统提示词限定只在用户明确要求钉钉群通知时置真；本地规则识别“钉钉群通知/发到钉钉群”等说法并从标题移除渠道词；TaskDialog增加“到期时同时发送到钉钉群（仅此待办）”勾选框；待办卡片的元信息追加“· 钉钉”。
- 配置：设置页“钉钉群通知”卡片包含Webhook、加签密钥、保存与发送测试。dingtalk.validate_webhook只接受https://oapi.dingtalk.com/robot/send且必须带access_token；SecretStore新增dingtalk.dpapi，沿用DPAPI加密，不写入settings.json。
- 发送：dingtalk.send按钉钉加签规范计算timestamp与HMAC-SHA256 sign，发送text消息（标题、时间、重复规则），8秒超时并禁止重定向。app.check_due在本地提醒、气泡与托盘消息之后调用push_dingtalk，后台线程执行，结果经dingtalk_result回到主线程；失败只提示状态栏和托盘，不阻塞提醒、不自动重试。未配置机器人时任务照常本地提醒，回执注明“到期仅本地提醒”。

### 对话内管理待办

0.23起可在对话中修改、完成、删除已有待办，仍由程序校验与执行，模型只负责语义匹配。

- 上下文：assistant.task_snapshot把最多50条未完成待办按到期时间列成“id | 标题 | 到期 | 重复 | 状态”，附在系统提示词末尾；超出部分注明不可操作。提示词要求模型逐字引用id、同标题多条时列候选反问、修改时间必须为未来时间、正文不得声称执行成功。
- 解码：core.\_decode_tasks支持action=update/complete/delete；update至少包含一个字段，id必须为32位十六进制；动作与字段非法时逐条计入errors，不影响同批其他操作。本地规则模式检测到管理动词时提示到待办页操作，不写库。
- 执行：app.execute_task_op重新读取当前未完成列表校验id；update用缺省字段补全原值后调用TaskStore.edit，已逾期且未给新时间时拒绝；complete调用TaskStore.complete并在回执中给出下一次时间；delete软删除并写入last_deleted，待办页可撤销。回执采用“原 → 新”格式，并刷新待办页、关闭对应提醒卡。
- 歧义：目标标题在当前未完成列表中出现多条时不执行，app.build_choice输出按到期时间排序的序号列表（含时间、重复、逾期标记），选择状态按会话存入task_choice。下一条消息若为序号（支持“2”“第2个”“第二条”），在发起模型请求前直接执行；超出范围保留选择并提示，其他内容清除选择后正常请求。应用重启后选择状态丢失。
- 记录：选择提示与回执作为助手消息写入会话历史，重载后仍可见，但其中序号不再可点击或可回复。

### 到期提醒卡

ui/reminder.py的ReminderDialog取代系统QDialog：Qt.FramelessWindowHint去边框，WA_TranslucentBackground承载20px圆角白卡与暖灰阴影，固定420px宽。卡片自上而下为爪印图标与“待办提醒”标签、关闭按钮、20px标题、时间胶囊（逾期用#FDECEA/#B4432F，正常用#FFF0EA/#C9563F，重复规则非none时追加灰色胶囊）、提示“关闭后仍可在待办页继续处理”，以及完成（主按钮）、10分钟后、打开待办（透明文字按钮）。第3次（最终）提醒的提示改为“已提醒 3 次，关闭后将标记为延期，不再提醒”，并禁用“10 分钟后”按钮、附tooltip说明。

- 定位：present(anchor, index)优先放在桌宠上方14px；空间不足放到下方；桌宠不可见时落在屏幕右下角24px。多个同时到期的提醒按index纵向错开，并夹紧在当前屏幕可用区域内。
- 动效：showEvent中非offscreen环境播放180ms淡入并上移8px，offscreen直接显示以保证截图与测试稳定。
- 生命周期：app.py的check_due为每个到期任务创建并记录到self.reminders，finished时forget_reminder执行pop + deleteLater；完成/延后走resolve并关闭，打开待办会显示主窗、切到待办页并选中该任务。
- 次数与延期：tasks新增remind_count与deferred（默认0），数据库版本升到6并自动备份。每次实际弹出提醒（含启动补提醒与手动延后后再次到期）由TaskStore.mark_shown计数，达到REMIND_LIMIT=3时置deferred=1并在状态栏提示；due()排除已延期任务，启动时reset_notifications也跳过它们，因此不再弹窗、气泡、托盘或推送钉钉。延期任务仍为pending，首页逾期统计继续计入；待办卡与首页时间线显示“已延期”并弱化红色，点击“十分钟后提醒”只提示去修改时间。edit与reopen会清零计数和延期状态，重新开始提醒。

Fluent滚动区域沿用细滚动轨与交互展开；保留原生控件的区域使用6px细滚动条。系统文件选择器、Windows原生标题栏及部分标准消息框仍由系统/Qt管理，不承诺对系统窗口进行完整自绘。

## 6. 验证与维护

本轮通过`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -q`运行99项测试；新增“3D 模式在 offscreen 环境回退 2D 且 pet_mode 可持久化”回归；此前“3次提醒后延期且重置通知/延后不再触发”“编辑与恢复待办清零延期状态”“第3次提醒卡禁用延后并在待办页显示延期”等回归保持通过。3D 透明背景、原生鼠标拖动、2D/3D 往返切换使用 `.artifacts/capture_pet3d.py`、`test_pet3d_drag.py`、`test_pet3d_toggle.py` 在真实桌面验证；0.26 的待机动画与暂停静止使用 `test_pet3d_anim.py` 对比间隔1.2秒的连续截图（运行帧不同、暂停帧一致）；0.27 的视线、点击与拖拽使用 `test_pet3d_interact.py` 钩住页面接口：鼠标移到左右两侧分别收到 x=-1/1，单击触发一次 react，拖拽依次收到 true/false 且窗口移动，暂停后视线调用数不再增加；0.28 的巡逻使用 `test_pet3d_walk.py` 验证约 1 秒移动 48px、右边缘自动掉头、鼠标移入/暂停立即停止、开关写入 pet_walking；0.29 的狐狸模型使用 `test_pet3d_fox.py` 在真实桌面截图检查待机、左右视线、点击奔跑、巡逻、拖拽与暂停，并复查 `test_pet3d_interact.py` 的视线值为 x=-1/1、react 触发一次、拖拽 true/false、暂停后视线调用数不变，`test_pet3d_walk.py` 的移动、掉头与停止全部通过；走动转向时模型完整落在 220px 窗口内。0.30 换成哈士奇后沿用同一套脚本复测待机、注视、点击跳起、左右巡逻、拖拽与暂停，并按 220×252 画布导出页面 canvas 检查取景。视觉检查使用.artifacts/capture_warm_ui.py同时生成offscreen与Windows原生渲染截图，覆盖首页、聊天、下拉、待办、宠物图库设置、设置下半部、到期提醒与桌宠。

运行unittest、tools/check_fluent.py及打包自检；检查长消息、连续URL、流式更新、会话切换、滚动位置、草稿确认与窗口销毁。高DPI与多显示器缩放仍需在真实桌面环境验收，尤其是提醒卡夹紧屏幕边缘和桌宠上方空间不足时的回退位置。

不要将视觉样式分散到业务分支；新控件优先使用ui/controls.py和ui/fluent.py。新内容容器复用Surface或CardWidget，辅助文字使用subtitle，主操作显式primary=True。
