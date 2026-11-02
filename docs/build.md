# 构建 Moect

## 开发环境

Windows x64、Python 3.11 x64、Node.js 22+；安装器使用 Inno Setup 6.5+。Python 依赖见 `requirements.txt`，前端依赖由 `frontend/package-lock.json` 锁定。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
Copy-Item ui/icon.svg ui-qce/icon.svg
python build.py
.\installer\build.ps1 -OutputDirectory .\release
python scripts/package_release.py .\release --no-source
```

`build.py` 从 `core/version.py` 读取版本，生成 `dist/Moect/Moect.exe`、完整依赖目录、独立更新组件及受管理文件清单。安装脚本读取 EXE 版本并生成 `Moect-版本号-Setup-x64.exe`；打包脚本生成便携 ZIP 与校验文件。便携包不附带使用说明和修复说明，保留运行依赖及许可证。

程序入口是 `edge_app.py`，前端构建至 `ui-qce`。`app.py` 为保留的旧 Qt 宿主，不进入当前桌面发行包。修改前端后重新构建并恢复图标，再进行 Python 打包。

安装器允许选择安装位置与桌面快捷方式，使用当前用户权限。首次构建从 Microsoft 官方地址获取 WebView2 引导程序并校验其 Microsoft Authenticode 签名；用户安装时仅在缺少运行环境的情况下执行。Inno Setup 中文翻译保留原维护者信息。

## 发布

GitHub 版本标签应指向与二进制对应的源码提交。安装包与便携版发布到 Release，源码可通过该标签获取；公开的 SHA256SUMS.txt 只列出公开发行附件。

`scripts/publish_release.py` 使用本机已配置的 GitHub 凭据完成草稿、上传校验和正式发布，不把凭据写入仓库。其发布参数只接受安装包、便携 ZIP 与公开校验文件。内置公告/更新服务由独立的签名发布通道管理，详见 [公告与更新](announcements-updates.md)。

## 可选作者工具

发布中心是独立入口 `publisher_app.py`，可在 frontend 目录执行以下命令构建界面，再运行 `python build_publisher.py`：

```powershell
npx tsc --noEmit
npx vite build --config vite.publisher.config.ts
```

该工具需要作者自己的签名私钥和服务授权。构建仅收集程序代码、公开验签配置、界面与许可证，不包含作者资料或授权文件。使用方式见 [发布中心](publisher.md)。

## 验证与宣传图

测试使用合成数据库与虚构媒体。可运行 `python -m unittest` 执行后端测试；构建界面回归使用 Playwright 与已安装的 Microsoft Edge。不会为测试上传真实聊天记录。

`docs/tools/render_assets.py` 将虚构演示数据渲染为 README 宣传图。字体、第三方许可证和媒体来源信息保留在 `THIRD_PARTY_LICENSES`、`THIRD_PARTY_NOTICES.md`。
