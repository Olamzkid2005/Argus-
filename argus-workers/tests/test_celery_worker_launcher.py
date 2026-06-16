"""Tests for celery_worker_launcher.py."""

import importlib
import os
import signal
import sys
from unittest.mock import patch

import pytest


@pytest.fixture
def cwl():
    """Import/reload celery_worker_launcher with venv found."""
    with patch("celery_worker_launcher.os.path.exists", return_value=True), \
         patch("celery_worker_launcher.os.chdir"):
        import celery_worker_launcher
        importlib.reload(celery_worker_launcher)
        yield celery_worker_launcher


class TestCeleryWorkerLauncher:
    def test_main_constructs_correct_command_with_default_concurrency(self, cwl):
        with patch("celery_worker_launcher.subprocess.Popen") as mock_popen, \
             patch("celery_worker_launcher.signal.signal"):
            mock_popen.return_value.pid = 12345
            mock_popen.return_value.wait.return_value = 0
            cwl.main()
            args = mock_popen.call_args[0][0]
            assert args[0] == cwl.VENV_PYTHON
            assert args[1] == cwl.CELERY_BIN
            assert "--concurrency" in args
            assert args[args.index("--concurrency") + 1] == "8"

    def test_main_uses_celery_concurrency_env_var(self, cwl):
        with patch.dict(os.environ, {"CELERY_CONCURRENCY": "16"}), \
             patch("celery_worker_launcher.subprocess.Popen") as mock_popen, \
             patch("celery_worker_launcher.signal.signal"):
            mock_popen.return_value.pid = 12345
            mock_popen.return_value.wait.return_value = 0
            cwl.main()
            args = mock_popen.call_args[0][0]
            assert args[args.index("--concurrency") + 1] == "16"

    def test_main_falls_back_to_system_python(self):
        with patch("celery_worker_launcher.os.path.exists", return_value=False), \
             patch("celery_worker_launcher.os.chdir"):
            import celery_worker_launcher
            importlib.reload(celery_worker_launcher)
        with patch("celery_worker_launcher.subprocess.Popen") as mock_popen, \
             patch("celery_worker_launcher.signal.signal"):
            mock_popen.return_value.pid = 12345
            mock_popen.return_value.wait.return_value = 0
            celery_worker_launcher.main()
            args = mock_popen.call_args[0][0]
            assert args[0] == sys.executable

    def test_main_sets_up_signal_handlers(self, cwl):
        with patch("celery_worker_launcher.subprocess.Popen") as mock_popen, \
             patch("celery_worker_launcher.signal.signal") as mock_signal:
            mock_popen.return_value.pid = 12345
            mock_popen.return_value.wait.return_value = 0
            cwl.main()
            sig_handled = [args[0][0] for args in mock_signal.call_args_list]
            assert signal.SIGTERM in sig_handled
            assert signal.SIGINT in sig_handled
