"""Bounded, local Windows discovery; never scans whole drives."""
from __future__ import annotations
import csv, ctypes, json, os, re, sqlite3, subprocess, sys, time, uuid
from collections import deque
from dataclasses import dataclass, field
from contextlib import closing
from pathlib import Path
from .core import MigrationError


def running_apps():
    if os.name != 'nt': return []
    try:
        r=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode: raise MigrationError('无法检查运行中的应用，请稍后重试。')
        return sorted({row[0] for row in csv.reader(r.stdout.splitlines()) if row and row[0].casefold() in ('tai.exe','hindsight.exe')})
    except (OSError,subprocess.TimeoutExpired) as e:
        raise MigrationError('无法检查运行中的应用，请稍后重试。') from e


def ensure_closed():
    names=running_apps()
    if names: raise MigrationError('请先完全退出 '+ '、'.join(names)+'（包括托盘图标），再执行此操作。')


def process_folders():
    if os.name != 'nt': return []
    # Read only install paths for the two known executables.
    import ctypes.wintypes as w
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),('th32ParentProcessID',w.DWORD),('pcPriClassBase',w.LONG),('dwFlags',w.DWORD),('szExeFile',w.WCHAR*260)]
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD]
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
    k.CreateToolhelp32Snapshot.restype=w.HANDLE
    k.OpenProcess.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE]
    k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
    k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    snapshot=k.CreateToolhelp32Snapshot(2,0); result=[]
    if snapshot == ctypes.c_void_p(-1).value: return result
    try:
        e=Entry(); e.dwSize=ctypes.sizeof(e); ok=k.Process32FirstW(snapshot,ctypes.byref(e))
        while ok:
            if e.szExeFile.casefold() in ('tai.exe','hindsight.exe'):
                handle=k.OpenProcess(0x1000,False,e.th32ProcessID)
                if handle:
                    try:
                        buf=ctypes.create_unicode_buffer(32768); size=w.DWORD(len(buf))
                        if k.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)): result.append((e.szExeFile.casefold(),Path(buf.value).parent))
                    finally: k.CloseHandle(handle)
            ok=k.Process32NextW(snapshot,ctypes.byref(e))
    finally: k.CloseHandle(snapshot)
    return result


@dataclass
class Candidate:
    path: Path
    sources: list[str] = field(default_factory=list)
    active: bool = False
    account: str = ''
    size: int = 0
    modified: float = 0


@dataclass
class Discovery:
    kind: str
    candidates: list[Candidate] = field(default_factory=list)
    checked: int = 0
    scanned_dirs: int = 0
    limited: bool = False
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)


def normalize_path(value):
    """Accept pasted paths, registry icons and quoted executable commands."""
    value = str(value).strip()
    if value.startswith('"') and '"' in value[1:]:
        value = value[1:value.index('"', 1)]
    else:
        value = re.sub(r',-?\d+$', '', value)
        match = re.match(r'(.+?\.exe)(?:\s+.*)?$', value, re.I)
        if match: value = match.group(1)
    value = os.path.expandvars(value)
    value = re.sub(r'%([^%]+)%', lambda m: os.environ.get(m.group(1), m.group(0)), value)
    return Path(value).expanduser()


def valid_db(p, table):
    p = Path(p)
    try:
        if not p.is_file(): return False
        # Reject unrelated files before SQLite can create journal sidecars.
        with p.open('rb') as f:
            if f.read(16) != b'SQLite format 3\x00': return False
        with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro', uri=True, timeout=.15)) as c:
            return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
    except (sqlite3.Error, OSError, ValueError):
        return False


