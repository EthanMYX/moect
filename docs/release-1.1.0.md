Moect 的首个公开发布版本。微信会话、媒体与离线聊天归档，集中在一个紫色主题的 Windows 桌面软件里。

## 下载

- **Moect-1.1.0-Setup-x64.exe**：推荐，中文一键安装包，创建桌面和开始菜单入口；缺少 WebView2 时自动准备运行环境，需要联网。
- **Moect-1.1.0-Windows-x64.zip**：便携版，解压完整文件夹后运行 Moect.exe；需要系统已安装 WebView2。
- **Moect-1.1.0-Source.zip**：对应的完整项目源码、构建脚本与许可证。
- **SHA256SUMS.txt**：上述三个文件的 SHA-256 校验值。

## 这次带来了什么

- 单聊、群聊预览与批量导出，HTML / JSON / JSONL / TXT / CSV / Markdown 六种格式。
- HTML 打开即进入对话，批量归档可在聊天页切换会话；正文/发送者搜索和北京时间范围筛选。
- 可用头像、图片、GIF、音视频、引用回复、合并转发与独立转发页。
- 链接、小程序、文件、位置及历史转账卡片，资源随导出保存，缺失资源提供明细。
- 会话名称任务、文件/目录入口及记录删除；紫色主题、鸿蒙字体、桌面窗口拖动与缩放。
- 升级沿用旧数据和导出历史，卸载保留用户数据。

## 适用范围

Windows 10 1809+ / Windows 11 x64，面向 Windows 微信 4.x。微信更新可能影响兼容性；未缓存、已失效或凭据不可用的媒体不保证恢复。归档应整份保留 HTML、消息分片和资源目录。

发布前完成静态检查、TypeScript/Vite 构建、PyInstaller 与 Inno Setup 编译。未进行真实微信导出或安装过程测试。安装包尚未进行 Authenticode 签名。

[使用指南](https://github.com/mofan6/Moect/blob/main/docs/usage.md) · [项目介绍](https://github.com/mofan6/Moect) · [反馈问题](https://github.com/mofan6/Moect/issues)

本项目按 GPL-3.0 发布。
