import sys
import time
import unittest

from piece2stl.pipeline.process import CancellationError, hidden_process_kwargs, run_command


class ProcessTests(unittest.TestCase):
    def test_windows_children_are_forced_hidden(self):
        options = hidden_process_kwargs()
        if sys.platform == "win32":
            self.assertTrue(options["creationflags"] & 0x08000000)
            self.assertIsNotNone(options["startupinfo"])
        else:
            self.assertEqual(options, {})

    def test_command_output_is_forwarded(self):
        lines = []
        run_command(
            [sys.executable, "-c", "print('piece2stl-ok')"],
            log=lines.append,
        )
        self.assertTrue(any("piece2stl-ok" in line for line in lines))

    def test_windows_child_has_no_console_window(self):
        if sys.platform != "win32":
            self.skipTest("Contrôle spécifique à Windows")
        lines = []
        run_command(
            [
                sys.executable,
                "-c",
                "import ctypes; print('CONSOLE=' + str(ctypes.windll.kernel32.GetConsoleWindow()))",
            ],
            log=lines.append,
        )
        self.assertIn("CONSOLE=0", lines)

    def test_silent_command_can_be_cancelled(self):
        started = time.monotonic()
        with self.assertRaises(CancellationError):
            run_command(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                log=lambda _line: None,
                cancel=lambda: time.monotonic() - started > 0.2,
            )
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
