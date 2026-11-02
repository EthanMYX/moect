"""Regression coverage for Windows version virtualization in frozen programs."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.windows_version import require_windows_build, windows_version


class WindowsVersionTests(unittest.TestCase):
    def test_kernel_version_wins_over_manifest_virtualized_build(self):
        reported = SimpleNamespace(build=9200, platform_version=(10, 0, 26100))
        with patch('core.windows_version._rtl_version', return_value=(10, 0, 26300)), \
                patch('core.windows_version.sys.getwindowsversion', return_value=reported, create=True) as fallback:
            self.assertEqual(windows_version(), (10, 0, 26300))
            fallback.assert_not_called()

    def test_platform_version_is_used_when_native_query_is_unavailable(self):
        reported = SimpleNamespace(build=9200, platform_version=(10, 0, 26100))
        with patch('core.windows_version._rtl_version', side_effect=OSError), \
                patch('core.windows_version.sys.getwindowsversion', return_value=reported, create=True):
            self.assertEqual(windows_version(), (10, 0, 26100))

    def test_unknown_version_is_not_mistaken_for_an_old_windows(self):
        with patch('core.windows_version._rtl_version', return_value=(0, 0, 0)), \
                patch('core.windows_version.sys.getwindowsversion', return_value=SimpleNamespace(build=9200), create=True):
            with self.assertRaisesRegex(ValueError, '无法确认'):
                windows_version()

    def test_supported_builds_pass_and_genuinely_older_builds_are_rejected(self):
        with patch('core.windows_version.sys.platform', 'win32'):
            for build in (17763, 19045, 22000, 26100, 26300):
                with self.subTest(build=build), patch('core.windows_version.windows_version', return_value=(10, 0, build)):
                    require_windows_build(17763)
            with patch('core.windows_version.windows_version', return_value=(10, 0, 19045)):
                with self.assertRaisesRegex(ValueError, '26100.*19045'):
                    require_windows_build(26100)


if __name__ == '__main__':
    unittest.main()
