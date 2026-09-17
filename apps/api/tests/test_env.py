"""Environment resolution: process variables first, developer files only when allowed."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import env as env_module
from app.services.env import env_value

DEVELOPER_FILES = ({"GEMINI_API_KEY": "developer-key"},)


class EnvValueTest(unittest.TestCase):
    def setUp(self):
        files_patch = patch.object(env_module, "_env_files", lambda: DEVELOPER_FILES)
        files_patch.start()
        self.addCleanup(files_patch.stop)
        env_patch = patch.dict(os.environ)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        for name in ("GEMINI_API_KEY", "PIXEL_IGNORE_ENV_FILES"):
            os.environ.pop(name, None)

    def test_developer_files_are_a_fallback(self):
        self.assertEqual(env_value("GEMINI_API_KEY"), "developer-key")
        os.environ["GEMINI_API_KEY"] = "process-key"
        self.assertEqual(env_value("GEMINI_API_KEY"), "process-key")

    def test_web_app_env_files_are_never_read(self):
        web_root = env_module.REPO_ROOT / "apps" / "web"
        self.assertTrue(env_module.API_ENV_FILES)
        for path in env_module.API_ENV_FILES:
            with self.subTest(path=path):
                self.assertNotEqual(path.parent, web_root)
                self.assertFalse(path.is_relative_to(web_root))

    def test_hermetic_runs_ignore_developer_files(self):
        os.environ["PIXEL_IGNORE_ENV_FILES"] = "true"
        self.assertIsNone(env_value("GEMINI_API_KEY"))
        os.environ["GEMINI_API_KEY"] = "process-key"
        self.assertEqual(env_value("GEMINI_API_KEY"), "process-key")


if __name__ == "__main__":
    unittest.main()
