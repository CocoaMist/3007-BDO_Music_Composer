from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from bdo_music_composer.app import windows_recovery


class WindowsRecoveryTests(unittest.TestCase):
    def test_source_launch_does_not_register(self) -> None:
        with patch.object(windows_recovery.sys, "platform", "win32"):
            self.assertFalse(windows_recovery.register_frozen_application_restart())

    def test_frozen_windows_launch_registers_without_user_data(self) -> None:
        kernel = MagicMock()
        kernel.RegisterApplicationRestart.return_value = 0
        ctypes = MagicMock()
        ctypes.windll.kernel32 = kernel
        with (
            patch.object(windows_recovery.sys, "platform", "win32"),
            patch.object(windows_recovery.sys, "frozen", True, create=True),
            patch.dict("sys.modules", {"ctypes": ctypes}),
        ):
            self.assertTrue(windows_recovery.register_frozen_application_restart())
        kernel.RegisterApplicationRestart.assert_called_once_with(None, 12)


if __name__ == "__main__":
    unittest.main()