def read_json(path):
    try:
        path = Path(path)
        if path.stat().st_size > 1024*1024: return {}
        value = json.loads(path.read_text('utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError): return {}


def parse_active_user(config):
    value = read_json(Path(config)/'active_user.json').get('uid')
    return value.strip() if isinstance(value, str) and value.strip() else None


def config_roots():
    return list(dict.fromkeys(Path(os.environ[k])/'Hindsight' for k in ('APPDATA','LOCALAPPDATA') if os.getenv(k)))


def settings_path():
    if os.getenv('TAI_MIGRATOR_SETTINGS'): return normalize_path(os.environ['TAI_MIGRATOR_SETTINGS'])
    return Path(os.getenv('LOCALAPPDATA', str(Path.home())))/'Tai-Hindsight-Migrator'/'locations.json'


def remember_path(kind, path):
    if kind not in ('tai','hindsight'): return
    path = Path(path).resolve()
    if not path.is_file(): return
    config = settings_path(); saved = read_json(config)
    previous = saved.get(kind, [])
    if not isinstance(previous, list): previous = []
    saved[kind] = list(dict.fromkeys([str(path)]+[p for p in previous if isinstance(p,str)]))[:8]
    temp = config.with_name(config.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf8')
        os.replace(temp, config)
    except OSError:
        try: temp.unlink(missing_ok=True)
        except OSError: pass


# This is a fixed, read-only Windows script. It never launches shortcut targets.
WINDOWS_HINT_SCRIPT = r'''
$ErrorActionPreference='SilentlyContinue'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$rows=[System.Collections.Generic.List[object]]::new()
function Add-Hint($kind,$path,$source) {
    if($path) { $rows.Add([pscustomobject]@{kind=$kind;path=[string]$path;source=$source}) }
}
function App-Kind($name) {
    if($name -match '(?i)^tai(?:$|[\s\d._-])') { return 'tai' }
    if($name -match '(?i)^hindsight(?:$|[\s\d._-])') { return 'hindsight' }
}
$keys=@('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
foreach($item in (Get-ItemProperty $keys)) {
 $kind=App-Kind $item.DisplayName
 if($kind) { Add-Hint $kind $item.InstallLocation '安装登记'; Add-Hint $kind $item.DisplayIcon '安装登记' }
}
foreach($hive in @('HKCU:','HKLM:')) {
 foreach($exe in @('Tai.exe','hindsight.exe')) {
  $key=Get-ItemProperty "$hive\Software\Microsoft\Windows\CurrentVersion\App Paths\$exe"
  Add-Hint ($exe.Split('.')[0].ToLower()) $key.'(default)' '应用注册路径'
 }
 foreach($entry in (Get-ItemProperty "$hive\Software\Microsoft\Windows\CurrentVersion\Run")) {
  foreach($prop in $entry.PSObject.Properties) {
   if($prop.Value -is [string] -and $prop.Value -match '(?i)(?:^|[\\/"\s])(tai|hindsight)\.exe(?:["\s]|$)') {
    Add-Hint $Matches[1].ToLower() $prop.Value '开机启动项'
   }
  }
 }
}
$shell=New-Object -ComObject WScript.Shell
$folders=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('CommonDesktopDirectory'),
 [Environment]::GetFolderPath('StartMenu'),[Environment]::GetFolderPath('CommonStartMenu'),
 [Environment]::GetFolderPath('Recent')) | Where-Object {$_} | Select-Object -Unique
$count=0
foreach($folder in $folders) {
 foreach($link in (Get-ChildItem -LiteralPath $folder -Filter '*.lnk' -Recurse -File | Select-Object -First 1800)) {
  if(++$count -gt 4000) { break }
  $shortcut=$shell.CreateShortcut($link.FullName)
  $exe=[IO.Path]::GetFileName($shortcut.TargetPath)
  if($exe -match '(?i)^(tai|hindsight)\.exe$') { Add-Hint $Matches[1].ToLower() $shortcut.TargetPath '快捷方式' }
  elseif($link.BaseName -match '(?i)^(tai|hindsight)(?:$|[\s._-])') { Add-Hint $Matches[1].ToLower() $shortcut.TargetPath '最近访问' }
 }
}
ConvertTo-Json -InputObject @($rows.ToArray()) -Compress -Depth 3
'''


def windows_hints():
    if os.name != 'nt': return []
    try:
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',WINDOWS_HINT_SCRIPT],
            capture_output=True, encoding='utf-8-sig', errors='replace', timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: return []
        values = json.loads(result.stdout or '[]')
        if isinstance(values, dict): values = [values]
        return [(v['kind'], normalize_path(v['path']), v['source']) for v in values
                if isinstance(v,dict) and v.get('kind') in ('tai','hindsight') and isinstance(v.get('path'),str)]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired): return []


def shortcut_target(path):
    if os.name != 'nt': return None
    script = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $s=New-Object -ComObject WScript.Shell; $s.CreateShortcut($env:TAI_MIGRATOR_LINK).TargetPath"
    try:
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            env=dict(os.environ,TAI_MIGRATOR_LINK=str(path)), capture_output=True,
            encoding='utf-8-sig', errors='replace', timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        return normalize_path(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired): return None


def _seeds(kind, hints=None):
    seeds = []
    def add(path, source):
        if path: seeds.append((normalize_path(path), source))
    saved = read_json(settings_path()).get(kind, [])
    if isinstance(saved,list):
        for path in saved:
            if isinstance(path,str): add(path,'上次使用')
    if kind == 'hindsight':
        if os.getenv('HINDSIGHT_DATA_DIR','').strip(): add(os.environ['HINDSIGHT_DATA_DIR'],'Hindsight 环境配置')
        for root in config_roots(): add(root,'系统数据目录')
    for name,path in process_folders():
        if name == kind+'.exe': add(path,'运行中的程序')
    for app,path,source in (windows_hints() if hints is None else hints):
        if app == kind: add(path,source)
    appname = 'Tai' if kind == 'tai' else 'Hindsight'
    for key in ('APPDATA','LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)','ProgramData'):
        if os.getenv(key):
            add(Path(os.environ[key])/appname,'常见目录')
            add(Path(os.environ[key])/'Programs'/appname,'常见目录')
    # Portable distributions are often unpacked alongside this tool or on Desktop/Downloads.
    home = Path(os.getenv('USERPROFILE',str(Path.home())))
    for folder in (home/'Desktop',home/'Downloads',Path(sys.executable).parent if getattr(sys,'frozen',False) else Path.cwd()):
        try:
            for child in folder.iterdir():
                if child.is_dir() and re.match(r'^'+kind+r'(?:$|[\s\d._-])',child.name,re.I): add(child,'便携目录')
        except OSError: pass
    # Check familiar software containers on mounted local drives, without scanning a whole drive.
    if os.name == 'nt':
        for drive in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            if ctypes.windll.kernel32.GetDriveTypeW(drive+':\\') != 3: continue
            for container in ('Software','Apps','Tools','Portable','软件'):
                parent = Path(drive+':/')/container
                try:
                    for child in parent.iterdir():
                        if child.is_dir() and re.match(r'^'+kind+r'(?:$|[\s\d._-])',child.name,re.I): add(child,'便携目录')
                except OSError: pass
    return seeds


SKIP_FOLDERS = {'tai-migration-backups','backups','backup','.git','node_modules','__pycache__',
                '$recycle.bin','system volume information','windows','screenshots','cache','logs','target'}


def discover(kind, base=None, deep=False, cancel=None, progress=None, max_dirs=6000, max_seconds=15, hints=None):
    """Read-only discovery with a shared directory/time budget and cancellation."""
    if kind not in ('tai','hindsight'): raise ValueError('未知应用类型')
    result = Discovery(kind); table = 'AppModels' if kind == 'tai' else 'activities'
    found = {}; visited = set(); tested = set(); start = time.monotonic()
    selected = normalize_path(base) if base else None
    if selected and selected.suffix.lower() == '.lnk':
        selected = shortcut_target(selected)
        if not selected:
            result.warnings.append('无法读取此快捷方式，请选择程序文件或安装文件夹。'); return result
    explicit_file = bool(selected and selected.is_file() and selected.suffix.lower() not in ('.exe','.json'))
    if explicit_file:
        seeds=[(selected,'手动选择')]
    elif selected:
        root = selected.parent if selected.is_file() or selected.suffix.lower() in ('.exe','.json') else selected
        seeds=[(root,'所选文件夹')]
        # Hindsight stores configuration separately from its executable.
        if kind=='hindsight': seeds.extend((r,'系统数据目录') for r in config_roots())
    else: seeds=_seeds(kind,hints)
    queue=deque((p,source,0,7 if deep else (4 if selected else 2)) for p,source in seeds)
    def stopped():
        if cancel is not None and cancel.is_set(): result.cancelled=True; return True
        if result.scanned_dirs >= max_dirs or time.monotonic()-start >= max_seconds:
            result.limited=True; return True
        return False
    def inspect(path,source):
        key=str(path.resolve()).casefold()
        if key in found:
            if source not in found[key].sources: found[key].sources.append(source)
            return
        if key in tested: return
        tested.add(key); result.checked+=1
        if valid_db(path,table):
            stat=path.stat(); found[key]=Candidate(path.resolve(),[source],size=stat.st_size,modified=stat.st_mtime)
    while queue:
        if stopped(): break
        path,source,depth,limit=queue.popleft()
        try:
            if path.suffix.lower()=='.exe': path=path.parent
            if path.is_file(): inspect(path,source); continue
            key=str(path.resolve()).casefold()
            if key in visited or not path.is_dir(): continue
            visited.add(key); result.scanned_dirs+=1
            if progress and result.scanned_dirs%20==1: progress(result.scanned_dirs,str(path))
            if kind=='hindsight':
                custom=read_json(path/'bootstrap.json').get('data_path')
                if isinstance(custom,str) and custom.strip():
                    custom_path=normalize_path(custom)
                    if custom_path.is_absolute(): queue.appendleft((custom_path,'Hindsight 自定义目录',0,2))
                    else: result.warnings.append('发现相对数据路径；请选择 Hindsight 实际使用的数据文件夹。')
            # Read only names here; schema validation distinguishes main/foreign databases.
            with os.scandir(path) as entries:
                for entry in entries:
                    if cancel is not None and cancel.is_set(): result.cancelled=True; break
                    if time.monotonic()-start >= max_seconds: result.limited=True; break
                    name=entry.name.casefold()
                    if entry.is_file(follow_symlinks=False):
                        extension=Path(name).suffix
                        if extension in ('.db','.sqlite','.sqlite3') and (
                            kind=='tai' and (selected is not None or name in ('data.db','tai.db')) or
                            kind=='hindsight' and (selected is not None or name.startswith('hindsight'))):
                            inspect(Path(entry.path),source)
                    elif depth<limit and entry.is_dir(follow_symlinks=False) and name not in SKIP_FOLDERS:
                        # Junctions can escape the selected folder or form cycles.
                        if entry.is_symlink() or (hasattr(os.path,'isjunction') and os.path.isjunction(entry.path)): continue
                        queue.append((Path(entry.path),source,depth+1,limit))
            if result.cancelled or result.limited: break
        except (OSError,ValueError): continue
    candidates=list(found.values())
    if kind=='hindsight':
        roots=config_roots()
        uids={uid for root in roots if (uid:=parse_active_user(root))}
        desired=('hindsight.'+next(iter(uids))+'.sqlite') if len(uids)==1 else None
        for candidate in candidates:
            candidate.active = desired is not None and candidate.path.name.casefold()==desired.casefold()
            candidate.account = (candidate.path.stem[len('hindsight.'):] if candidate.path.stem.startswith('hindsight.') else '本地 / 未登录')
    result.candidates=sorted(candidates,key=lambda c:(not c.active,0 if '手动选择' in c.sources else 1,str(c.path).casefold()))
    if result.limited: result.warnings.append('扫描达到时间或目录上限。可选择更接近安装位置的文件夹继续扫描。')
    return result


def locate_tai(base=None):
    return [c.path for c in discover('tai',base).candidates]


def locate_hindsight_candidates(base=None):
    return [c.path for c in discover('hindsight',base).candidates]


def choose_hindsight(candidates, config_dir=None):
    candidates=[Path(p) for p in candidates]
    if len(candidates)==1: return candidates[0],candidates,'已找到 Hindsight 数据库，请核对路径'
    if len(candidates)>1:
        roots=[Path(config_dir)] if config_dir else config_roots()
        uids={uid for root in roots if (uid:=parse_active_user(root))}
        if len(uids)==1:
            desired='hindsight.'+next(iter(uids))+'.sqlite'
            matches=[p for p in candidates if p.name.casefold()==desired.casefold()]
            if len(matches)==1: return matches[0],candidates,'已匹配当前账号，请核对路径'
        # Multiple or conflicting identities must always be explicitly reviewed.
        return None,candidates,'发现多个数据库，请选择当前账号使用的主数据库'
    return None,[],'未找到数据库，可扫描安装文件夹或选择程序快捷方式'
