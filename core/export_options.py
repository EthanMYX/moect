"""Validated export preferences shared by the bridge and media pipeline."""
RESOURCE_TYPES=('image','video','audio','file')


def export_preferences(payload):
    def boolean(snake,camel,default):
        value=payload.get(snake,payload.get(camel,default))
        if not isinstance(value,bool):raise ValueError('导出开关必须为布尔值：'+camel)
        return value
    quick=boolean('quick_export','quickExport',False)
    types=payload.get('skip_resource_types',payload.get('skipDownloadResourceTypes',[]))
    if not isinstance(types,(list,tuple)) or any(not isinstance(t,str) or t not in RESOURCE_TYPES for t in types):
        raise ValueError('跳过的资源类型只支持 image、video、audio、file')
    return {'include_system_messages':boolean('include_system_messages','includeSystemMessages',True),
            'include_avatars':boolean('include_avatars','includeAvatars',True) and not quick,
            'quick_export':quick,
            'skip_resource_types':[t for t in RESOURCE_TYPES if quick or t in types]}


def is_system_message(msg):
    return msg.get('kind')=='system' or msg.get('type') in (10000,10002)
