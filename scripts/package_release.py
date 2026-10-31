"""Package the built runtime and Git-tracked corresponding source only."""
import hashlib
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.version import VERSION  # noqa: E402

PORTABLE_EXCLUDED={'使用说明.md','修复说明.md'}

def main():
    output=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'release'
    output.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'dist/Moect'
    if not (runtime/'Moect.exe').is_file():raise SystemExit('Build the runtime first.')
    installer=output/f'Moect-{VERSION}-Setup-x64.exe'
    if not installer.is_file():raise SystemExit('Build the installer first.')
    portable=output/f'Moect-{VERSION}-Windows-x64.zip'
    with ZipFile(portable,'w',ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(runtime.rglob('*')):
            if path.is_file() and path.name not in PORTABLE_EXCLUDED:
                archive.write(path,'Moect/'+path.relative_to(runtime).as_posix())
        for source,target in [('LICENSE','LICENSE'),('THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md')]:
            archive.write(ROOT/source,'Moect/'+target)
    source=output/f'Moect-{VERSION}-Source.zip'
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
    with ZipFile(source,'w',ZIP_DEFLATED,compresslevel=6) as archive:
        for filename in sorted(filter(None,files)):
            path=ROOT/filename
            if path.is_file():archive.write(path,'Moect-Source/'+filename)
    packages=[installer,portable,source]
    checksums=[]
    for path in packages:
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        checksums.append(digest+'  '+path.name)
        print(path.name,path.stat().st_size,flush=True)
    (output/'SHA256SUMS.txt').write_text('\n'.join(checksums)+'\n',encoding='utf-8')


if __name__=='__main__':main()
