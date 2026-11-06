"""Offline checks of the actual frozen dependencies, using temporary synthetic files."""
import json
import math
import struct
import tempfile
import wave
from pathlib import Path

from .version import VERSION


def run(report):
    result = {'version': VERSION, 'checks': {}}
    try:
        import clr
        clr.AddReference('System.Windows.Forms')
        result['checks']['netfx'] = True
        from .archive_packaging import export_options, update_options, package_folder
        import pyzipper
        import pysilk
        from .excel_export import write_excel
        from .media_codec import MediaCodec
        from .windows_version import windows_version
        result['windows'] = list(windows_version())
        with tempfile.TemporaryDirectory(prefix='moect-frozen-check-') as temporary:
            root = Path(temporary)
            source = root/'中文归档';source.mkdir()
            (source/'聊天.html').write_text('<p>Synthetic offline record</p>', encoding='utf-8')
            saved = update_options({}, {'zip': True, 'encrypt': True, 'password': 'Synthetic 密码'})
            _, password = export_options(json.loads(json.dumps(saved)), {})
            result['checks']['dpapi'] = password.decode() == 'Synthetic 密码'
            package_folder(source, root/'encrypted.zip', password, lambda: None, lambda _: None)
            with pyzipper.AESZipFile(root/'encrypted.zip') as archive:
                archive.setpassword(password)
                result['checks']['aes_zip'] = b'Synthetic' in archive.read('聊天.html')
            path = root/'records.xlsx'
            count = write_excel(path, iter([{'time_str':'2026-11-06','text':'=1+1','server_id':'326543963595411110'}]),
                                'Synthetic', lambda message: (message['text'], ''), lambda _: None, lambda: None)
            result['checks']['excel'] = count == 1 and path.stat().st_size > 0
            samples = [int(7000 * math.sin(2 * math.pi * 440 * i/24000)) for i in range(480)]
            silk = pysilk.encode(struct.pack('<480h', *samples), sample_rate=24000)
            audio = MediaCodec(lambda: None).audio(silk, root/'voice.wav')
            with wave.open(str(audio), 'rb') as stream:
                result['checks']['silk_wav'] = stream.getnframes() == 480
        result['ok'] = all(result['checks'].values())
    except Exception as error:
        result.update(ok=False, error=type(error).__name__ + ': ' + str(error))
    report = Path(report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
