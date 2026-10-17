import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import closing
from migrator.core import Options, inspect_plan, migrate, restore_backup, MigrationError

FIX = Path(__file__).parent / 'fixtures'

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / 'Tai 数据.db'
        self.dst = self.root / 'hindsight.sqlite'
        self.make(self.src, 'tai.sql')
        self.make(self.dst, 'hindsight_v43.sql')
        self.exec(self.dst, "INSERT INTO devices(device_id,display_name,is_self) VALUES('test-device','我的电脑',1)")
        self.opts = Options()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, p, fixture):
        with closing(sqlite3.connect(p)) as c:
            c.executescript((FIX / fixture).read_text('utf8')); c.commit()

    def exec(self, p, sql, args=()):
        with closing(sqlite3.connect(p)) as c:
            c.execute(sql, args); c.commit()

    def rows(self, p, sql):
        with closing(sqlite3.connect(p)) as c:
            return c.execute(sql).fetchall()

    def hour(self, i=1, date='2026-10-15 23:00:00', seconds=600, app=1):
        self.exec(self.src, 'INSERT INTO HoursLogModels VALUES(?,?,?,?)', (i,date,seconds,app))

    def test_preview_is_read_only_and_import_preserves_seconds_category_and_device(self):
        self.hour()
        before = self.src.read_bytes(), self.dst.read_bytes()
        p = inspect_plan(self.src, self.dst, self.opts)
        self.assertEqual((p.new, p.total_seconds, p.app_count), (1,600,1))
        self.assertEqual((self.src.read_bytes(),self.dst.read_bytes()), before)
        result = migrate(p)
        row = self.rows(self.dst, 'SELECT duration_secs,local_date,local_hour,process_name,device_id,started_at,ended_at FROM activities')[0]
        self.assertEqual(row[:5], (600,'2026-10-15',23,'Code.exe','test-device'))
        self.assertTrue(row[5].endswith('+08:00'))
        self.assertEqual(self.rows(self.dst, "SELECT display_name FROM app_groups WHERE id='Code.exe'")[0][0], 'Visual Studio Code')
        self.assertTrue(result.backup.exists())
        self.assertTrue(result.report.exists())
        self.assertEqual(self.src.read_bytes(), before[0])

    def test_repeat_and_copied_source_are_idempotent_and_growth_updates_only_import(self):
        self.hour()
        migrate(inspect_plan(self.src,self.dst,self.opts))
        copy = self.root / 'copy.db'
        shutil.copy2(self.src,copy)
        p = inspect_plan(copy,self.dst,self.opts)
        self.assertEqual((p.new,p.unchanged),(0,1))
        self.exec(copy,'UPDATE HoursLogModels SET Time=900')
        p = inspect_plan(copy,self.dst,self.opts)
        self.assertEqual(p.updated,1)
        migrate(p)
        self.assertEqual(self.rows(self.dst,'SELECT duration_secs FROM activities'),[(900,)])

    def test_daily_reconciliation_does_not_double_count_hours(self):
        self.hour(seconds=600)
        self.exec(self.src, "INSERT INTO DailyLogModels VALUES(1,'2026-10-15',900,1)")
        p = inspect_plan(self.src,self.dst,self.opts)
        self.assertEqual(p.total_seconds,900)
        self.assertEqual(sum(x.seconds for x in p.records),900)
        self.assertTrue(any('补齐' in w for w in p.warnings))
        migrate(p)
        self.assertEqual(self.rows(self.dst,'SELECT SUM(duration_secs) FROM activities')[0][0],900)

    def test_hourly_duplicate_aggregates_and_invalid_duration_is_blocked(self):
        self.hour(seconds=600)
        self.hour(2,seconds=200)
        p = inspect_plan(self.src,self.dst,self.opts)
        self.assertEqual((p.new,p.total_seconds),(1,800))
        self.hour(3,seconds=3000)
        with self.assertRaises(MigrationError):
            inspect_plan(self.src,self.dst,self.opts)

    def test_missing_app_and_malformed_time_are_explicit_errors(self):
        self.hour(app=999)
        with self.assertRaises(MigrationError): inspect_plan(self.src,self.dst,self.opts)
        self.exec(self.src,'DELETE FROM HoursLogModels')
        self.hour(date='bad')
        with self.assertRaises(MigrationError): inspect_plan(self.src,self.dst,self.opts)

    def test_target_change_invalidates_preview(self):
        self.hour()
        p = inspect_plan(self.src,self.dst,self.opts)
        self.exec(self.dst,"UPDATE devices SET display_name='changed'")
        with self.assertRaisesRegex(MigrationError,'预览'):
            migrate(p)
        self.assertEqual(self.rows(self.dst,'SELECT COUNT(*) FROM activities')[0][0],0)

    def test_failure_rolls_back_whole_batch(self):
        self.hour()
        self.hour(2,'2026-10-16 00:00:00',200,2)
        self.exec(self.dst, "CREATE TRIGGER reject_chrome BEFORE INSERT ON activities WHEN NEW.process_name='chrome.exe' BEGIN SELECT RAISE(ABORT,'forced failure'); END")
        p = inspect_plan(self.src,self.dst,self.opts)
        with self.assertRaises(MigrationError): migrate(p)
        self.assertEqual(self.rows(self.dst,'SELECT COUNT(*) FROM activities')[0][0],0)
        self.assertEqual(self.rows(self.dst,"SELECT COUNT(*) FROM sqlite_master WHERE name='tai_migration_items'")[0][0],0)

    def test_cancel_rolls_back(self):
        self.hour()
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(MigrationError): migrate(inspect_plan(self.src,self.dst,self.opts),cancel=cancel)
        self.assertEqual(self.rows(self.dst,'SELECT COUNT(*) FROM activities')[0][0],0)

    def test_backup_restore_and_checksum(self):
        self.hour()
        r = migrate(inspect_plan(self.src,self.dst,self.opts))
        restore_backup(self.dst,r.backup)
        self.assertEqual(self.rows(self.dst,'SELECT COUNT(*) FROM activities')[0][0],0)
        self.assertEqual(hashlib.sha256(self.dst.read_bytes()).hexdigest(),hashlib.sha256(r.backup.read_bytes()).hexdigest())
        r.backup.write_bytes(r.backup.read_bytes()+b'bad')
        with self.assertRaises(MigrationError): restore_backup(self.dst,r.backup)

    def test_old_schema_and_date_range(self):
        self.dst.unlink()
        self.make(self.dst,'hindsight_v7.sql')
        self.hour()
        self.hour(2,'2026-10-16 00:00:00',300,2)
        p=inspect_plan(self.src,self.dst,Options(start_date='2026-10-16',end_date='2026-10-16'))
        self.assertEqual(p.total_seconds,300)
        migrate(p)
        self.assertEqual(self.rows(self.dst,'SELECT process_name FROM activities'),[('chrome.exe',)])

    def test_overlap_defaults_to_skip_and_override_is_explicit(self):
        self.hour()
        self.exec(self.dst, "INSERT INTO activities(started_at,ended_at,duration_secs,local_date,local_hour,process_name,category_id,device_id) VALUES('2026-10-15T23:20:00+08:00','2026-10-15T23:25:00+08:00',300,'2026-10-15',23,'Code.exe','other','test-device')")
        p=inspect_plan(self.src,self.dst,self.opts)
        self.assertEqual((p.new,p.conflicts),(0,1))
        p=inspect_plan(self.src,self.dst,Options(overlap='import'))
        self.assertEqual((p.new,p.conflicts),(1,1))

    def test_foreign_schema_and_same_file_rejected(self):
        with self.assertRaises(MigrationError): inspect_plan(self.src,self.src,self.opts)
        with self.assertRaises(MigrationError): inspect_plan(self.dst,self.src,self.opts)

    def test_deleted_import_is_recreated(self):
        self.hour()
        migrate(inspect_plan(self.src,self.dst,self.opts))
        self.exec(self.dst,'DELETE FROM activities')
        p=inspect_plan(self.src,self.dst,self.opts)
        self.assertEqual(p.new,1)
        migrate(p)
        self.assertEqual(self.rows(self.dst,'SELECT COUNT(*) FROM activities')[0][0],1)

    def test_wal_source_is_seen_and_busy_target_reports_error(self):
        c=sqlite3.connect(self.src); c.execute('PRAGMA journal_mode=WAL')
        c.execute("INSERT INTO HoursLogModels VALUES(1,'2026-10-15 12:00:00',120,1)"); c.commit()
        try:
            p=inspect_plan(self.src,self.dst,self.opts)
            self.assertEqual(p.total_seconds,120)
            lock=sqlite3.connect(self.dst); lock.execute('BEGIN IMMEDIATE')
            try:
                with self.assertRaises(MigrationError): migrate(p)
            finally: lock.rollback(); lock.close()
        finally: c.close()


    def test_wal_target_round_trip(self):
        self.hour()
        with closing(sqlite3.connect(self.dst)) as c:
            c.execute('PRAGMA journal_mode=WAL')
        p=inspect_plan(self.src,self.dst,self.opts)
        result=migrate(p)
        self.assertEqual(self.rows(self.dst,'PRAGMA journal_mode')[0][0],'wal')
        self.assertEqual(self.rows(self.dst,'SELECT SUM(duration_secs) FROM activities')[0][0],600)
        self.assertEqual(inspect_plan(self.src,self.dst,self.opts).pending,0)
        restore_backup(self.dst,result.backup)
        self.assertEqual(self.rows(self.dst,'SELECT COUNT(*) FROM activities')[0][0],0)

    def test_native_overlap_spans_hours(self):
        self.hour(date='2026-10-15 12:00:00')
        self.exec(self.dst,"INSERT INTO activities(started_at,ended_at,duration_secs,local_date,local_hour,process_name,category_id,device_id) VALUES('2026-10-15T11:50:00+08:00','2026-10-15T12:20:00+08:00',1800,'2026-10-15',11,'Code.exe','other','test-device')")
        self.assertEqual(inspect_plan(self.src,self.dst,self.opts).conflicts,1)

    def test_edited_import_duration_is_protected(self):
        self.hour()
        migrate(inspect_plan(self.src,self.dst,self.opts))
        self.exec(self.dst,'UPDATE activities SET duration_secs=1')
        with self.assertRaises(MigrationError): inspect_plan(self.src,self.dst,self.opts)

if __name__=='__main__': unittest.main()
