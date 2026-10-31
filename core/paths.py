"""Moect storage, with compatibility for an existing pre-rename installation."""
import os
import tempfile
from pathlib import Path


def app_data_root():
    local=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))
    current=local/'Moect'
    legacy=local/'WeChatExporter'
    if (current/'config.json').is_file():return current
    if (legacy/'config.json').is_file():return legacy
    return current
