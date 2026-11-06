"""Moect storage, with compatibility for an existing pre-rename installation."""
import os
import stat
import tempfile
from pathlib import Path


def is_link(path):
    """Include Windows junctions and other reparse points in link checks."""
    path = Path(path)
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0)
                                        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
    except OSError:
        return True


def app_data_root():
    local=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))
    current=local/'Moect'
    legacy=local/'WeChatExporter'
    if (current/'config.json').is_file():return current
    if (legacy/'config.json').is_file():return legacy
    return current
