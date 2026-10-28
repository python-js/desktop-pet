# QFluentWidgets 改造

版本0.16.0，日期2026-10-27。已安装并验证PyQt-Fluent-Widgets 1.8.7，普通启动默认使用Fluent，依赖已加入requirements.txt。

## 已接入

真实PushButton/PrimaryPushButton、ComboBox、SpinBox、CheckBox、LineEdit和TextEdit；NavigationInterface图标导航；SettingCardGroup与CardWidget分组设置。Qt富文本历史展示、时间选择及宠物窗口继续使用原有实现。不是所有对话框均重写为Fluent窗口。

ui/fluent.py适配下拉userData参数、尺寸接口和方向键；使用parent构造后setText，避免库的重载构造递归。原主操作使用PrimaryPushButton。主题仅保留项目页面外壳样式，让Fluent管理组件样式与资源。

## 启动

源码使用原start.ps1或python -m desktop_pet即可。launch-fluent.ps1保留为显式Fluent入口。可在进程环境DESKTOP_PET_UI=native时临时使用旧组件，不改写用户配置。

共享原数据目录和单实例锁。先从托盘退出旧程序，再打开新版EXE。模型服务、密钥、数据库和宠物素材不包含在包内，也不被本次改造清除。

## 验证

71项测试通过；tools/check_fluent.py通过，覆盖真实组件类型、会话恢复、草稿、下拉数据映射与键盘。新增构造重载及禁用选项跳过的回归测试。Qt测试共享单个QApplication，以保持Fluent全局路由对象的正常生命周期。

实际EXE已打包并创建完整Fluent主窗口完成离屏自检（临时数据、禁用启动项和密钥适配器）。设置页、聊天页、动作区域与弹层截图已检查；1000像素宽设置页无横向溢出。真实Windows高DPI与系统字体缩放仍需用户环境验收。

## 发行

构建器收集qfluentwidgets资源，并记录QFluentWidgets、FramelessWindow、darkdetect等运行依赖版本及许可证。QFluentWidgets和PyQt的GPL/商业许可按最终发行方式确认。
