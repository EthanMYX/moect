# 账号资源导出

左侧提供“表情包”和“朋友圈”，任务记录、取消、删除记录、打开目录和打开导出文件沿用原有任务机制。

## 表情包

从当前账号的 `emoticon/emoticon.db` 读取收藏顺序、自定义表情及商店专辑，支持批量选择分类。收藏依据 `kFavEmoticonOrderTable` / `kCustomEmoticonOrderTable`，不会把所有用过的聊天表情误认为收藏。专辑依据 `kStoreEmoticonPackageTable`、`kStoreEmoticonFilesTable`、`kStoreEmoticonCaptionsTable`，已移除的专辑不混入当前分类。

本地文件优先，按需使用表情元数据的 CDN 与 AES 参数。商店整包根据专辑 ID 的 MD5 找到 `PersistStore` / `ThumbStore`，解密后按数据库偏移取成员。账号缓存采用独立 AES-CBC 材料，与聊天图片 DAT 密钥不同；需要时只对本机 Weixin.exe 做有时间上限的读取，命中材料保存在本机私有应用缓存。GIF/WebP 保持动画，WXGF 的 HEVC 帧转换为 GIF。缩略图会明确标记，未恢复项保留在资源明细中，不冒充原图。

“缓存所选表情资源”会主动尝试下载收藏/专辑元数据里仍有效的已知下载地址，结果可在随后导出时复用；无法凭空恢复未开放地址或已失效的商店资源。

导出目录包含按分类命名的子文件夹、离线索引页、`data.json` 和资源明细。不会导出账号密钥、候选种子、认证字段或原始数据库。

## 朋友圈范围与时间筛选

朋友圈媒体的独立 ISAAC-64 加密在本地处理：图片按完整密钥流解码，视频只处理前 128 KiB，随后校验媒体格式并转为可播放 MP4。密钥流使用 Bob Jenkins 的公共领域标准算法，跨 2048 字节会正常换块；URL 的鉴权 token、媒体 key 仅用于本机读取，不写入 HTML、JSON 或资源明细。带 key 的媒体未通过格式校验时不会被标成可用。

从 `sns/sns.db` 的 `SnsTimeLine` 读取，可选“我的朋友圈”“公共朋友圈”“指定账号”三种范围。本人和指定账号按 UID 参数化筛选；公共范围读取当前账号可读取的本机缓存。XML 作者与数据库作者不一致的记录不会混入。指定账号支持 UID、微信号或可唯一匹配的昵称，重名时需要选择具体 UID；无效范围不会自动变成全部动态。支持正文、作者、时间、图片、视频和分享链接；视频默认随归档导出，可取消以节省空间。

三个范围打开后都直接读取本地缓存，可立即预览或导出，不强制选择日期。日期仅作为可选筛选条件，留空导出全部缓存；仍支持按北京时间精确到分钟筛选。用户在微信手动浏览、打开图片或视频后，点击右上角“刷新资源快照”，即可整理最新 SNS/表情数据库并更新预览。

朋友圈没有 UI 自动化、鼠标/键盘模拟、自动翻页或主动下载功能，也不调用远端历史接口。预览只从本地缓存及既有 Moect 缓存读取，最多生成 12 条缩略图；图片索引和预览有时间/大小预算，避免拖慢页面。导出图片、视频及评论附件也只使用本地可还原资源。缓存缺失时明确记录状态，不会为了获取内容接管微信操作。

公共缓存可能包括浏览账号主页时留下的记录，数据库不能可靠区分它们与主时间线来源。微信权限、历史可见范围和本机缓存清理可能使归档不完整。

从朋友圈 XML 的 `like_user_list`、`comment_user_list` 及可解析的 `pack_info_buf` 中提取互动，不猜测 `SnsMessage` 数字类型。保留 UID、昵称、头像、回复关系和评论时间；删除标记会排除，同一评论 ID 去重，64 位 ID 优先，0 不作为唯一 ID。评论的已知图片/表情也经过现有媒体管线。HTML 使用三列方形图片网格，单图保留自然比例；点赞与评论分别可收起，点击点赞头像显示姓名。无头像原文件时显示昵称首字。

软件与两种离线 HTML 共用 `ui/date-range-picker.js`。年/月下拉与日历选择日期，小时/分钟完整显示，应用并确定后才提交；取消不改条件。按北京时间处理，开始分钟从 00 秒起，结束分钟包含 59 秒。HTML 的时间筛选只作用于本次已导出的数据，不能读取归档之外的历史。

退出登录会取消尚未完成的资源刷新；过期任务不得把旧账号写回。已开始的导出持有独立快照，退出登录不会清空其任务记录或已完成文件。

## 查阅的开源案例与格式资料

- [Bob Jenkins ISAAC-64 原始算法](https://burtleburtle.net/bob/c/isaac64.c)：公共领域，`core/sns_codec.py` 依据标准算法实现，并通过固定输出向量校验。

- [CN-Grace/Wechat-Emoticon-Parser，v4.0-plus](https://github.com/CN-Grace/Wechat-Emoticon-Parser/tree/v4.0-plus)：Windows 4.x 账号表情缓存 AES 派生、整包格式，MIT。
- [Rikkkum/wx_emoji_windows](https://github.com/Rikkkum/wx_emoji_windows)：收藏顺序表和下载元数据。
- [liusheng22/export-wechat-emoji](https://github.com/liusheng22/export-wechat-emoji)：专辑元数据、整包偏移与质量状态的交叉参考。
- [bojieli/greenbubbles 数据库格式](https://github.com/bojieli/greenbubbles/blob/main/docs/WECHAT_DATABASE_FORMAT.md)：`SnsTimeLine` 字段与缓存范围。
- [sgaofen/murmur 的 SNS 读取模块](https://github.com/sgaofen/murmur/blob/main/cli/sns.py)：TimelineObject XML 字段交叉参考。
- [WeFlow 朋友圈服务](https://github.com/hicccc77/WeFlow/blob/main/electron/services/snsService.ts)：研究功能与可行性，未引入其代码或原生组件。

实现位于 `core/account_assets.py`、`core/sticker_cache.py`、`core/account_exporting.py`。新代码在本项目中实现，没有安装外部数据上传服务。
