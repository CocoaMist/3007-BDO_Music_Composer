from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from bdo_music_composer.core.third_party_credits import (
    BASIC_PITCH_LICENSE_URL,
    BASIC_PITCH_MODEL_URL,
    BASIC_PITCH_NOTICE_URL,
    CREDIT_ENTRIES,
    CREDIT_SECTION_SOURCES,
    RESEARCH_CITATIONS,
)
from bdo_music_composer.core.content_boundary import (
    CONTENT_BOUNDARY_PARAGRAPHS,
    CONTENT_BOUNDARY_TITLE,
)


ROOT = Path(__file__).resolve().parents[1]


class ThirdPartyCreditsTests(unittest.TestCase):
    def test_every_credit_has_a_unique_github_link_and_license_label(self) -> None:
        section_keys = {key for key, _source in CREDIT_SECTION_SOURCES}
        names = [entry.name for entry in CREDIT_ENTRIES]
        self.assertEqual(len(names), len(set(names)))
        for entry in CREDIT_ENTRIES:
            with self.subTest(project=entry.name):
                self.assertIn(entry.section, section_keys)
                self.assertTrue(entry.license_label.strip())
                self.assertTrue(entry.github_url.startswith("https://github.com/"))

    def test_direct_runtime_and_build_foundations_are_acknowledged(self) -> None:
        names = {entry.name for entry in CREDIT_ENTRIES}
        required = {
            "Spotify Basic Pitch 0.4.0 + nmp.onnx",
            "Microsoft ONNX Runtime",
            "librosa",
            "SoundFile",
            "libsndfile",
            "python-soxr",
            "libsoxr",
            "NumPy",
            "SciPy",
            "scikit-learn",
            "mir_eval",
            "pretty_midi",
            "resampy",
            "CPython",
            "PySide6 / Qt",
            "Mido",
            "Pillow",
            "PyInstaller",
            "Setuptools",
            "typing_extensions",
        }
        self.assertTrue(required.issubset(names), required - names)

    def test_basic_pitch_model_license_and_citation_evidence_is_locked(self) -> None:
        basic_pitch = next(
            entry for entry in CREDIT_ENTRIES
            if entry.name.startswith("Spotify Basic Pitch")
        )
        self.assertEqual(basic_pitch.license_label, "Apache-2.0")
        for url in (
            basic_pitch.github_url,
            BASIC_PITCH_MODEL_URL,
            BASIC_PITCH_LICENSE_URL,
            BASIC_PITCH_NOTICE_URL,
        ):
            self.assertTrue(url.startswith("https://github.com/spotify/basic-pitch"))
        citation = RESEARCH_CITATIONS[0]
        self.assertEqual(citation.name, "Basic Pitch")
        self.assertIn("Bittner", citation.citation)
        self.assertIn("ICASSP 2022", citation.citation)
        self.assertEqual(citation.github_url, basic_pitch.github_url)

    def test_notices_contain_every_curated_github_link(self) -> None:
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for entry in CREDIT_ENTRIES:
            with self.subTest(project=entry.name):
                self.assertIn(entry.github_url, notices)
        for url in (
            BASIC_PITCH_MODEL_URL,
            BASIC_PITCH_LICENSE_URL,
            BASIC_PITCH_NOTICE_URL,
        ):
            self.assertIn(url, notices)

    def test_offscreen_credits_dialog_exposes_clickable_links(self) -> None:
        script = textwrap.dedent(
            """
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser
            from bdo_music_composer.ui.main_window import MidiToBdoWindow
            from bdo_music_composer.core.third_party_credits import CREDIT_ENTRIES
            from bdo_music_composer.core.content_boundary import (
                CONTENT_BOUNDARY_PARAGRAPHS,
                CONTENT_BOUNDARY_TITLE,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            with patch.object(QDialog, "exec", return_value=0):
                window._show_acknowledgements()
            dialog = window.findChild(QDialog, "ThanksDialog")
            assert dialog is not None
            browser = dialog.findChild(QTextBrowser, "ThanksText")
            assert browser is not None
            assert browser.openExternalLinks()
            html = browser.toHtml()
            for entry in CREDIT_ENTRIES:
                assert entry.github_url in html, entry.github_url
            assert "arxiv.org/abs/2203.09893" in html
            assert CONTENT_BOUNDARY_TITLE in browser.toPlainText()
            for paragraph in CONTENT_BOUNDARY_PARAGRAPHS:
                assert paragraph in browser.toPlainText()
            dialog.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        with tempfile.TemporaryDirectory() as user_data:
            env["BDO_USER_DATA_DIR"] = user_data
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=45,
            )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
