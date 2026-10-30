# Windows 构建与运行

版本：0.30.1；日期：2026-10-30。

当前交付为构建脚本与打包兼容代码；本机已按此脚本产出构建，但受限环境尚未在未安装 Python/Qt 的干净机器上验收。

## 构建

在 Windows 64位 Python 虚拟环境中，从 desktop-pet 目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build-windows.ps1
```

构建器固定使用 PyInstaller 6.16.0，使用当前虚拟环境中的运行依赖。每次写入新的带版本与时间戳目录，不覆盖旧发行目录。缺少依赖时直接报错，不自动安装或修改注册表。

成功后 `dist/windows-0.30.1-时间戳/` 包含：

- `DesktopPet/DesktopPet.exe` 和 `_internal` 依赖目录；整个 DesktopPet 文件夹必须一起保留。`_internal/desktop_pet/assets/pet3d/` 内含 three.js、GLTFLoader、哈士奇与狐狸模型（含许可证），3D 模式离线可用。
- `DesktopPet/licenses/` 项目许可证、运行依赖许可证原文和依赖版本清单。
- ZIP压缩包、文件SHA256清单 `manifest.json` 与打包程序自检结果 `smoke-test.json`。

自检会运行新EXE的专用入口，检查Qt离屏插件、内存SQLite、基础动作生成与 3D 场景资产；构建器另外核对包内 `assets/pet3d` 文件齐全。不访问真实配置、密钥或用户数据库。自检失败不会生成最终ZIP；仍可能留下中间构建目录。

## 运行与数据

解压完整文件夹后双击DesktopPet.exe。应用数据仍保存到 `%LOCALAPPDATA%\DesktopPet`，源码版与打包版共享当前用户数据，因此两者不要同时运行。QLockFile继续防止重复实例。

不要将设置、数据库、API Key或上传的宠物素材放入发行包。构建仅从launch.py依赖图收集代码，不复制应用数据目录、旧opendoro项目或整个工作区。

打包版的登录启动直接调用EXE的 `--background` 参数。切换到打包版或移动文件夹后，需在设置中重新应用启动配置。不会自动改写已有启动项。首次迁移前建议保留数据目录备份。

## 发行状态

该方案生成免安装文件夹版，暂不包含安装器、数字签名或自动更新。代码实现不等于已通过真实打包验收。

PyQt5使用GPLv3或商业许可；项目根目录为Apache-2.0许可证。构建器收集依赖许可文件，不代替对发行方式与许可要求的确认。Qt插件和实际产物清单以构建结果为准。

尚需在真实打包程序中验证：正常显示、中文文字、托盘、透明窗口、提醒、密钥加密、登录启动，以及没有Python环境的Windows机器运行。
