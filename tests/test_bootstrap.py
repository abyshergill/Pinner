import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pinner import config
from pinner.core.bootstrap import open_repository
from pinner.core.models import Section


class BootstrapTests(unittest.TestCase):
    def test_first_run_seeds_default_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = open_repository(Path(tmp) / "a.db")
            self.assertEqual([g.name for g in repo.list_groups(Section.PATHS)], ["General"])
            self.assertEqual([g.name for g in repo.list_groups(Section.BROWSER)], ["Bookmarks"])
            repo.db.close()

    def test_reopen_does_not_duplicate_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(2):
                repo = open_repository(Path(tmp) / "a.db")
                repo.db.close()
            repo = open_repository(Path(tmp) / "a.db")
            self.assertEqual(len(repo.list_groups(Section.PATHS)), 1)
            repo.db.close()

    def test_db_path_env_override(self):
        with mock.patch.dict(os.environ, {config.DB_ENV_VAR: "/tmp/custom.db"}):
            self.assertEqual(config.default_db_path(), Path("/tmp/custom.db"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(config.DB_ENV_VAR, None)
            self.assertEqual(config.default_db_path(), config.PROJECT_ROOT / "pinner.db")
            self.assertEqual(config.default_db_path().name, "pinner.db")


if __name__ == "__main__":
    unittest.main()
