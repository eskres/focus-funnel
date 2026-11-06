"""The backend's `app` loggers write INFO to stderr (thought-export task
2.10, design decision 17)."""

import json
import logging
import subprocess
import sys
from pathlib import Path

import app.main  # noqa: F401 - imported for its logging setup
from app.log_masking import APP_LOGGER, configure_app_logging

BACKEND = Path(__file__).resolve().parent.parent


def test_the_export_logger_writes_info():
    assert logging.getLogger("app.thoughts.export").getEffectiveLevel() == logging.INFO
    assert logging.getLogger(APP_LOGGER).propagate is True


def test_a_second_call_adds_no_handler():
    configure_app_logging()
    configure_app_logging()
    handlers = logging.getLogger(APP_LOGGER).handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert handlers[0].stream is sys.stderr
    assert handlers[0].formatter._fmt == "%(levelname)s %(name)s: %(message)s"


def test_root_and_library_loggers_are_left_alone():
    """In a fresh interpreter: the levels before and after importing app.main."""
    script = (
        "import json, logging, sys; sys.path.insert(0, '.')\n"
        "levels = lambda: [logging.getLogger().level, logging.getLogger('httpx').getEffectiveLevel()]\n"
        "before = levels()\n"
        "import app.main\n"
        "print(json.dumps({'before': before, 'after': levels(),"
        " 'export': logging.getLogger('app.thoughts.export').getEffectiveLevel(),"
        " 'handlers': len(logging.getLogger('app').handlers),"
        " 'root_handlers': len(logging.getLogger().handlers)}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout.strip().splitlines()[-1])
    assert found["after"] == found["before"]
    assert found["export"] == logging.INFO
    assert found["handlers"] == 1
    assert found["root_handlers"] == 0


def test_an_info_line_reaches_stderr():
    script = (
        "import logging, sys; sys.path.insert(0, '.')\n"
        "import app.main\n"
        "logging.getLogger('app.thoughts.export').info('export ended user=x format=json thoughts=0 outcome=complete')\n"
        "logging.getLogger('httpx').info('not shown')\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (
        "INFO app.thoughts.export: export ended user=x format=json thoughts=0 outcome=complete"
        in result.stderr
    )
    assert "not shown" not in result.stderr
