# Windows 构建与运行

当前代码版本：`0.32.0`。最近已构建包为 `0.32.0`：`windows-0.32.0-20261123-185133-051876/`，包含 Inno Setup 安装器与 GitHub Releases 自动更新。`DesktopPet-0.32.0-setup.exe` 大小 132,542,116 字节，SHA256 为 `AC6056CC2847943F2C510BC606FB0D13B843630B930DFAFD6A4E2A5A121D647F`；ZIP 绿色版大小 191,556,455 字节，SHA256 为 `1E97E64F9BEB3BE2618B81BB7D4C5B79B713DED219DB1990FF7ACE4F0C5A841B`。打包自检通过（qt-offscreen、sqlite、pet-image、pet3d-assets、web-bundle）。

## 构建

在 64 位 Windows 的项目虚拟环境中，从 `desktop-pet` 目录执行。需要 Python 3.10+、Node.js 18+、npm 与 Inno Setup 6（提供 `ISCC.exe`）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build-windows.ps1
```

脚本在 `web/` 下运行 `npm ci`（`node_modules` 不存在时）和 `npm run build`，然后用 PyInstaller 生成 onedir 文件夹发行版，再由 Inno Setup 编译安装包。PyInstaller 固定为 6.16.0。每次写入新版本/时间戳目录，不覆盖旧发行目录。构建需要安装清单中的 Qt 运行组件；缺少依赖、前端构建失败或找不到 `ISCC.exe` 时会停止（可用 `INNO_SETUP_ISCC` 指定路径）。

输出位于 `dist/windows-<版本>-<时间戳>/`：

- `DesktopPet/DesktopPet.exe` 及 `_internal/` 依赖；分发和解压时须保留整个 `DesktopPet` 文件夹。
- `_internal/web/index.html` 主界面和 `_internal/web/pet3d/` 离线 three.js/3D 模型资源。
- `DesktopPet/licenses/` 项目和运行依赖许可文件，以及依赖版本清单。
- `DesktopPet-<版本>-setup.exe` 安装包（Inno Setup，per-user 安装到 `%LOCALAPPDATA%\Programs\DesktopPet`）。
- ZIP 绿色版、`manifest.json`（含安装包 SHA256/大小）和 `smoke-test.json` 自检结果。

构建器运行打包 EXE 的无头自检，检查 Qt 插件、SQLite、宠物图片、3D 资源和 Web 前端，并核对冻结目录资源。自检使用隔离数据目录，不读取用户配置、密钥或数据库。自检通过不代表已覆盖所有真实桌面、显示器和 Windows 版本。

## 分发与运行

正式渠道分发 `DesktopPet-<版本>-setup.exe`，运行后按当前用户安装，无需管理员权限。ZIP 绿色版保留给开发和排障，解压后须运行整个 `DesktopPet` 文件夹内的 EXE。首次运行需配置自己的模型服务和密钥。程序把数据库与设置存放在 `%LOCALAPPDATA%\DesktopPet`；安装、升级和卸载都不会删除这个数据目录。

安装器使用固定 `AppId` 与命名互斥体 `DesktopPetSingleInstance`，覆盖安装会保留数据与启动项；卸载时只删除程序目录，并在启动项指向已卸载 EXE 时清理 HKCU Run 值。源码版和打包版共享当前 Windows 用户的数据目录，不要同时运行。关闭主窗口会留在托盘；从托盘选择“退出”后提醒停止，重启应用会补检仍未处理的逾期待办。

当前安装包未配置数字签名，Windows 可能显示未知发布者提示。

## 自动更新

应用从固定地址读取更新清单：

`https://github.com/python-js/desktop-pet/releases/latest/download/latest.json`

- `latest.json` 声明 `version`、`installer.url/sha256/size` 与更新说明；安装包必须是 HTTPS 地址。
- 打包版启动 10 秒后每天检查一次；设置页可手动检查。发现新版本后由用户确认下载，SHA256 与大小校验通过才允许安装。
- 安装时应用正常退出，临时 PowerShell 助手等待进程结束，再以 `/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS` 运行安装包，成功后重启应用；失败则重新启动旧版本。日志在 `%LOCALAPPDATA%\DesktopPet\updates\install.log`。
- 开发版只显示检查/下载结果，不执行安装；可用 `DESKTOP_PET_UPDATE_URL` 指向本地清单测试。

发布步骤：先推送版本提交，再构建安装包，然后带 GitHub token 发布：

```powershell
$env:GITHUB_TOKEN = '<具有 repo 权限的 token>'
.\.venv\Scripts\python.exe tools\publish_release.py --notes-file docs\release-notes.md
```

脚本会创建 `v<版本>` Release（先 draft，上传安装包和 `latest.json` 后再发布），清单写入安装包 SHA256 与大小。token 只用于发版机器，不进入仓库或安装包。`--dry-run` 只在本地产出 `latest.json`。

## 验收边界

验证日志截至 2026-11-11 记录了 Win11 单屏 2560×1440@100% 下的 WebEngine 界面/桥接检查、打包自检及有限常驻运行观察。2026-11-23 在本机 Win11 完成安装器与自动更新验收：per-user 全新安装、覆盖安装（HKCU Run 指向迁移）、卸载（清理启动项/目录、保留数据目录），以及一次完整自动更新（检查 → 下载 132 MB → SHA256/大小校验 → 退出 → PowerShell 助手静默安装 → 重启安装版）。Win10、125%/150% DPI、双屏与跨屏拖动、休眠唤醒、干净机器首次启动、DPAPI 登录启动的目标机验收尚未完成；签名前还应按实际发行渠道复核 Qt/PySide6 许可及发行义务。详细证据见 [验证记录](VALIDATION.md) 与 [Web 迁移计划](WEB_MIGRATION_PLAN.md)。
