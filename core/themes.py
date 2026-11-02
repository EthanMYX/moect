"""Persisted accent palettes shared by the web page and native resize gutter."""
ACCENTS = (
    ('violet','鸢尾紫','#7056c4','#cdbbff'),
    ('blue','晴空蓝','#3565b5','#aac7ff'),
    ('cyan','青瓷青','#006a78','#80d5e4'),
    ('green','松叶绿','#386b45','#9fd6a8'),
    ('orange','暖杏橙','#985018','#ffb781'),
    ('rose','蔷薇粉','#9c426b','#ffb0d1'),
    ('red','朱砂红','#ac3942','#ffb3b7'),
    ('slate','雾山灰','#52636c','#b6cbd7'),
)
ACCENT_IDS = {item[0] for item in ACCENTS}


def mix(a,b,weight):
    left=bytes.fromhex(a.lstrip('#'));right=bytes.fromhex(b.lstrip('#'))
    return '#'+''.join(f'{round(x*(1-weight)+y*weight):02x}' for x,y in zip(left,right))


def palette(mode,accent):
    item=next((row for row in ACCENTS if row[0]==accent),ACCENTS[0])
    if item[0]=='violet':
        # Preserve the accepted default appearance exactly.
        colors=(['#f7f5fb','#1d1b20','#fffbff','#fffbff','#7056c4','#ffffff','#eee8f7','#4b3a76','#f0ecf5','#625b71','#eae2f8','#4b3aa2','#e6deef','#8b76f5','#f1ecf8'] if mode!='dark' else
                ['#141218','#e9e0ef','#1e1a25','#282230','#cdbbff','#382469','#352c46','#e4d8f7','#2b2534','#b7adc5','#3c3052','#e5d8ff','#3b3247','#bda6ff','#141218'])
    elif mode=='dark':
        primary=item[3];base=mix('#101114',item[2],.06);fg=mix('#eeeeef',primary,.12)
        colors=[base,fg,mix(base,primary,.05),mix(base,primary,.10),primary,mix('#111114',item[2],.30),mix(base,primary,.13),fg,mix(base,primary,.08),mix('#a8a7ac',primary,.14),mix(base,primary,.18),fg,mix(base,primary,.20),primary,base]
    else:
        primary=item[2];fg=mix('#1d1b20',primary,.10)
        colors=[mix('#ffffff',primary,.045),fg,mix('#ffffff',primary,.009),mix('#ffffff',primary,.009),primary,'#ffffff',mix('#ffffff',primary,.10),mix('#29232d',primary,.35),mix('#ffffff',primary,.065),mix('#625e68',primary,.10),mix('#ffffff',primary,.13),primary,mix('#ffffff',primary,.17),mix(primary,'#ffffff',.15),mix('#ffffff',primary,.07)]
    names=('background','foreground','card','popover','primary','primary-foreground','secondary','secondary-foreground','muted','muted-foreground','accent','accent-foreground','border','ring','sidebar')
    result=dict(zip(names,colors))
    result.update({'card-foreground':result['foreground'],'popover-foreground':result['foreground'],'input':result['border'],
                   'sidebar-foreground':result['foreground'],'sidebar-primary':result['primary'],'sidebar-primary-foreground':result['primary-foreground'],
                   'sidebar-accent':result['accent'],'sidebar-accent-foreground':result['accent-foreground'],'sidebar-border':result['border'],'sidebar-ring':result['ring']})
    return result


def accent_choices():return [{'id':i,'name':name,'color':light} for i,name,light,dark in ACCENTS]


def archive_theme(value=None):
    value=value if isinstance(value,dict) else {}
    return {'mode':'dark' if value.get('mode')=='dark' else 'light',
            'accent':value.get('accent') if isinstance(value.get('accent'),str) and value['accent'] in ACCENT_IDS else 'violet'}


def theme_archive(template,theme=None):
    """Color CSS only; message text, SVG payloads and transfer status keep intact."""
    import re
    theme=archive_theme(theme);colors=palette(theme['mode'],theme['accent'])
    groups={
        'background':('f7f5fb',),
        'foreground':('292137','292b31'),
        'card':('ffffff','fff','fcfaff'),
        'muted':('f4f1f7','f5f1fb','f1eff5','f0eafa'),
        'secondary':('e8dff8','eee8f7','f0ecf5'),
        'accent':('e9defd',),
        'primary':('7056c4','7056a0','705c8d','725c90'),
        'ring':('a48bd9','bca8dc','aa8fdf'),
        'muted-foreground':('7e718f','897a99','887a98','82718e','76608c','96939e','8b8b94','96711b','978aab','9b91a8','78668d','746387','66537e','7a5cb0'),
        'border':('e4dcef','e3daef','e5ddef','e2d8ee','dedde3','d9cde6','e6deef','dfd5ed','e6dfed','e2d8ee'),
    }
    roles={value:role for role,values in groups.items() for value in values}
    def color(match):
        value=match.group()[1:].lower();alpha=None
        if len(value) in (4,8):alpha=int(value[-1]*2 if len(value)==4 else value[-2:],16)/255;value=value[:-1] if len(value)==4 else value[:-2]
        role=roles.get(value)
        if not role:return match.group()
        variable='var(--'+role+')'
        return variable if alpha is None else 'color-mix(in srgb,'+variable+' '+str(round(alpha*100,3))+'%,transparent)'
    def style(match):
        css=re.sub(r'#[a-fA-F0-9]{8}\b|#[a-fA-F0-9]{6}\b|#[a-fA-F0-9]{4}\b|#[a-fA-F0-9]{3}\b',color,match.group(2))
        css=re.sub(r'((?:background|background-color)\s*:\s*)white\b',r'\1var(--card)',css,flags=re.I)
        css=re.sub(r'(\bcolor\s*:\s*)white\b',r'\1var(--primary-foreground)',css,flags=re.I)
        variables=':root{color-scheme:'+theme['mode']+';'+''.join('--'+k+':'+v+';' for k,v in colors.items())+'--moect-backdrop:rgba(0,0,0,'+('.5' if theme['mode']=='dark' else '.25')+')}*{scrollbar-color:var(--primary) var(--background)}'
        return match.group(1)+variables+css+match.group(3)
    return re.sub(r'(<style\b[^>]*>)(.*?)(</style>)',style,template,flags=re.S|re.I)
