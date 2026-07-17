import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class AIInstallerTests(unittest.TestCase):
    def test_powershell_script_is_utf8_bom_for_windows_powershell_51(self):
        raw = (ROOT / "scripts" / "setup_ai.ps1").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8-sig")
        self.assertIn("Write-Piece2STLProgress 100", text)
        self.assertIn("IA locale prête", text)

    def test_gui_installer_uses_a_hidden_process(self):
        source = (ROOT / "piece2stl" / "gui.py").read_text(encoding="utf-8")
        self.assertNotIn("CREATE_NEW_CONSOLE", source)
        process_source = (ROOT / "piece2stl" / "pipeline" / "process.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("CREATE_NO_WINDOW", process_source)
        self.assertIn("STARTF_USESHOWWINDOW", process_source)


if __name__ == "__main__":
    unittest.main()
