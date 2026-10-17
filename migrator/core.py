"""Offline, transactional Tai -> Hindsight migration. No network access."""
from __future__ import annotations

import hashlib
import json
import math
import ntpath
import os
import re
import shutil
import sqlite3
import threading
import uuid
from collections import defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TITLE = 'Tai 小时汇总（重建时间段）'
NS = uuid.UUID('6189958b-b77c-4894-83a1-870917b826bb')

class MigrationError(Exception):
    """An actionable error safe to show to the user."""

@dataclass(frozen=True)
class Options:
    start_date: str = ''
    end_date: str = ''
    timezone: str = 'Asia/Shanghai'
    categories: bool = True
    daily_fallback: bool = True
    overlap: str = 'skip'

@dataclass
class Record:
    key: str
    process: str
    display: str
    exe: str
    day: str
    hour: int
    seconds: int
    category: str = ''
    color: str = '#94A3B8'
    estimated: bool = False
    action: str = 'new'
    activity_id: int | None = None
    old_seconds: int = 0

@dataclass
class Plan:
    source: Path
    target: Path
    options: Options
    source_signature: str
    target_signature: str
    source_sha256: str
    records: list[Record]
    warnings: list[str]
    device_id: str
    target_count: int
    target_version: int
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: int = 0

    @property
    def total_seconds(self): return sum(r.seconds for r in self.records)
    @property
    def app_count(self): return len({r.process for r in self.records if r.seconds})
    @property
    def pending(self): return self.new + self.updated
    @property
    def delta_seconds(self):
        return sum(r.seconds - r.old_seconds for r in self.records if r.action in ('new','update'))
    @property
    def date_range(self):
        days = [r.day for r in self.records if r.seconds]
        return (min(days),max(days)) if days else ('','')

@dataclass
class Result:
    batch_id: str
    new: int
    updated: int
    unchanged: int
    seconds_added: int
    backup: Path | None
    report: Path | None
    warnings: list[str] = field(default_factory=list)

