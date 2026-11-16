# Windows 构建与运行

当前代码版本：`0.32.0`（2026-11-11）。最近已构建包为 `0.31.0`：`windows-0.31.0-20261111-113751-946102/DesktopPet-0.31.0-windows.zip`，未包含 0.32 视觉升级；其 SHA256 为 `FCA9C7AC0C54BAD1E85897E645F412D039E7E1022925E2E853499DE26E74D41D`。0.32 对应安装包需重新运行本页构建流程。

## 构建

在 64 位 Windows 的项目虚拟环境中，从 `desktop-pet` 目录执行。需要 Python 3.10+、Node.js 18+ 与 npm：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build-windows.ps1
```

脚本在 `web/` 下运行 `npm ci`（`node_modules` 不存在时）和 `npm run build`，然后用 PyInstaller 生成 onedir 文件夹发行版。PyInstaller 固定为 6.16.0。每次写入新版本/时间戳目录，不覆盖旧发行目录。构建需要安装清单中的 Qt 运行组件；缺少依赖或前端构建失败时会停止。

输出位于 `dist/windows-<版本>-<时间戳>/`：

- `DesktopPet/DesktopPet.exe` 及 `_internal/` 依赖；分发和解压时须保留整个 `DesktopPet` 文件夹。
- `_internal/web/index.html` 主界面和 `_internal/web/pet3d/` 离线 three.js/3D 模型资源。
- `DesktopPet/licenses/` 项目和运行依赖许可文件，以及依赖版本清单。
- ZIP、`manifest.json` SHA256 清单和 `smoke-test.json` 自检结果。

构建器运行打包 EXE 的无头自检，检查 Qt 插件、SQLite、宠物图片、3D 资源和 Web 前端，并核对冻结目录资源。自检使用隔离数据目录，不读取用户配置、密钥或数据库。构建后会生成 ZIP；自检通过不代表已覆盖所有真实桌面、显示器和 Windows 版本。

## 分发与运行

把 `DesktopPet-<版本>-windows.zip` 发给 Windows x64 用户。对方应完整解压后运行 `DesktopPet/DesktopPet.exe`，不能只复制 EXE。首次运行需配置自己的模型服务和密钥。程序把数据库与设置存放在 `%LOCALAPPDATA%\DesktopPet`；构建不会打包本机应用数据或用户资源。

源码版和打包版共享当前 Windows 用户的数据目录，不要同时运行。关闭主窗口会留在托盘；从托盘选择“退出”后提醒停止，重启应用会补检仍未处理的逾期待办。打包后的登录启动直接调用 EXE；移动应用目录后需重新应用启动设置。

当前交付是免安装 onedir ZIP，未配置数字签名、安装器或应用内自动更新。Windows 可能对未签名程序显示未知发布者提示。

## 验收边界

验证日志截至 2026-11-11 记录了 Win11 单屏 2560×1440@100% 下的 WebEngine 界面/桥接检查、打包自检及有限常驻运行观察。Win10、125%/150% DPI、双屏与跨屏拖动、休眠唤醒、干净机器首次启动、DPAPI 登录启动的目标机验收尚未完成；签名前还应按实际发行渠道复核 Qt/PySide6 许可及发行义务。详细证据见 [验证记录](VALIDATION.md) 与 [Web 迁移计划](WEB_MIGRATION_PLAN.md)。
