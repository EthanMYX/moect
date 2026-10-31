# Moect 1.1.0 · 首次公开发布（2026-10-31）

- HTML 归档入口直接打开聊天记录，批量导出在聊天页顶部切换会话。
- 新增中文一键安装器：按当前用户安装、创建桌面/开始菜单入口、检测 WebView2，缺失时通过 Microsoft 官方引导程序安装。
- 发布紫色主题项目首页、四张原创宣传图、使用与构建指南。
- 保留媒体、合并转发、时间筛选、任务管理、鸿蒙字体和已有数据兼容逻辑。
- 发布前完成静态检查、前端构建及两级打包；未执行真实微信导出或安装流程测试。

# Moect 1.1.0 · branding and cards (2026-10-31)

- Rename application/UI/export identities and Windows executable metadata to Moect; use the user-owned GitHub project in the sidebar/About buttons.
- Preserve existing account state/media keys and historical file paths; use the Moect default export folder for new exports.
- Add compact native-style link/article/mini-program, file and location cards with local thumbnails/source icons; add amount/status transfer cards without payment-action credentials.
- Keep static-only post-change verification at the user's request.

# 1.1.0 (2026-10-31)

- Hide duplicate image/emoji attachment filenames; preserve click-to-open media and on-disk originals.
- Parse bounded recordinfo/dataitem forwards with source names, timestamps, nested records and available attachments; create linked offline HTML pages plus complete JSON/TXT copies. Preserve forward details in all supported formats and expand them in the desktop preview.
- Add offline HTML time-range filtering/reset and bounded chunk caching/time indexes.
- Open session previews by row click/keyboard, preserving independent export actions and batch selection.
- Centralize version 1.1.0 for state/export metadata and the About view; update package versions and Windows EXE version resources.
- Static Python/JS/TS checks and builds only after implementation, per the user's request.

# 1.0.1

- Fix `argument 1: OverflowError: int too long to convert` at `OpenProcessToken`: all process/token APIs now use explicit pointer-width signatures and thread-local Windows error handling.
- Keep missing debug privilege as a normal boolean result; ordinary same-user process reads can continue without it.
- Add four native ABI regression tests using only this process and synthetic data.
- Restore DWM native rounded corners/shadow by preserving the native frame capabilities while handling `WM_NCCALCSIZE` for the custom QCE title bar.
- Preserve native edge resizing and the monitor work area when maximized. Windows uses square corners while maximized and rounded corners after restoring.

# 1.0.0

Initial desktop integration of the QCE interface and WeChatMsg 4.x backend.

## 1.0.1 same-version correction (2026-10-31)

- WebView2 per-monitor rendering, embedded HarmonyOS Sans SC, 14px sidebar.
- Supplied Violet Conversation icon and matching purple themes.
- Contact/profile avatars, portable local media, link and mini-program metadata.
- QCE task/overview rows, conversation names, file/folder actions and record deletion.

## 1.0.1 native window and media correction (2026-10-31)

Native WebView2 drag regions and resize gutter; ChatName2Id/MessageResourceInfo joins; PKCS#7 AES and independent XOR; WXGF image decoding, GIF/CDN handling, H.264/AAC normalization and structured replies. Static-only review/build at user request; re-export is required.

## 1.0.1 strict image-key and XOR correction (2026-10-31)

Validate the full AES segment, PKCS#7 and declared plaintext length before accepting cached/scanned keys. Prioritize mutable private memory and share scan time across processes. Recover and validate independent XOR tails; bound WXGF HEVC candidate decoding; validate JPEG pixels and GIF frames. Prefer HD originals, preserve decrypted WXGF with a PNG preview, expose credential-free failure diagnostics and export-stage progress. Static checks/build only; no live or synthetic decryption tests were run.

## 1.0.1 JPEG trailer and emoticon recovery correction (2026-10-31)

Handle valid JPEGs with trailing WeChat cache metadata by walking raster boundaries before full image verification. Support the observed emoticon CDN host, retry failed inherited proxy connections directly, and keep TLS validation. Add same-account emoticon.db metadata, business/emoticon caches and alternate emoji URL fields. Reuse strictly validated CDN AES decoding for local/remote encrypted resources and preserve GIF animation. Add credential-free network diagnostics. Existing failed resources were diagnosed read-only; the changed application receives static checks/build, without an end-to-end export/UI test at the user's request.
