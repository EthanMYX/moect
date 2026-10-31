"""Fictional, self-contained demo. Never opens WeChat data."""
from datetime import datetime, timezone, timedelta

SESSIONS = [
    ('demo_design@chatroom', '周末出走计划', '群聊', '照片收到了，这次的日落真的很美。', '山'),
    ('demo_lin', '林间', '私聊', '好，那我们周六上午见。', '林'),
    ('demo_designers@chatroom', '小小设计工作室', '群聊', '新版本的页面已整理好，明天一起看。', '设'),
    ('demo_family@chatroom', '一家人', '群聊', '到家记得说一声，晚饭给你留着。', '家'),
    ('demo_chen', '陈一', '私聊', '那个书单我发给你啦。', '陈'),
    ('demo_books@chatroom', '读点好书', '群聊', '下个月一起读《看不见的城市》。', '书'),
    ('demo_file', '文件传输助手', '私聊', '旅行清单.pdf', '文'),
]


class DemoArchive:
    def __init__(self, library=None):
        self.library = library

    def close(self):
        pass

    def sessions(self):
        base = int(datetime(2026, 10, 30, 15, 30).timestamp())
        return [dict(username=u, display=n, summary=s, is_group=u.endswith('@chatroom'),
                     last_time=base-i*2700, sort_time=base-i*2700, has_messages=True,
                     unread=0, initial=a) for i, (u, n, t, s, a) in enumerate(SESSIONS)]

    def messages(self, session, options=None, descending=False, before=None, cancel=None):
        options = options or {}
        base = int(datetime(2026, 10, 30, 10, 10).timestamp())
        text = [
            ('林间', '周末的天气看起来不错，去山里走走吧？', False),
            ('我', '好呀！上次收藏的那条路线正好可以安排上。', True),
            ('陈一', '我整理了一份行程，走到观景台大概两小时，不会太累。', False),
            ('林间', '那就慢慢走，沿路找一家小店吃午饭。', False),
            ('我', '带上相机和热咖啡。\n最近很想把这些小小的日常好好留下来。', True),
            ('陈一', '日程已经记下啦，周六 9:00 在地铁站集合。', False),
            ('林间', '[图片] 山顶的日落', False),
            ('我', '这张光线真好，下次我们也等到日落再回来。', True),
            ('陈一', '照片收到了，这次的日落真的很美。', False),
        ]
        rows = []
        for i, (sender, content, me) in enumerate(text):
            ts = base + i * 240
            kind = 'image' if i == 6 else 'text'
            key = [ts, 0, i+1]
            if before and key >= before: continue
            if options.get('start') is not None and ts < options['start']: continue
            if options.get('end') is not None and ts > options['end']: continue
            if options.get('kind', 'all') not in ('all', kind): continue
            if options.get('query', '').casefold() not in (sender+' '+content).casefold(): continue
            rows.append(dict(local_id=i+1, server_id=str(i+1), shard=0, type=3 if kind=='image' else 1,
                             type_name='图片' if kind=='image' else '文本', create_time=ts,
                             time_str=datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'),
                             sender=sender, sender_wxid='demo_me' if me else 'demo_friend',
                             is_sender=me, text=content, content=content, kind=kind, extra={},
                             session=session, _cursor=key))
        for msg in reversed(rows) if descending else rows:
            if cancel: cancel()
            yield msg

    def page(self, session, options=None, before=None, limit=60):
        rows = list(self.messages(session, options, descending=True, before=before))
        page = rows[:limit]
        return dict(messages=list(reversed(page)), more=len(rows)>limit,
                    cursor=page[-1]['_cursor'] if page else None)
