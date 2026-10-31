"""Python adaptation of QCE's bounded buffered writer and batch source design.

Based on shuakami/qq-chat-exporter, qq-chat-export-core/src/stream_utils.rs
and text_exporter.rs (GPL-3.0). See THIRD_PARTY_NOTICES.md.
"""
import os
from pathlib import Path

DEFAULT_FLUSH_THRESHOLD = 1024 * 1024


class BufferedTextWriter:
    def __init__(self, path, threshold=DEFAULT_FLUSH_THRESHOLD, encoding='utf-8'):
        self.path = Path(path)
        self.file = open(self.path, 'w', encoding=encoding, newline='')
        self.parts = []
        self.size = 0
        self.threshold = threshold
        self.bytes_written = 0

    def write(self, text):
        if not text:
            return
        self.parts.append(text)
        self.size += len(text.encode('utf-8'))
        if self.size >= self.threshold:
            self.flush()

    def flush(self):
        if self.parts:
            self.file.write(''.join(self.parts))
            self.bytes_written += self.size
            self.parts.clear()
            self.size = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if not exc_type:
                self.flush()
                self.file.flush()
                os.fsync(self.file.fileno())
        finally:
            self.file.close()

