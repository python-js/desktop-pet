# Desktop Pet

Windows 桌面 AI 助手：用自然语言创建和管理待办，通过桌面宠物提醒；包含首页、任务管理、多会话聊天、联网搜索、本地知识库、免打扰与钉钉通知。主窗口使用 React + QtWebEngine，待办和设置由 Python/PySide6 本地服务提供，数据保存在本机。

当前代码版本：`0.32.0`。与根目录的 `opendoro` 是独立应用，不读取其模型配置或个人记录。当前以 Windows 10/11 x64 为目标；macOS 尚未完成验证。`0.32.0` 的安装包尚未生成；最近的打包结果为 `0.31.0`，未包含本轮视觉升级，见 [Windows 构建说明](docs/WINDOWS_BUILD.md)。

## 功能概览

- 通过 OpenAI Chat Completions 兼容接口聊天，支持 SSE 流式输出、停止、重试、重新生成及多会话。
- 对话可创建、修改、完成和删除待办。通过校验的操作会直接执行，无需再次确认或保存；信息不足或同名事项无法确定时会追问。重复规则支持不重复、每天、工作日、每周。
- 首页展示今日待办和提醒时间线；支持逾期、稍后提醒、免打扰时段、提前提醒、自动顺延、提醒次数上限、今天别再提醒、任务历史、撤销删除及数据导出/清空。
- 可选 Tavily 联网搜索、本地文档知识库、钉钉群提醒。联网服务和钉钉凭据由用户自行配置；Windows 可使用 DPAPI 加密记住密钥。
- 支持 2D 图片宠物与内置骨骼动画 3D 哈士奇，可拖动、互动、暂停及在屏幕变化后找回位置。

图片作为 2D 宠物显示，内置 3D 哈士奇是独立素材；目前尚不能根据上传图片生成 2D/3D 角色或 Live2D 模型。桌面宠物不是可靠闹钟：彻底退出期间不会即时提醒，重启后会补检未处理的到期事项。请勿用于关键提醒。

## 运行源码

需要 Windows 64 位、Python 3.10+、Node.js 18+ 和 npm。首次安装：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Push-Location web
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe -m desktop_pet
```

开发前端时，使用 `start-dev.ps1` 启动桌面版热更新模式。它会启动 Vite 开发服务器并连接桌面 WebView；保存 React、TypeScript 或 CSS 文件后，界面会自动更新，通常无需重启桌面窗口。关闭桌面程序后，启动脚本会自动停止 Vite。

`start.ps1` 用于启动已经构建好的源码版；面向发布的构建仍通过 `npm run build` 生成 `web/dist/` 单文件页面。Python 后端代码、桌面窗口外壳或 Python 依赖发生变更时，仍需重启应用。开发模式仅用于本机，不用于发行包。

## 试用流程

1. 打开聊天页，输入例如“明天 9 点提醒我开会”，应用会直接创建通过校验的待办，无需再点保存。每月或自定义间隔重复规则尚不支持；事项、时间不完整时助手会追问。
2. 未配置模型时仅支持有限的本地时间规则；在设置中配置 OpenAI 兼容 API 地址、模型和自己的密钥后即可使用模型聊天。聊天及必要的任务上下文会发送给用户配置的供应商。
3. 在待办页查看和编辑任务，或在偏好设置中配置联网搜索、知识库、钉钉通知、登录启动和提醒偏好。
4. 上传图片作为 2D 宠物，右键宠物可切换内置 3D 哈士奇。3D 和主窗口均需要 PySide6 QtWebEngine。

## 构建 Windows 发行包

安装构建依赖后执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build-windows.ps1
```

需要 Node.js 18+ 与 npm。构建脚本会构建 Web 前端，再生成免安装 onedir 文件夹、打包自检结果、SHA256 清单、第三方许可证和 ZIP。成功后可将 `dist/windows-<版本>-<时间戳>/DesktopPet-<版本>-windows.zip` 发给 Windows x64 用户。对方需完整解压 ZIP 并运行 `DesktopPet/DesktopPet.exe`；不要从文件夹里单独复制 EXE。用户需自行配置自己的模型服务和密钥。

发行包目前未做代码签名，也不包含安装器或自动更新。解压后第一次启动可能显示 Windows 未知发布者提示。

## 开发检查

```powershell
Push-Location web
npm ci
npm run build
Pop-Location
python -m unittest discover -s tests -q
```

最近一次已记录的迁移回归为 169 项 Python 测试通过、Web 前端构建及打包 EXE 自检通过，详见 [验证记录](docs/VALIDATION.md)。这些记录对应其标注的提交/构建；修改后应在当前代码上重新验证。当前 Web 迁移及验收边界见 [迁移计划](docs/WEB_MIGRATION_PLAN.md)，桥接协议见 [BRIDGE_API.md](docs/BRIDGE_API.md)。

## 设计与隐私

- [产品与技术设计](docs/DESIGN.md)
- [实施计划](docs/IMPLEMENTATION.md)
- [Web 迁移计划](docs/WEB_MIGRATION_PLAN.md)
- [界面设计系统](docs/UI_DESIGN_SYSTEM.md)
- [Windows 构建与发布](docs/WINDOWS_BUILD.md)
- [验证记录](docs/VALIDATION.md)

聊天内容会发送给用户配置的模型服务；如启用联网搜索或知识库，相关查询或文档片段也可能随模型请求发送。数据文件保存在 `%LOCALAPPDATA%\DesktopPet`。发行包构建不包含本机数据、设置、密钥或用户上传图片。详见偏好设置中的密钥选项与数据管理功能。
