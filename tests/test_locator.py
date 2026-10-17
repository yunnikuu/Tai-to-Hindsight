import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from migrator import locator


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            'APPDATA': str(self.root/'Roaming'), 'LOCALAPPDATA': str(self.root/'Local'),
            'USERPROFILE': str(self.root/'User'), 'ProgramData': str(self.root/'ProgramData'),
            'ProgramFiles': str(self.root/'Programs'), 'ProgramFiles(x86)': str(self.root/'Programs32'),
            'HINDSIGHT_DATA_DIR': '', 'TAI_MIGRATOR_SETTINGS': str(self.root/'settings.json'),
        })
        self.env.start()
        self.proc = patch.object(locator, 'process_folders', return_value=[])
        self.proc.start()

    def tearDown(self):
        self.proc.stop(); self.env.stop(); self.tmp.cleanup()

    def db(self, path, kind):
        path.parent.mkdir(parents=True, exist_ok=True)
        sql = ('CREATE TABLE AppModels(ID); CREATE TABLE HoursLogModels(ID);'
               if kind == 'tai' else 'CREATE TABLE activities(id);')
        with closing(sqlite3.connect(path)) as c:
            c.executescript(sql); c.commit()
        return path.resolve()

    def test_folder_scan_finds_nested_portable_tai(self):
        expected = self.db(self.root/'Portable'/'Tai-1.5'/'Tai'/'Data'/'data.db', 'tai')
        self.assertIn(expected, locator.locate_tai(self.root/'Portable'))

    def test_hindsight_data_env_override(self):
        expected = self.db(self.root/'Custom Data'/'hindsight.sqlite', 'hindsight')
        with patch.dict(os.environ, {'HINDSIGHT_DATA_DIR': str(expected.parent)}):
            self.assertIn(expected, locator.locate_hindsight_candidates())

    def test_bootstrap_bom_and_environment_variable(self):
        config = self.root/'Roaming'/'Hindsight'; config.mkdir(parents=True)
        expected = self.db(self.root/'Custom Data'/'hindsight.sqlite', 'hindsight')
        with patch.dict(os.environ, {'TEST_MIGRATION_DATA': str(expected.parent)}):
            (config/'bootstrap.json').write_text(json.dumps({'data_path': '%TEST_MIGRATION_DATA%'}), encoding='utf-8-sig')
            self.assertIn(expected, locator.locate_hindsight_candidates())

    def test_data_folder_accepts_sqlite3_extension(self):
        expected = self.db(self.root/'Chosen'/'hindsight.sqlite3', 'hindsight')
        self.assertIn(expected, locator.locate_hindsight_candidates(expected.parent))

    def test_history_recovers_previously_selected_portable_db(self):
        expected = self.db(self.root/'Obscure'/'Data'/'data.db', 'tai')
        locator.remember_path('tai', expected)
        with patch.object(locator, 'windows_hints', return_value=[]):
            self.assertIn(expected, [c.path for c in locator.discover('tai').candidates])

    def test_shortcut_and_registry_hints_are_used(self):
        expected = self.db(self.root/'Off Drive'/'Tai'/'Data'/'data.db', 'tai')
        with patch.object(locator, 'windows_hints', return_value=[('tai', expected.parent.parent/'Tai.exe', '桌面快捷方式')]):
            result = locator.discover('tai')
        self.assertIn(expected, [c.path for c in result.candidates])
        self.assertIn('桌面快捷方式', result.candidates[0].sources)

    def test_active_account_is_read_from_all_config_roots(self):
        config = self.root/'Local'/'Hindsight'; config.mkdir(parents=True)
        (config/'active_user.json').write_text('{"uid":"alice"}', encoding='utf8')
        alice = self.db(self.root/'Other'/'hindsight.alice.sqlite', 'hindsight')
        anon = self.db(self.root/'Other'/'hindsight.sqlite', 'hindsight')
        selected, _, _ = locator.choose_hindsight([anon, alice])
        self.assertEqual(selected, alice)

    def test_scan_cancels_and_never_returns_backup_folder(self):
        good = self.db(self.root/'Chosen'/'live'/'hindsight.sqlite', 'hindsight')
        backup = self.db(self.root/'Chosen'/'tai-migration-backups'/'hindsight.sqlite', 'hindsight')
        result = locator.discover('hindsight', self.root/'Chosen', deep=True)
        self.assertIn(good, [c.path for c in result.candidates])
        self.assertNotIn(backup, [c.path for c in result.candidates])
        event = threading.Event(); event.set()
        result = locator.discover('hindsight', self.root/'Chosen', deep=True, cancel=event)
        self.assertTrue(result.cancelled)

    def test_selected_db_is_scoped_and_read_only(self):
        selected = self.db(self.root/'Specific'/'tai.db', 'tai')
        before = selected.read_bytes()
        result = locator.discover('tai', selected)
        self.assertEqual([c.path for c in result.candidates], [selected])
        self.assertEqual(before, selected.read_bytes())

    def test_directory_budget_reports_incomplete_scan(self):
        for i in range(5): (self.root/'Chosen'/str(i)).mkdir(parents=True)
        result = locator.discover('tai', self.root/'Chosen', deep=True, max_dirs=2)
        self.assertTrue(result.limited)
        self.assertLessEqual(result.scanned_dirs, 2)

    def test_registry_icon_and_command_paths_are_normalized(self):
        path = self.root/'Tai Folder'/'Tai.exe'
        self.assertEqual(locator.normalize_path('"'+str(path)+'",0'), path)
        self.assertEqual(locator.normalize_path('"'+str(path)+'" --selfStart'), path)

    def test_conflicting_account_markers_do_not_auto_select(self):
        for folder, uid in [('Roaming','alice'),('Local','bob')]:
            config=self.root/folder/'Hindsight'; config.mkdir(parents=True)
            (config/'active_user.json').write_text(json.dumps({'uid':uid}), encoding='utf8')
        alice=self.db(self.root/'Data'/'hindsight.alice.sqlite','hindsight')
        bob=self.db(self.root/'Data'/'hindsight.bob.sqlite','hindsight')
        self.assertIsNone(locator.choose_hindsight([alice,bob])[0])