def sha256(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def signature(p: Path) -> str:
    h=hashlib.sha256()
    for part in (p,Path(str(p)+'-wal')):
        h.update(part.name.encode('utf8'))
        if part.exists() and (part == p or part.stat().st_size > 32):
            h.update(sha256(part).encode('ascii'))
    return h.hexdigest()

def read_db(p: Path) -> sqlite3.Connection:
    if not p.is_file(): raise MigrationError(f'数据库不存在：{p}。请先启动并退出对应软件，或重新选择文件。')
    try:
        c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        c.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
        return c
    except sqlite3.Error as e:
        raise MigrationError(f'无法读取 SQLite 数据库：{p.name}。请检查文件或退出占用程序。详情：{e}') from e

def tables(c): return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def columns(c,t): return {r['name']:r for r in c.execute(f'PRAGMA table_info("{t}")')}

def require(c,t,fields):
    if t not in tables(c) or not set(fields)<=set(columns(c,t)):
        raise MigrationError(f'数据库结构不匹配：缺少 {t} 表或字段 {", ".join(fields)}。请选择正确软件的主数据库。')

def check_target(c):
    require(c,'activities',('id','started_at','ended_at','duration_secs','local_date','local_hour','process_name','category_id'))
    known={'id','started_at','ended_at','duration_secs','local_date','local_hour','process_name','category_id','window_title','device_id','updated_at','origin','remote_id','excluded','url_host','screenshot_path','image_hash'}
    for name,col in columns(c,'activities').items():
        if name not in known and col['notnull'] and col['dflt_value'] is None and not col['pk']:
            raise MigrationError(f'Hindsight 新增了无法填充的必填字段 {name}，已停止写入。')
    if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':
        raise MigrationError('Hindsight 数据库完整性检查未通过，请先修复或恢复备份。')

def options_zone(opts):
    try: z=ZoneInfo(opts.timezone)
    except (ZoneInfoNotFoundError,ValueError) as e: raise MigrationError('时区无效，请使用 Asia/Shanghai 或有效的 IANA 时区。') from e
    for value in (opts.start_date,opts.end_date):
        if value:
            try:
                if date.fromisoformat(value).isoformat()!=value: raise ValueError()
            except ValueError as e: raise MigrationError('日期格式应为 YYYY-MM-DD，例如 2026-10-01。') from e
    if opts.start_date and opts.end_date and opts.start_date>opts.end_date: raise MigrationError('开始日期不能晚于结束日期。')
    if opts.overlap not in ('skip','import'): raise MigrationError('无效的重叠处理方式。')
    return z

def parse_time(value,zone):
    try:
        # System.Data.SQLite defaults to ISO8601. Never guess epochs or .NET ticks.
        dt=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
        if dt.tzinfo: dt=dt.astimezone(zone).replace(tzinfo=None)
        return dt
    except (ValueError,TypeError,OverflowError) as e:
        raise MigrationError(f'Tai 时间无法识别：{value!r}。支持 SQLite 默认 ISO8601 日期；未对未知编码做猜测。') from e

def duration(value,limit):
    try:
        n=float(value)
        if not math.isfinite(n) or n!=int(n) or not 0<=n<=limit: raise ValueError()
        return int(n)
    except (ValueError,TypeError,OverflowError) as e:
        raise MigrationError(f'Tai 时长无效：{value!r}，允许范围为 0–{limit} 整秒。已停止，避免丢失或虚增数据。') from e

def process_of(app):
    raw=(app.get('File') or '').strip().strip('"')
    candidate=ntpath.basename(raw) if raw else ''
    if not candidate or candidate in ('.','..'): candidate=(app.get('Name') or '').strip()
    name=ntpath.basename(candidate)
    if not name or name in ('.','..'): raise MigrationError(f'Tai 应用 ID={app.get("ID")} 缺少进程名和路径。')
    if not name.lower().endswith('.exe'): name+='.exe'
    return name

def load_records(c,opts):
    zone=options_zone(opts)
    require(c,'AppModels',('ID','Name'))
    ts=tables(c)
    if not {'HoursLogModels','DailyLogModels'} & ts: raise MigrationError('Tai 缺少小时和每日使用记录表。')
    apps={r['ID']:dict(r) for r in c.execute('SELECT * FROM AppModels')}
    cats={r['ID']:dict(r) for r in c.execute('SELECT * FROM CategoryModels')} if 'CategoryModels' in ts else {}
    hours=defaultdict(int); days=defaultdict(int); meta={}; warnings=[]
    def identity(row):
        if row['AppModelID'] not in apps: raise MigrationError(f'Tai 记录引用了不存在的应用 ID={row["AppModelID"]}。')
        a=apps[row['AppModelID']]; proc=process_of(a); cat=cats.get(a.get('CategoryID'),{})
        key=proc.casefold()
        meta.setdefault(key,dict(process=proc,display=a.get('Alias') or a.get('Description') or a.get('Name') or proc,
                                 exe=a.get('File') or '',category=cat.get('Name') or '',color=cat.get('Color') or '#94A3B8'))
        return key
    def selected(day): return (not opts.start_date or day>=opts.start_date) and (not opts.end_date or day<=opts.end_date)
    if 'HoursLogModels' in ts:
        require(c,'HoursLogModels',('ID','DataTime','Time','AppModelID'))
        for row in c.execute('SELECT * FROM HoursLogModels ORDER BY ID'):
            dt=parse_time(row['DataTime'],zone); day=dt.date().isoformat()
            if not selected(day): continue
            n=duration(row['Time'],3600)
            if not n: continue
            if dt.minute or dt.second or dt.microsecond: raise MigrationError(f'Tai 小时记录不是整点：{row["DataTime"]}。')
            p=identity(row); hours[p,day,dt.hour]+=n
            if hours[p,day,dt.hour]>3600: raise MigrationError(f'{meta[p]["process"]} 在 {day} {dt.hour}:00 累计超过 3600 秒。请检查 Tai 的重复或异常记录。')
    if 'DailyLogModels' in ts and opts.daily_fallback:
        require(c,'DailyLogModels',('ID','Date','Time','AppModelID'))
        for row in c.execute('SELECT * FROM DailyLogModels ORDER BY ID'):
            day=parse_time(row['Date'],zone).date().isoformat()
            if not selected(day): continue
            n=duration(row['Time'],86400)
            if n: days[identity(row),day]+=n
    estimated=set(); filled=0
    for (p,day),n in days.items():
        if n>86400: raise MigrationError(f'{day} 的每日汇总超过 86400 秒，已停止迁移。')
        existing=sum(hours[p,day,h] for h in range(24))
        gap=max(0,n-existing)
        if n<existing: warnings.append(f'{meta[p]["process"]} {day}：每日汇总少于小时合计，采用小时合计 {existing} 秒。')
        if gap:
            filled+=gap
            for h in range(24):
                add=min(gap,3600-hours[p,day,h])
                if add:
                    hours[p,day,h]+=add; gap-=add; estimated.add((p,day,h))
                if not gap: break
    if filled: warnings.append(f'已按每日汇总补齐 {filled} 秒；补齐部分从当天可用小时依次放置，不能代表实际小时分布。')
    result=[]
    for (p,day,h),n in sorted(hours.items()):
        if not n: continue
        key=str(uuid.uuid5(NS,f'{p}|{day}|{h}'))
        result.append(Record(key=key,day=day,hour=h,seconds=n,estimated=(p,day,h) in estimated,**meta[p]))
    if 'WebBrowseLogModels' in ts: warnings.append('本工具仅迁移应用使用；Tai 的网站浏览记录不写入 Hindsight。')
    warnings.insert(0,'Tai 仅保留小时/日汇总。活动起止时间为重建值，不代表原始会话；不包含截图和真实窗口标题。')
    return result,warnings

def device_for(c,p):
    if 'devices' in tables(c):
        r=c.execute('SELECT device_id FROM devices WHERE is_self=1 AND deleted_at IS NULL').fetchall()
        if len(r)==1: return r[0][0]
    candidates=[p.parent/'device.json']
    if os.getenv('APPDATA'): candidates.append(Path(os.environ['APPDATA'])/'Hindsight'/'device.json')
    for f in candidates:
        try:
            value=json.loads(f.read_text('utf8')).get('device_id')
            if value: return str(value)
        except (OSError,ValueError,AttributeError): pass
    if 'devices' in tables(c): raise MigrationError('无法确认 Hindsight 本机设备。请在这台电脑启动一次 Hindsight 并完全退出，再重新预览。')
    return 'local'

def classify(c,records,opts,device):
    ts=tables(c); ledger={}
    if 'tai_migration_items' in ts:
        require(c,'tai_migration_items',('record_key','activity_id','timezone','process_name','local_date','local_hour','seconds'))
        ledger={r['record_key']:dict(r) for r in c.execute('SELECT * FROM tai_migration_items')}
    owned={v['activity_id'] for v in ledger.values()}
    existing={r['id']:dict(r) for r in c.execute('SELECT * FROM activities')}
    day_set={(r.process.casefold(),r.day) for r in records}
    keys={r.key for r in records}
    # A daily fallback may move when real hourly data becomes available. Zero old owned
    # slots in the selected app/day so that a re-import cannot double-count the moved time.
    for key,v in ledger.items():
        if key not in keys and (v['process_name'].casefold(),v['local_date']) in day_set and v['activity_id'] in existing:
            records.append(Record(key=key,process=v['process_name'],display=v['process_name'],exe='',day=v['local_date'],hour=v['local_hour'],seconds=0))
    conflicts=0
    acols=columns(c,'activities')
    native=set()
    for r in existing.values():
        if r['id'] not in owned and (not 'device_id' in acols or r['device_id']==device):
            # Treat hand-edited same-process local-time activities as overlap even if an older Hindsight schema had NULL buckets.
            if r['process_name'] and r['local_date']:
                native.add((r['process_name'].casefold(),r['local_date'],r['local_hour']))
                try:
                    zone=options_zone(opts)
                    start=datetime.fromisoformat(str(r['started_at']).replace('Z','+00:00'))
                    end=datetime.fromisoformat(str(r['ended_at']).replace('Z','+00:00'))
                    if start.tzinfo is None: start=start.replace(tzinfo=zone)
                    if end.tzinfo is None: end=end.replace(tzinfo=zone)
                    start=start.astimezone(timezone.utc); end=end.astimezone(timezone.utc)
                    if end-start>timedelta(days=366): raise MigrationError('Hindsight 活动时间跨度异常，已停止预览。')
                    cursor=start.astimezone(zone).replace(minute=0,second=0,microsecond=0).astimezone(timezone.utc)
                    while cursor<end:
                        local=cursor.astimezone(zone)
                        native.add((r['process_name'].casefold(),local.date().isoformat(),local.hour))
                        cursor+=timedelta(hours=1)
                except (ValueError,TypeError,OverflowError,AttributeError): pass
    for r in records:
        item=ledger.get(r.key); old=existing.get(item['activity_id']) if item else None
        if old:
            if item['timezone']!=opts.timezone: raise MigrationError('该批数据已使用其他时区导入，请恢复备份或沿用原时区后再试。')
            if old['duration_secs']!=item['seconds'] or old.get('window_title')!=TITLE or old['process_name'].casefold()!=r.process.casefold() or old['local_date']!=r.day or old['local_hour']!=r.hour:
                raise MigrationError('已导入的记录在 Hindsight 中发生修改，已停止以避免覆盖。请恢复备份后重试。')
            r.activity_id=item['activity_id']; r.old_seconds=old['duration_secs']
            r.action='same' if r.seconds==old['duration_secs'] else 'update'
        else: r.action='new'
        if (r.process.casefold(),r.day,r.hour) in native:
            conflicts+=1
            if opts.overlap=='skip': r.action='conflict'
    return conflicts

def inspect_plan(source, target, options=None) -> Plan:
    opts=options or Options(); options_zone(opts)
    source=Path(source).expanduser().resolve(); target=Path(target).expanduser().resolve()
    if source==target or (source.exists() and target.exists() and os.path.samefile(source,target)): raise MigrationError('Tai 和 Hindsight 不能选择同一个数据库。')
    try:
        ss=signature(source); ds=signature(target)
        with closing(read_db(source)) as src:
            src.execute('BEGIN'); records,warnings=load_records(src,opts)
        with closing(read_db(target)) as dst:
            dst.execute('BEGIN'); check_target(dst); device=device_for(dst,target)
            conflicts=classify(dst,records,opts,device)
            count=dst.execute('SELECT COUNT(*) FROM activities').fetchone()[0]
            ver=dst.execute('SELECT COALESCE(MAX(version),0) FROM schema_version').fetchone()[0] if 'schema_version' in tables(dst) else 0
        if signature(source)!=ss or signature(target)!=ds: raise MigrationError('数据库在读取时发生变化，请完全退出 Tai 与 Hindsight 后重新预览。')
        if conflicts: warnings.append(f'有 {conflicts} 个应用小时与 Hindsight 原有记录重叠；'+('本次跳过这些小时。' if opts.overlap=='skip' else '按你的选择仍然导入，统计时长可能重复。'))
        warnings.append('迁移只写本地数据库，不主动加入 Hindsight 云同步队列。请在目标电脑的本机视图查看。')
        return Plan(source,target,opts,ss,ds,sha256(source),records,warnings,device,count,ver,
                    sum(r.action=='new' for r in records),sum(r.action=='update' for r in records),sum(r.action=='same' for r in records),conflicts)
    except (sqlite3.Error,OSError) as e: raise MigrationError(f'预览失败：{e}') from e

def atomic_json(p,data):
    tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('w',encoding='utf8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
    finally: tmp.unlink(missing_ok=True)

def backup_database(target: Path, folder: Path | None=None) -> Path:
    folder=folder or target.parent/'tai-migration-backups'
    folder.mkdir(parents=True,exist_ok=True)
    p=folder/(target.stem+'.'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.'+uuid.uuid4().hex[:8]+'.sqlite')
    try:
        with closing(read_db(target)) as src, closing(sqlite3.connect(p)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise MigrationError('备份完整性校验失败。')
        atomic_json(p.with_suffix('.sqlite.json'),dict(kind='tai-hindsight-backup-v1',target=str(target),sha256=sha256(p),created_at=datetime.now(timezone.utc).isoformat()))
        return p
    except (OSError,sqlite3.Error) as e: raise MigrationError(f'备份未成功，目标数据没有写入：{e}') from e

def insert_row(c,table,data,ignore=False):
    cols=columns(c,table); data={k:v for k,v in data.items() if k in cols}
    for name,col in cols.items():
        if name not in data and col['notnull'] and col['dflt_value'] is None and not col['pk']:
            raise MigrationError(f'无法兼容 {table}.{name} 必填字段，事务已取消。')
    keys=list(data)
    sql=f'INSERT {"OR IGNORE " if ignore else ""}INTO "{table}" ('+','.join('"'+k+'"' for k in keys)+') VALUES ('+','.join('?' for _ in keys)+')'
    return c.execute(sql,[data[k] for k in keys]).lastrowid

def ensure_metadata(c,r,opts,now):
    ts=tables(c); cat='other'
    if 'categories' in ts:
        if opts.categories and r.category:
            deleted=' AND deleted_at IS NULL' if 'deleted_at' in columns(c,'categories') else ''
            row=c.execute('SELECT id FROM categories WHERE name=?'+deleted,(r.category,)).fetchone()
            if row: cat=row[0]
            else:
                cat='tai-'+str(uuid.uuid5(NS,'category|'+r.category))
                color=r.color
                if re.fullmatch(r'#[0-9a-fA-F]{8}',color): color='#'+color[-6:]
                if not re.fullmatch(r'#[0-9a-fA-F]{6}',color): color='#94A3B8'
                insert_row(c,'categories',dict(id=cat,name=r.category,color=color,builtin=0,icon='Tag',updated_at=now))
        elif not c.execute('SELECT 1 FROM categories WHERE id=?',(cat,)).fetchone():
            insert_row(c,'categories',dict(id=cat,name='其他',color='#94A3B8',builtin=0,icon='MoreHorizontal',updated_at=now))
    if 'app_groups' in ts and 'app_group_members' in ts:
        m=c.execute('SELECT group_id FROM app_group_members WHERE process_name=? AND deleted_at IS NULL',(r.process,)).fetchone() if 'deleted_at' in columns(c,'app_group_members') else c.execute('SELECT group_id FROM app_group_members WHERE process_name=?',(r.process,)).fetchone()
        if not m:
            # Do not overwrite a user-owned group that happens to share this id.
            gid=r.process
            if not c.execute('SELECT 1 FROM app_groups WHERE id=?',(gid,)).fetchone():
                insert_row(c,'app_groups',dict(id=gid,display_name=r.display,category_id=cat,updated_at=now))
            else:
                gid='tai-'+str(uuid.uuid5(NS,'group|'+r.process))
                if not c.execute('SELECT 1 FROM app_groups WHERE id=?',(gid,)).fetchone(): insert_row(c,'app_groups',dict(id=gid,display_name=r.display,category_id=cat,updated_at=now))
            insert_row(c,'app_group_members',dict(process_name=r.process,group_id=gid,updated_at=now,deleted_at=None))
    if 'app_categories' in ts:
        insert_row(c,'app_categories',dict(process_name=r.process,category_id=cat,updated_at=now,deleted_at=None),ignore=True)
    if r.exe and 'process_paths' in ts:
        insert_row(c,'process_paths',dict(process_name=r.process,exe_path=r.exe,seen_at=now,updated_at=now),ignore=True)
    return cat

LEDGER_SQL = (
    'CREATE TABLE IF NOT EXISTS tai_migration_batches (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,source_path TEXT NOT NULL,source_sha256 TEXT NOT NULL,options_json TEXT NOT NULL,backup_path TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS tai_migration_items (record_key TEXT PRIMARY KEY,activity_id INTEGER NOT NULL,process_name TEXT NOT NULL,local_date TEXT NOT NULL,local_hour INTEGER NOT NULL,seconds INTEGER NOT NULL,timezone TEXT NOT NULL,batch_id TEXT NOT NULL)',
)

def migrate(plan: Plan, progress=None, cancel: threading.Event | None=None) -> Result:
    if not plan.pending: return Result('',0,0,plan.unchanged,0,None,None,plan.warnings)
    cancel=cancel or threading.Event()
    backup=None; conn=None; report=None
    def notify(p,text):
        if cancel.is_set(): raise MigrationError('迁移已取消，当前事务没有写入任何记录。')
        if progress: progress(p,text)
    try:
        notify(0,'核对预览与文件状态')
        if signature(plan.source)!=plan.source_signature or signature(plan.target)!=plan.target_signature:
            raise MigrationError('数据库自预览后发生变化，请重新预览再迁移。')
        conn=sqlite3.connect(plan.target.resolve().as_uri()+'?mode=rw',uri=True,timeout=2)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        if signature(plan.target)!=plan.target_signature: raise MigrationError('目标自预览后变化，请重新预览。')
        check_target(conn)
        notify(.05,'备份 Hindsight 数据库')
        backup=backup_database(plan.target)
        notify(.15,'备份已校验，开始转换')
        for sql in LEDGER_SQL: conn.execute(sql)
        batch=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        conn.execute('INSERT INTO tai_migration_batches VALUES(?,?,?,?,?,?)',(batch,now,str(plan.source),plan.source_sha256,json.dumps(asdict(plan.options)),str(backup)))
        writes=[r for r in plan.records if r.action in ('new','update')]
        z=options_zone(plan.options)
        for i,r in enumerate(writes):
            notify(.15+.75*i/max(len(writes),1),f'写入 {i+1} / {len(writes)} · {r.display}')
            start=datetime.combine(date.fromisoformat(r.day),datetime.min.time()).replace(hour=r.hour,tzinfo=z)
            # Both RFC3339 instants and local bucket fields are explicit. A DST gap
            # cannot encode a real hour; refuse to invent a valid-looking instant.
            if start.astimezone(timezone.utc).astimezone(z).replace(tzinfo=None)!=start.replace(tzinfo=None):
                raise MigrationError(f'{r.day} {r.hour}:00 在所选时区不存在，请改正时区。')
            end=(start.astimezone(timezone.utc)+timedelta(seconds=r.seconds)).astimezone(z)
            cat=ensure_metadata(conn,r,plan.options,now)
            values=dict(started_at=start.isoformat(timespec='seconds'),ended_at=end.isoformat(timespec='seconds'),duration_secs=r.seconds,
                        local_date=r.day,local_hour=r.hour,process_name=r.process,window_title=TITLE,category_id=cat,
                        device_id=plan.device_id,updated_at=now,origin='local',remote_id=str(uuid.uuid5(NS,r.key+'|'+plan.device_id)),excluded=0)
            if r.action=='new': activity_id=insert_row(conn,'activities',values)
            else:
                activity_id=r.activity_id
                # Update only owned activity timing; preserve user category metadata.
                data={k:v for k,v in values.items() if k in columns(conn,'activities') and k not in ('category_id','process_name','device_id','origin','remote_id')}
                conn.execute('UPDATE activities SET '+','.join('"'+k+'"=?' for k in data)+' WHERE id=?',list(data.values())+[activity_id])
            conn.execute('INSERT INTO tai_migration_items VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(record_key) DO UPDATE SET activity_id=excluded.activity_id,seconds=excluded.seconds,batch_id=excluded.batch_id',
                         (r.key,activity_id,r.process,r.day,r.hour,r.seconds,plan.options.timezone,batch))
        if conn.execute('PRAGMA foreign_key_check').fetchone(): raise MigrationError('目标存在外键异常，整批迁移已回滚。')
        if signature(plan.source)!=plan.source_signature: raise MigrationError('Tai 在迁移期间发生变化，已回滚。请退出 Tai 再预览。')
        report=backup.parent/(batch+'.report.json')
        report_data=dict(status='prepared',batch_id=batch,source=str(plan.source),target=str(plan.target),source_sha256=plan.source_sha256,
                         backup=str(backup),backup_sha256=sha256(backup),created_at=now,options=asdict(plan.options),
                         new=plan.new,updated=plan.updated,unchanged=plan.unchanged,conflicts=plan.conflicts,delta_seconds=plan.delta_seconds,
                         warnings=plan.warnings,records=[asdict(r) for r in plan.records])
        atomic_json(report,report_data)
        notify(.95,'检查完成，提交事务')
        conn.commit()
        report_data['status']='committed'
        warnings=list(plan.warnings)
        try: atomic_json(report,report_data)
        except OSError: warnings.append('数据库已成功提交，但报告状态未能从 prepared 更新；请保留备份并重新预览核对。')
        # Cancellation after commit must never be reported as a rolled-back import.
        if progress: progress(1,'迁移完成')
        return Result(batch,plan.new,plan.updated,plan.unchanged,plan.delta_seconds,backup,report,warnings)
    except (OSError,sqlite3.Error,MigrationError) as e:
        if conn: conn.rollback()
        if report and report.exists():
            try:
                data=json.loads(report.read_text('utf8')); data['status']='rolled_back'; data['error']=str(e); atomic_json(report,data)
            except OSError: pass
        if isinstance(e,MigrationError): raise
        raise MigrationError(f'迁移失败，事务已回滚：{e}。请完全退出 Tai 与 Hindsight，并检查磁盘空间与目录权限。'+(f' 备份：{backup}' if backup else '')) from e
    finally:
        if conn: conn.close()

def restore_backup(target, backup) -> Path:
    target=Path(target).resolve(); backup=Path(backup).resolve()
    if target==backup: raise MigrationError('恢复目标不能是备份本身。')
    try:
        meta=json.loads(backup.with_suffix('.sqlite.json').read_text('utf8'))
        if meta.get('kind')!='tai-hindsight-backup-v1' or sha256(backup)!=meta.get('sha256'):
            raise MigrationError('备份 SHA-256 校验未通过，已停止恢复。')
        if Path(meta['target']).resolve()!=target: raise MigrationError('该备份不属于当前目标数据库，请选择对应备份。')
        with closing(read_db(backup)) as c: check_target(c)
        with closing(read_db(target)) as c: check_target(c)
        safety=backup_database(target)
        # Require a clean, quiescent database before byte-for-byte atomic replacement.
        with closing(sqlite3.connect(target,timeout=2)) as c:
            c.execute('PRAGMA busy_timeout=2000')
            row=c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if row and row[0]: raise MigrationError('目标数据库仍被占用，退出 Hindsight 后再恢复。')
            c.execute('BEGIN EXCLUSIVE'); c.rollback()
        wal=Path(str(target)+'-wal')
        if wal.exists() and wal.stat().st_size: raise MigrationError('目标仍有未合并 WAL，已停止恢复。')
        tmp=target.with_name(target.name+'.restore-'+uuid.uuid4().hex+'.tmp')
        try:
            shutil.copyfile(backup,tmp)
            if sha256(tmp)!=meta['sha256']: raise MigrationError('恢复临时文件校验失败。')
            os.replace(tmp,target)
            for suffix in ('-wal','-shm'): Path(str(target)+suffix).unlink(missing_ok=True)
        finally: tmp.unlink(missing_ok=True)
        if sha256(target)!=meta['sha256']: raise MigrationError('恢复后哈希不一致，请保留安全备份。')
        return safety
    except (OSError,sqlite3.Error,ValueError,KeyError) as e:
        raise MigrationError(f'无法恢复：{e}。原目标的安全备份位于 tai-migration-backups。') from e
