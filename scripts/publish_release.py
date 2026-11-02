"""Publish a prepared Moect release through the official GitHub REST API.

Uses the configured Git credential helper; credentials stay in process memory.
Run after reviewing/committing/pushing the matching source and local packages.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.version import VERSION  # noqa: E402


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--repository',default='mofan6/Moect')
    parser.add_argument('--checksums',type=Path,help='Public checksum file for the two client products only.')
    args=parser.parse_args()
    owner,name=args.repository.split('/')
    paths=[args.directory/f'Moect-{VERSION}-Setup-x64.exe',
        args.directory/f'Moect-{VERSION}-Windows-x64.zip',
        args.checksums or args.directory/'SHA256SUMS.txt']
    if not all(p.is_file() for p in paths):raise SystemExit('Missing prepared release assets.')
    if paths[-1].name!='SHA256SUMS.txt':raise SystemExit('Checksum asset must be named SHA256SUMS.txt.')
    expected_checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[:2]}
    supplied={}
    for line in paths[-1].read_text(encoding='utf-8-sig').splitlines():
        checksum_digest,checksum_name=line.split('  ',1);supplied[checksum_name]=checksum_digest
    if supplied!=expected_checksums:raise SystemExit('Public checksums must match exactly the installer and portable ZIP.')
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0'}
    result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
        text=True,capture_output=True,env=env,check=True)
    credential=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    token=credential.get('password')
    if not token:raise SystemExit('No configured GitHub credential.')
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
        'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Moect-release'}
    def api(method,path,data=None,binary=None,content_type=None):
        url=path if path.startswith('https://uploads.github.com/') else 'https://api.github.com'+path
        body=binary if binary is not None else json.dumps(data).encode() if data is not None else None
        request=Request(url,data=body,method=method,headers={**headers,
            'Content-Type':content_type or 'application/json'})
        with urlopen(request,timeout=180) as response:return json.load(response)
    if api('GET','/user')['login'].casefold()!=owner.casefold():raise SystemExit('Credential owner does not match repository.')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    remote=api('GET',f'/repos/{owner}/{name}/commits/main')['sha']
    if sha!=remote:raise SystemExit('Push the matching source commit first.')
    tag='v'+VERSION
    try:
        reference=api('GET',f'/repos/{owner}/{name}/git/ref/tags/{tag}')['object']
    except HTTPError as exc:
        if exc.code!=404:raise
        reference=api('POST',f'/repos/{owner}/{name}/git/refs',{'ref':'refs/tags/'+tag,'sha':sha})['object']
        if reference['sha']!=sha:raise SystemExit('Version tag creation did not match the source commit.')
    else:
        for _ in range(4):
            if reference['type']=='commit':break
            reference=api('GET',f'/repos/{owner}/{name}/git/tags/{reference["sha"]}')['object']
        if reference['type']!='commit' or reference['sha']!=sha:raise SystemExit('Existing tag points to a different source commit.')
    try:release=api('GET',f'/repos/{owner}/{name}/releases/tags/{tag}')
    except HTTPError as exc:
        if exc.code!=404:raise
        release=api('POST',f'/repos/{owner}/{name}/releases',{'tag_name':tag,'target_commitish':sha,
            'name':'Moect '+VERSION,'body':(ROOT/f'docs/release-{VERSION}.md').read_text(encoding='utf-8'),
            'draft':True,'prerelease':False})
    if not release['draft']:raise SystemExit('This release is already public; refusing to overwrite it.')
    if release['target_commitish'] not in (sha,'main'):raise SystemExit('Existing draft uses a different source commit.')
    if any(a['name'] not in {p.name for p in paths} for a in release.get('assets',[])):
        raise SystemExit('Draft has unrelated assets; refusing to publish them.')
    api('PATCH',f'/repos/{owner}/{name}/releases/{release["id"]}',{
        'tag_name':tag,'target_commitish':sha,'name':'Moect '+VERSION,
        'body':(ROOT/f'docs/release-{VERSION}.md').read_text(encoding='utf-8')})
    print('Draft release ready',flush=True)
    assets={a['name']:a for a in release.get('assets',[])}
    for path in paths:
        with path.open('rb') as stream:digest='sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()
        previous=assets.get(path.name)
        if previous:
            if previous['size']!=path.stat().st_size or previous.get('digest')!=digest:
                raise SystemExit('Existing draft asset differs: '+path.name)
            print('Verified existing asset:',path.name,flush=True);continue
        url=release['upload_url'].split('{',1)[0]+'?name='+quote(path.name)
        asset=api('POST',url,binary=path.read_bytes(),content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        if asset['size']!=path.stat().st_size or asset.get('digest')!=digest:
            raise SystemExit('Uploaded asset verification failed: '+path.name)
        print('Uploaded and verified:',path.name,flush=True)
    public=api('PATCH',f'/repos/{owner}/{name}/releases/{release["id"]}',{
        'tag_name':tag,'target_commitish':sha,'draft':False,'make_latest':'true'})
    if public['draft'] or public['tag_name']!=tag:raise SystemExit('Published release version tag does not match.')
    print(json.dumps({'release':public['html_url'],'draft':public['draft'],'assets':len(paths)}),flush=True)


if __name__=='__main__':main()
