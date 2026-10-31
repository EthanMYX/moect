"""Native ABI regressions, using only this Python process and synthetic data."""
import ctypes
import ctypes.wintypes as wt
import os
import tempfile
import unittest
from unittest.mock import patch
from wx4 import key


class WindowsInteropTests(unittest.TestCase):
    def test_debug_privilege_accepts_64_bit_pseudo_handle(self):
        handle=key.kernel32.GetCurrentProcess()
        self.assertEqual(handle,ctypes.c_void_p(-1).value)
        # Before 1.0.1 this exact real API call raised argument-1 OverflowError.
        # A regular non-admin token may legitimately return False.
        for _ in range(3):
            self.assertIsInstance(key.enable_debug_privilege(),bool)

    def test_token_open_and_close_real_api(self):
        token=wt.HANDLE()
        self.assertTrue(key.advapi32.OpenProcessToken(key.kernel32.GetCurrentProcess(),0x0008,ctypes.byref(token)))
        self.assertTrue(token.value)
        self.assertTrue(key.kernel32.CloseHandle(token))

    def test_read_own_high_address_and_query_regions(self):
        buffer=ctypes.create_string_buffer(b'fixture-memory-only')
        address=ctypes.addressof(buffer)
        self.assertGreater(address,0xffffffff)
        handle=key._open(os.getpid())
        self.assertTrue(handle)
        try:
            self.assertEqual(key._read(handle,address,len(buffer)),buffer.raw)
            self.assertTrue(any(base<=address<base+size for base,size in key._regions(handle)))
        finally:key.kernel32.CloseHandle(handle)

    def test_extraction_reaches_scanner_after_real_privilege_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            extractor=key.KeyExtractor(directory)
            def collect():extractor.salt_index={'fixture':[]}
            def scan(pid):
                self.assertEqual(pid,os.getpid())
                extractor.keys['fixture']='synthetic-key'
                return {'hit':1,'candidates':1}
            with patch.object(extractor,'collect',side_effect=collect), \
                 patch.object(extractor,'scan_process',side_effect=scan) as scanner, \
                 patch.object(key,'find_weixin_processes',return_value=[{'pid':os.getpid(),'mem_kb':1}]):
                self.assertEqual(extractor.extract(),{'fixture':'synthetic-key'})
                scanner.assert_called_once()


if __name__=='__main__':unittest.main()
