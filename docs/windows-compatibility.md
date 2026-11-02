# Windows 兼容性调查

当前桌面版的目标系统为 Windows 10 1809 x64 及以上、Windows 11 x64。此次没有降低主程序依赖、字体、主题、WebView2 渲染、窗口拖动和缩放效果，也没有打包或发布 Win7 版本。

## Win7 x64 安装失败的已确认原因

1. 安装脚本明确设置了 `MinVersion=10.0.17763`。Win7 的系统版本为 6.1，即使是 64 位也会被安装器拒绝。新版脚本为这个检查增加了中文说明。
2. 随附 Python 3.11 的官方最低系统为 Windows 8.1，不能靠取消安装器限制在 Win7 运行。Python 官方建议需要 Win7 的程序使用 Python 3.8，而当前源码和部分原生依赖需要更高版本。
3. Win7 可用的最后一代 Edge/WebView2 为 109，无法安装当前 Evergreen 运行时。当前前端使用现代 Tailwind CSS 和浏览器能力，强行固定到旧内核还需要独立构建和页面适配。
4. 原生宿主使用 `SetProcessDpiAwarenessContext` 等新 Windows API。这些调用及现有原生 Python 扩展也必须逐项替换或分支处理。

因此，仅改安装器最低版本、使用便携包、勾选 Windows 兼容模式或管理员运行，均不能形成可用的 Win7 桌面版。当前没有真实 Win7 系统的验证条件，不能声称已兼容。若未来提供 Win7 桌面版，应使用独立的旧系统构建、依赖锁定与测试环境，不能让 Win10/11 主程序回退。

## 目前可行的使用方式

在 Windows 10/11 完成导出，将整个 HTML 导出文件夹复制到 Win7，用支持其脚本能力的浏览器阅读。离线聊天和资源查看器不依赖 Python、WebView2 安装或登录微信；但旧版 Internet Explorer 不支持查看器。此方式仅用于阅读归档，不能在 Win7 本机连接或导出微信，媒体编解码能力仍取决于浏览器。

## 官方资料

- [Python 3.11 on Windows — supported systems](https://docs.python.org/3.11/using/windows.html)
- [Microsoft Edge / WebView2 supported operating systems](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-supported-operating-systems)
- [SetProcessDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext)
