"""Synthetic databases for previews and packaged end-to-end verification."""
import json, sqlite3, tempfile
from pathlib import Path
from contextlib import closing
from .core import inspect_plan, migrate, restore_backup, sha256

def make_demo(root):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    fixtures=Path(__file__).parent/'fixtures'
    src=root/'Tai 示例.db'; dst=root/'hindsight.example.sqlite'
    for p,fixture in ((src,'tai.sql'),(dst,'hindsight_v43.sql')):
        with closing(sqlite3.connect(p)) as c:
            c.executescript((fixtures/fixture).read_text('utf8')); c.commit()
    with closing(sqlite3.connect(src)) as c:
        c.execute('DELETE FROM AppModels'); c.execute('DELETE FROM CategoryModels')
        for i,name,color in [(1,'工作','#4E6A9B'),(2,'浏览','#238777'),(3,'沟通','#D79536'),(4,'娱乐','#8A6B99')]:
            c.execute('INSERT INTO CategoryModels(ID,Name,Color) VALUES(?,?,?)',(i,name,color))
        for i,proc,name,seconds in [(1,'Code.exe','Visual Studio Code',2580),(2,'msedge.exe','Microsoft Edge',1860),(3,'WeChat.exe','微信',720),(4,'steam.exe','Steam',1080)]:
            c.execute('INSERT INTO AppModels(ID,Name,Description,File,Alias,CategoryID) VALUES(?,?,?,?,?,?)',(i,proc,name,'C:/Applications/'+proc,name,i))
            for day in range(10,16):
                c.execute('INSERT INTO HoursLogModels(DataTime,Time,AppModelID) VALUES(?,?,?)',(f'2026-10-{day:02d} {8+i:02d}:00:00',seconds,i))
        c.commit()
    with closing(sqlite3.connect(dst)) as c:
        c.execute("INSERT INTO devices(device_id,display_name,is_self) VALUES('demo-device','演示电脑',1)"); c.commit()
        c.execute('PRAGMA journal_mode=WAL')
    return src,dst

def self_test(output):
    report={'ok':False}
    try:
        with tempfile.TemporaryDirectory(prefix='tai-hindsight-check-') as d:
            src,dst=make_demo(d); source_hash=sha256(src)
            plan=inspect_plan(src,dst); before=sha256(dst)
            result=migrate(plan)
            with closing(sqlite3.connect(dst)) as c:
                seconds=c.execute('SELECT SUM(duration_secs) FROM activities').fetchone()[0]
                rows=c.execute('SELECT COUNT(*) FROM activities').fetchone()[0]
                mode=c.execute('PRAGMA journal_mode').fetchone()[0]
            assert seconds==plan.total_seconds and rows==plan.new
            assert sha256(src)==source_hash
            repeat=inspect_plan(src,dst); assert repeat.pending==0
            restore_backup(dst,result.backup)
            with closing(sqlite3.connect(dst)) as c: assert c.execute('SELECT COUNT(*) FROM activities').fetchone()[0]==0
            assert sha256(dst)==sha256(result.backup)
            report.update(ok=True,records=rows,seconds=seconds,journal_mode=mode,repeat_pending=repeat.pending,source_unchanged=True,restored=True)
    except Exception as exc:
        report['error']=repr(exc)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if report['ok'] else 1
