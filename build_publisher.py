"""Build the private author console independently; never collect author credentials."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from PyInstaller.utils.win32.versioninfo import VSVersionInfo,FixedFileInfo,StringFileInfo,StringTable,StringStruct,VarFileInfo,VarStruct
from core.version import VERSION


def main():
    root=Path(__file__).resolve().parent
    ui=root/'ui-publisher'
    if not (ui/'publisher.html').is_file():raise SystemExit('Build frontend/vite.publisher.config.ts first.')
    shutil.copy2(root/'ui/icon.svg',ui/'icon.svg');shutil.copy2(root/'icon.ico',ui/'icon.ico')
    support=root/'build-support/publisher';support.mkdir(parents=True,exist_ok=True)
    version=support/'publisher-version.txt'
    info=VSVersionInfo(ffi=FixedFileInfo(filevers=(1,0,0,0),prodvers=(1,0,0,0),mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[
        StringFileInfo([StringTable('080404b0',[
            StringStruct('FileDescription','Moect 发布中心'),StringStruct('ProductName','Moect 发布中心'),
            StringStruct('FileVersion','1.0.0'),StringStruct('ProductVersion','1.0.0'),
            StringStruct('InternalName','MoectPublisher'),StringStruct('OriginalFilename','Moect发布中心.exe')])]),
        VarFileInfo([VarStruct('Translation',[0x0804,1200])])])
    version.write_text(str(info),encoding='utf-8')
    output=root.parents[1]/'outputs'/VERSION
    output.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();windows=Path(env.get('SystemRoot',r'C:\Windows'))
    env['PATH']=os.pathsep.join([str(Path(sys.executable).parent),str(Path(sys.base_prefix)),str(windows/'System32'),str(windows)])
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onefile','--name','Moect发布中心',
        '--icon',str(root/'icon.ico'),'--manifest',str(root/'windows.manifest'),'--version-file',str(version),
        '--distpath',str(output),'--workpath',str(support/'build'),'--specpath',str(support),
        '--add-data',str(ui)+';ui-publisher','--add-data',str(root/'ui/online-config.json')+';ui',
        '--add-data',str(root/'LICENSE')+';.',
        '--add-data',str(root/'THIRD_PARTY_NOTICES.md')+';.',
        '--add-data',str(root/'THIRD_PARTY_LICENSES')+';THIRD_PARTY_LICENSES',
        '--exclude-module','PySide6','--exclude-module','PyQt5','--exclude-module','PyQt6','--exclude-module','tkinter',
        '--exclude-module','wx4','--exclude-module','core.service',
        '--collect-all','webview','--collect-all','pythonnet','--collect-all','clr_loader',
        '--hidden-import','webview.platforms.edgechromium','--hidden-import','webview.platforms.winforms',str(root/'publisher_app.py')]
    subprocess.run(command,cwd=root,env=env,check=True)
    print(str(output/'Moect发布中心.exe'))


if __name__=='__main__':main()
