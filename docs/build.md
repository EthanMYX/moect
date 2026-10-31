# 构建 Moect

## 环境

Windows x64、Python 3.11 x64、Node.js 22+。安装器使用 Inno Setup 6.5+。开发依赖见根目录 requirements.txt 和 frontend/package-lock.json。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
Copy-Item ui/icon.svg ui-qce/icon.svg
python build.py
.\installer\build.ps1 -OutputDirectory .\release
```

程序产物为 `dist\Moect\Moect.exe` 及其完整 `_internal` 文件夹；安装产物为 `release\Moect-1.1.5-Setup-x64.exe`。版本统一取自 `core/version.py`，安装脚本读取已构建 EXE 的版本。

`installer/build.ps1` 首次从 Microsoft 官方地址下载 WebView2 引导程序到忽略的 `build-support` 目录，并验证 Microsoft Authenticode 签名后才编译。安装器按当前用户安装，检测 HKCU / HKLM 的 WebView2 运行环境；仅在缺失时执行引导程序。程序未附带 Authenticode 代码签名证书。

安装器中文翻译来自 Inno Setup 官方源代码仓库的 `Files/Languages/ChineseSimplified.isl`，文件保留原维护者信息。

入口为 `edge_app.py`。`app.py` 是保留的旧 Qt 宿主，不进入当前发布程序。修改前端后需要重新执行前端构建并复制图标，再执行 Python 打包。

## README 宣传图

```powershell
pip install playwright
python docs/tools/render_assets.py
```

脚本使用已安装的 Microsoft Edge，无需下载额外浏览器。在隔离临时目录中生成虚构数据，把真实前端和查看器渲染为截图，再用 HTML/CSS 组合成紫色宣传图。不会读取本机微信数据库，也不会操作用户现有窗口。成品位于 `docs/images`；中间截图和页面被 Git 忽略。

## 本次发布检查

1.1.5 进行了 25 项合成数据库与资源测试、Python AST/Ruff 静态检查、TypeScript/Vite 构建、PyInstaller 及 Inno Setup 编译。没有读取反馈用户的真实聊天数据或运行桌面界面回归测试。软件界面由用户检查。
