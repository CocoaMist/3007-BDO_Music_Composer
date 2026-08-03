#!/usr/bin/env python3
"""BDO Music Composer application entry point.

Run without arguments to open the PySide6 desktop editor. Arguments retain
the command-line conversion entry point, for example::

    python main.py samples/test_chord.mid test_song
"""

import sys


TRANSCRIPTION_SELF_TEST_ARGUMENT = "--self-test-transcription"
STARTUP_SELF_TEST_ARGUMENT = "--self-test-startup"
STARTUP_SELF_TEST_DURATION_MS = 10_500
STARTUP_SELF_TEST_ENVIRONMENT = "BDO_STARTUP_SELF_TEST"


def _self_test_transcription() -> int:
    """Exercise the packaged ONNX transcription path without user audio."""

    from pathlib import Path

    import numpy as np

    from bdo_music_composer.transcription.bdo_transcription import _onnx_model, transcription_backend_status

    available, message = transcription_backend_status()
    if not available:
        raise RuntimeError(message or "transcription backend status failed")

    import basic_pitch
    import basic_pitch.inference as inference
    import onnxruntime
    import soundfile
    import soxr

    providers = set(onnxruntime.get_available_providers())
    if "CPUExecutionProvider" not in providers:
        raise RuntimeError("ONNX Runtime CPUExecutionProvider is unavailable")

    model_path = Path(
        basic_pitch.build_icassp_2022_model_path(
            basic_pitch.FilenameSuffix.onnx
        )
    )
    if not model_path.is_file():
        raise RuntimeError("Basic Pitch ONNX model is missing")
    if not soundfile.available_formats():
        raise RuntimeError("SoundFile has no available audio formats")
    if not callable(soxr.ResampleStream):
        raise RuntimeError("soxr streaming resampler is unavailable")

    model = _onnx_model(basic_pitch, inference, onnxruntime)
    session_providers = set(model.model.get_providers())
    if "CPUExecutionProvider" not in session_providers:
        raise RuntimeError("Basic Pitch model did not load with the CPU provider")

    probe = np.zeros(
        (1, int(inference.AUDIO_N_SAMPLES), 1),
        dtype=np.float32,
    )
    prediction = model.predict(probe)
    expected_bins = {
        "note": 88,
        "onset": 88,
        "contour": 264,
    }
    for name, bins in expected_bins.items():
        value = np.asarray(prediction.get(name))
        if (
            value.ndim != 3
            or value.shape[0] != 1
            or value.shape[1] <= 0
            or value.shape[2] != bins
            or not bool(np.isfinite(value).all())
        ):
            raise RuntimeError(
                f"Basic Pitch returned invalid {name} evidence"
            )

    print("Transcription self-test passed (Basic Pitch ONNX / CPU).")
    return 0


def _run_startup_self_test_gui() -> int:
    """Run the GUI lifetime probe inside an already isolated environment."""

    import time

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from bdo_music_composer.ui.main_window import MidiToBdoWindow

    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = MidiToBdoWindow()
    started = time.monotonic()
    window.show()
    QTimer.singleShot(STARTUP_SELF_TEST_DURATION_MS, application.quit)
    exit_code = int(application.exec())
    elapsed = time.monotonic() - started
    window.close()
    if exit_code:
        raise RuntimeError(
            f"GUI startup self-test exited with code {exit_code}"
        )
    if elapsed < 10.0:
        raise RuntimeError(
            f"GUI startup self-test ended too early ({elapsed:.3f}s)"
        )
    print(f"GUI startup self-test passed ({elapsed:.3f}s).")
    return 0


def _self_test_startup() -> int:
    """Open the real window without reading or writing normal user data."""

    import os
    import tempfile

    user_data_environment = "BDO_USER_DATA_DIR"
    qt_platform_environment = "QT_QPA_PLATFORM"
    self_test_environment = STARTUP_SELF_TEST_ENVIRONMENT
    previous_user_data = os.environ.get(user_data_environment)
    previous_qt_platform = os.environ.get(qt_platform_environment)
    previous_self_test = os.environ.get(self_test_environment)
    try:
        with tempfile.TemporaryDirectory(
            prefix="bdo-music-composer-startup-self-test-"
        ) as isolated_user_data:
            # Keep this protection in the executable itself. The build script
            # also supplies a temporary root, but the diagnostic may be run
            # directly by a maintainer and must never touch their projects,
            # recents, settings, sample cache, or autosaves.
            os.environ[user_data_environment] = isolated_user_data
            os.environ[qt_platform_environment] = "offscreen"
            os.environ[self_test_environment] = "1"
            return _run_startup_self_test_gui()
    finally:
        if previous_user_data is None:
            os.environ.pop(user_data_environment, None)
        else:
            os.environ[user_data_environment] = previous_user_data
        if previous_qt_platform is None:
            os.environ.pop(qt_platform_environment, None)
        else:
            os.environ[qt_platform_environment] = previous_qt_platform
        if previous_self_test is None:
            os.environ.pop(self_test_environment, None)
        else:
            os.environ[self_test_environment] = previous_self_test


def main() -> None:
    if sys.argv[1:] == [TRANSCRIPTION_SELF_TEST_ARGUMENT]:
        raise SystemExit(_self_test_transcription())
    if sys.argv[1:] == [STARTUP_SELF_TEST_ARGUMENT]:
        raise SystemExit(_self_test_startup())

    if len(sys.argv) > 1:
        from scripts.bdo_convert import main as cli_main

        cli_main()
        return

    from bdo_music_composer.ui.main_window import main as gui_main

    raise SystemExit(gui_main())


if __name__ == "__main__":
    main()
