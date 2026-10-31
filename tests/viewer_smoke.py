"""Load a synthetic HTML export from file://, including its local chunks."""
import json
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from core.data import Archive
from core.exporting import export_session
from tests.test_core import fixture


def main():
    app=QApplication([])
    tmp=tempfile.TemporaryDirectory()
    root=Path(tmp.name)
    archive=Archive(fixture(root/'db'))
    out=root/'out';out.mkdir()
    result=export_session(archive,archive.sessions()[0],{'format':'html'},out,Path(__file__).parent.parent/'ui',lambda n:None,lambda:None)
    archive.close()
    view=QWebEngineView();view.resize(1000,800);view.show()
    view.load(QUrl.fromLocalFile(result['path']))
    steps=[("document.querySelectorAll('.row').length===80",None),
           ("document.querySelector('#next').click();true",None),
           ("document.querySelector('#page').textContent.startsWith('2 /')",None),
           ("document.querySelector('#search').value='特殊字符';document.querySelector('#go').click();true",None),
           ("document.querySelectorAll('.row').length===1 && document.querySelector('.bubble').textContent.includes('<script>')",None)]
    index=0;attempts=0
    def tick():
        nonlocal index,attempts
        if index==len(steps):
            print('Offline HTML chunks, pagination, search and escaped text passed',flush=True);app.exit(0);return
        def check(value):
            nonlocal index,attempts
            if value:index+=1;attempts=0
            else:attempts+=1
            if attempts>30:
                print('Offline viewer failed at step',index,flush=True);app.exit(1)
            else:QTimer.singleShot(250,tick)
        view.page().runJavaScript(steps[index][0],check)
    QTimer.singleShot(1500,tick)
    result=app.exec();view.close();view.deleteLater()
    return result


if __name__=='__main__':sys.exit(main())
