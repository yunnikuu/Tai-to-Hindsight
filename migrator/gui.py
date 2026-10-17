"""Focused native desktop workflow. All database work runs off the Tk thread."""
from __future__ import annotations
import os
import queue
import tempfile
import threading
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, ttk
from .dialogs import messages as messagebox, LocationDialog
import customtkinter as ctk
from .core import Options, MigrationError, inspect_plan, migrate, restore_backup
from . import locator

BG='#F7F8FA'; INK='#172C43'; MUTED='#69788A'; LINE='#DCE3EC'; TEAL='#238777'; AMBER='#D79536'
FONT='Microsoft YaHei UI'

def elapsed(seconds):
    sign='−' if seconds<0 else ''
    seconds=abs(int(seconds)); h,rem=divmod(seconds,3600); m,s=divmod(rem,60)
    if h: return f'{sign}{h} 小时 {m:02d} 分'
    return f'{sign}{m} 分 {s:02d} 秒'

class App(ctk.CTk):
    def __init__(self,demo=False):
        ctk.set_appearance_mode('light'); ctk.set_default_color_theme('blue')
        super().__init__()
        self.title('Tai → Hindsight · 数据迁移')
        self.geometry('1120x820'); self.minsize(1010,760); self.configure(fg_color=BG)
        self.plan=None; self.result=None; self.busy=False; self.demo=demo; self.demo_dir=None
        self.events=queue.Queue(); self.cancel_event=threading.Event(); self.controls=[]
        self.path_entries={}; self.discovery_results={}; self.discovery_interactive=False
        self.source=tk.StringVar(); self.target=tk.StringVar(); self.start=tk.StringVar(); self.end=tk.StringVar()
        self.zone=tk.StringVar(value='Asia/Shanghai'); self.categories=tk.BooleanVar(value=True)
        self.daily=tk.BooleanVar(value=True); self.overlap=tk.StringVar(value='跳过重叠小时（推荐）')
        self.stage=tk.StringVar(value='选择两个数据库，然后预览迁移内容。')
        self.build(); self.protocol('WM_DELETE_WINDOW',self.close)
        for var in (self.source,self.target,self.start,self.end,self.zone,self.categories,self.daily,self.overlap):
            var.trace_add('write',self.invalidate)
        self.after(100,self.poll)
        self.after(200,self.load_demo if demo else self.detect_all)
        icon=Path(__file__).parent/'assets'/'app.ico'
        if icon.exists(): self.iconbitmap(str(icon))

    def label(self,parent,text,size=13,bold=False,color=INK,**kw):
        return ctk.CTkLabel(parent,text=text,font=(FONT,size,'bold' if bold else 'normal'),text_color=color,**kw)

    def button(self,parent,text,command,width=90,primary=False,**kw):
        b=ctk.CTkButton(parent,text=text,command=command,width=width,height=34,corner_radius=6,
            font=(FONT,12),fg_color=TEAL if primary else '#EEF2F6',hover_color='#1C7063' if primary else '#E0E7EF',
            text_color='white' if primary else INK,**kw)
        self.controls.append(b); return b

    def build(self):
        self.grid_columnconfigure(0,weight=1); self.grid_rowconfigure(1,weight=1)
        head=ctk.CTkFrame(self,fg_color=INK,corner_radius=0,height=92)
        head.grid(row=0,column=0,sticky='ew'); head.grid_propagate(False)
        brand=ctk.CTkFrame(head,fg_color='transparent'); brand.pack(side='left',padx=28,pady=16)
        self.label(brand,'Tai',25,True,AMBER).pack(side='left')
        self.label(brand,'  →  ',22,color='#9CAEC0').pack(side='left')
        self.label(brand,'Hindsight',25,True,'#8AD3C4').pack(side='left')
        self.label(head,'应用使用记录迁移',15,True,'white').pack(side='left',padx=12)
        self.label(head,'离线工具  /  v1.1.0',12,color='#BAC7D4').pack(side='right',padx=28)
        body=ctk.CTkFrame(self,fg_color='transparent'); body.grid(row=1,column=0,sticky='nsew',padx=24,pady=(20,12))
        body.grid_columnconfigure(0,weight=1); body.grid_columnconfigure(1,weight=0,minsize=240); body.grid_rowconfigure(0,weight=1)
        left=ctk.CTkFrame(body,fg_color='transparent'); left.grid(row=0,column=0,sticky='nsew',padx=(0,20))
        left.grid_columnconfigure(0,weight=1); left.grid_rowconfigure(3,weight=1)
        paths=ctk.CTkFrame(left,fg_color='white',border_width=1,border_color=LINE,corner_radius=8)
        paths.grid(row=0,column=0,sticky='ew'); paths.grid_columnconfigure(0,weight=1)
        self.path_row(paths,0,'Tai · 来源',AMBER,self.source,'智能定位支持快捷方式、程序文件与便携目录；来源只读。','tai')
        self.path_row(paths,1,'Hindsight · 目标',TEAL,self.target,'识别自定义目录与当前账号；请核对目标数据库。','hindsight')
        filters=ctk.CTkFrame(left,fg_color='transparent'); filters.grid(row=1,column=0,sticky='ew',pady=(16,8))
        self.label(filters,'迁移范围',14,True).grid(row=0,column=0,sticky='w',columnspan=4,pady=(0,7))
        dates=ctk.CTkFrame(filters,fg_color='transparent'); dates.grid(row=1,column=0,sticky='w',columnspan=4)
        self.label(dates,'日期').pack(side='left',padx=(0,8))
        for var,placeholder in ((self.start,'起始 YYYY-MM-DD'),(self.end,'结束 YYYY-MM-DD')):
            e=ctk.CTkEntry(dates,textvariable=var,placeholder_text=placeholder,width=154,height=32,font=(FONT,12),border_color=LINE,fg_color='white')
            e.pack(side='left',padx=(0,8)); self.controls.append(e)
        self.label(dates,'YYYY-MM-DD · 留空为全部',11,color=MUTED).pack(side='left')
        self.button(dates,'清空',lambda:(self.start.set(''),self.end.set('')),width=55).pack(side='left',padx=8)
        opts=ctk.CTkFrame(filters,fg_color='transparent'); opts.grid(row=2,column=0,sticky='w',columnspan=4,pady=(10,0))
        for text,var in (('保留应用分类',self.categories),('用每日汇总补齐缺失时长',self.daily)):
            c=ctk.CTkCheckBox(opts,text=text,variable=var,font=(FONT,12),fg_color=TEAL,hover_color=TEAL,border_color='#A3B2C2',checkbox_width=17,checkbox_height=17)
            c.pack(side='left',padx=(0,20)); self.controls.append(c)
        advanced=ctk.CTkFrame(filters,fg_color='transparent'); advanced.grid(row=3,column=0,sticky='ew',columnspan=4,pady=(10,0))
        self.label(advanced,'重叠处理',12,color=MUTED).pack(side='left',padx=(0,8))
        menu=ctk.CTkOptionMenu(advanced,variable=self.overlap,values=['跳过重叠小时（推荐）','仍然导入（可能重复计时）'],width=222,height=30,font=(FONT,11),dropdown_font=(FONT,12),fg_color='#E8EEF3',button_color='#D3DDE6',button_hover_color='#BACBD7',text_color=INK)
        menu.pack(side='left'); self.controls.append(menu)
        self.label(advanced,'时区',12,color=MUTED).pack(side='left',padx=(14,8))
        z=ctk.CTkEntry(advanced,textvariable=self.zone,width=160,height=30,font=(FONT,11),border_color=LINE,fg_color='white'); z.pack(side='left'); self.controls.append(z)
        title=ctk.CTkFrame(left,fg_color='transparent'); title.grid(row=2,column=0,sticky='ew',pady=(10,7))
        self.label(title,'迁移预览',14,True).pack(side='left')
        self.preview_note=self.label(title,'预览后才会启用迁移',11,color=MUTED); self.preview_note.pack(side='right')
        tablebox=ctk.CTkFrame(left,fg_color='white',border_width=1,border_color=LINE,corner_radius=6)
        tablebox.grid(row=3,column=0,sticky='nsew'); tablebox.grid_columnconfigure(0,weight=1); tablebox.grid_rowconfigure(0,weight=1)
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('Migration.Treeview',font=(FONT,10),rowheight=36,background='white',fieldbackground='white',foreground=INK,borderwidth=0)
        style.configure('Migration.Treeview.Heading',font=(FONT,10,'bold'),background='#EDF2F6',foreground=MUTED,relief='flat',padding=(8,9))
        style.map('Migration.Treeview',background=[('selected','#DEF0EA')],foreground=[('selected',INK)])
        cols=('app','source','delta','state'); self.tree=ttk.Treeview(tablebox,columns=cols,show='headings',style='Migration.Treeview',selectmode='browse')
        for col,text,width in zip(cols,('应用 / 进程','来源时长','本次增量','处理结果'),(210,118,118,145)):
            self.tree.heading(col,text=text); self.tree.column(col,width=width,minwidth=75,anchor='w' if col=='app' else 'center',stretch=col=='app')
        self.tree.grid(row=0,column=0,sticky='nsew',padx=1,pady=1)
        scroll=ttk.Scrollbar(tablebox,orient='vertical',command=self.tree.yview); scroll.grid(row=0,column=1,sticky='ns'); self.tree.configure(yscrollcommand=scroll.set)
        self.empty_note=self.label(tablebox,'尚未预览\n选择来源和目标后点击“预览”',12,color=MUTED,justify='center')
        self.empty_note.grid(row=0,column=0,sticky='nsew',padx=12,pady=12)
        self.tree.tag_configure('alternate',background='#F8FAFC')
        self.tree.bind('<<TreeviewSelect>>',self.app_detail)
        self.selection_note=self.label(left,'此处将按应用显示使用时长与导入结果。',11,color=MUTED,anchor='w')
        self.selection_note.grid(row=4,column=0,sticky='ew',pady=(7,0))
        right=ctk.CTkFrame(body,width=240,fg_color='#EDF2F6',corner_radius=8)
        right.grid(row=0,column=1,sticky='nsew'); right.grid_propagate(False); right.grid_columnconfigure(0,weight=1); right.grid_rowconfigure(6,weight=1)
        self.label(right,'本次迁移',15,True,anchor='w').grid(row=0,column=0,sticky='ew',padx=18,pady=(18,14))
        self.summary=self.label(right,'等待预览',22,True,TEAL,anchor='w'); self.summary.grid(row=1,column=0,sticky='ew',padx=18)
        self.range_label=self.label(right,'选择数据后计算日期范围',11,color=MUTED,anchor='w'); self.range_label.grid(row=2,column=0,sticky='ew',padx=18,pady=(5,14))
        self.counts=self.label(right,'新增  —\n更新  —\n重复  —\n重叠  —',12,color=INK,anchor='w',justify='left'); self.counts.grid(row=3,column=0,sticky='ew',padx=18,pady=(0,14))
        ctk.CTkFrame(right,height=1,fg_color='#D3DDE6').grid(row=4,column=0,sticky='ew',padx=18)
        self.label(right,'迁移说明',13,True,anchor='w').grid(row=5,column=0,sticky='ew',padx=18,pady=(14,8))
        self.notes=ctk.CTkTextbox(right,fg_color='transparent',text_color=MUTED,font=(FONT,12),wrap='word',border_width=0,activate_scrollbars=True)
        self.notes.grid(row=6,column=0,sticky='nsew',padx=12,pady=(0,8))
        self.set_notes(['Tai 只保留小时 / 日汇总。迁移后的时间段为重建值，不能还原真实会话。','迁移前请完全退出两个软件，包括托盘。','只写入本机数据库，不主动上传云端。'])
        links=ctk.CTkFrame(right,fg_color='transparent'); links.grid(row=7,column=0,sticky='ew',padx=18,pady=(0,16))
        self.button(links,'备份与报告',self.open_backups,width=200).pack(fill='x',pady=(0,7))
        self.restore_btn=self.button(links,'从备份恢复…',self.restore,width=200); self.restore_btn.pack(fill='x',pady=(0,7))
        self.button(links,'使用说明',self.help,width=200).pack(fill='x')
        footer=ctk.CTkFrame(self,fg_color='white',corner_radius=0,border_width=1,border_color=LINE)
        footer.grid(row=2,column=0,sticky='ew'); footer.grid_columnconfigure(0,weight=1)
        self.status_label=ctk.CTkLabel(footer,textvariable=self.stage,font=(FONT,12),text_color=MUTED,anchor='w',wraplength=690,justify='left')
        self.status_label.grid(row=0,column=0,sticky='ew',padx=24,pady=(13,4))
        self.bar=ctk.CTkProgressBar(footer,height=4,progress_color=TEAL,fg_color='#E5EBF1'); self.bar.grid(row=1,column=0,sticky='ew',padx=24,pady=(0,14)); self.bar.set(0)
        actions=ctk.CTkFrame(footer,fg_color='transparent'); actions.grid(row=0,column=1,rowspan=2,padx=(0,24),pady=15)
        self.cancel_btn=self.button(actions,'取消',self.cancel,width=65); self.cancel_btn.pack(side='left',padx=(0,8)); self.cancel_btn.configure(state='disabled')
        self.preview_btn=self.button(actions,'预览',self.preview,width=82); self.preview_btn.pack(side='left',padx=(0,8))
        self.migrate_btn=self.button(actions,'开始迁移',self.start_migration,width=120,primary=True); self.migrate_btn.pack(side='left'); self.migrate_btn.configure(state='disabled')

    def path_row(self,parent,row,title,color,var,hint,kind):
        f=ctk.CTkFrame(parent,fg_color='transparent'); f.grid(row=row,column=0,sticky='ew',padx=16,pady=(12,10)); f.grid_columnconfigure(0,weight=1)
        self.label(f,title,13,True,color,anchor='w').grid(row=0,column=0,sticky='w',pady=(0,6))
        buttons=ctk.CTkFrame(f,fg_color='transparent'); buttons.grid(row=0,column=1,rowspan=2,sticky='e',padx=(8,0))
        self.button(buttons,'智能定位',lambda:self.detect(kind),width=78).pack(side='left',padx=(0,5))
        self.button(buttons,'文件…',lambda:self.browse(kind,False),width=58).pack(side='left',padx=(0,5))
        self.button(buttons,'扫描…',lambda:self.browse(kind,True),width=58).pack(side='left')
        e=ctk.CTkEntry(f,textvariable=var,height=33,font=(FONT,11),fg_color=BG,border_color=LINE); e.grid(row=1,column=0,sticky='ew'); self.controls.append(e); self.path_entries[kind]=e
        e.bind('<Return>',lambda _:self.detect(kind,var.get().strip()) if var.get().strip() else self.detect(kind))
        self.label(f,hint,11,color=MUTED,anchor='w').grid(row=2,column=0,columnspan=2,sticky='ew',pady=(5,0))

    def set_notes(self,items):
        self.notes.configure(state='normal'); self.notes.delete('1.0','end'); self.notes.insert('1.0','\n\n'.join(items)); self.notes.configure(state='disabled')

    def invalidate(self,*_):
        self.plan=None
        if hasattr(self,'migrate_btn'): self.migrate_btn.configure(state='disabled')
        if hasattr(self,'preview_note'): self.preview_note.configure(text='参数已变更，请重新预览')
        if hasattr(self,'tree'):
            for i in self.tree.get_children(): self.tree.delete(i)
            self.empty_note.grid()
            self.summary.configure(text='等待预览'); self.range_label.configure(text='参数变更后需要重新预览'); self.counts.configure(text='新增  —\n更新  —\n重复  —\n重叠  —')

    def lock(self,value,cancellable=False):
        self.busy=value
        for widget in self.controls: widget.configure(state='disabled' if value else 'normal')
        if self.demo and not value:
            for entry in self.path_entries.values(): entry.configure(state='disabled')
        self.cancel_btn.configure(state='normal' if value and cancellable else 'disabled')
        self.migrate_btn.configure(state='normal' if not value and self.plan and self.plan.pending else 'disabled')

    def guard_demo_paths(self):
        if not self.demo:
            return
        root=Path(self.demo_dir.name).resolve() if self.demo_dir else None
        if not root:
            raise MigrationError('示例临时目录不可用，请重新启动示例模式。')
        for label,path in (('Tai 来源',self.source.get()),('Hindsight 目标',self.target.get())):
            candidate=Path(path.strip().strip('\"')).resolve()
            if candidate != root and root not in candidate.parents:
                raise MigrationError(f'示例模式拒绝访问临时目录外的{label}。请重新启动示例模式。')

    def run(self,name,work,cancellable=False):
        if self.busy: return
        self.lock(True,cancellable); self.cancel_event.clear(); self.stage.set(name); self.bar.set(0)
        def execute():
            try: self.events.put(('done',name,work()))
            except Exception as exc: self.events.put(('error',name,exc))
        threading.Thread(target=execute,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,name,value=self.events.get_nowait()
                if kind=='progress': self.bar.set(name); self.stage.set(value); continue
                self.lock(False)
                if kind=='error':
                    self.stage.set(str(value)); self.invalidate(); messagebox.showerror('操作未完成',str(value),parent=self); continue
                if name=='正在读取并核对数据库…': self.show_plan(value)
                elif name=='正在迁移…': self.finished(value)
                elif name=='正在恢复备份…':
                    self.invalidate(); self.bar.set(1); self.stage.set('已恢复备份。恢复前的数据已另存为安全备份。')
                    messagebox.showinfo('恢复完成',f'已恢复到所选备份。\n\n恢复前安全备份：\n{value}',parent=self)
                else:
                    summaries=[]
                    for which,result in value:
                        self.discovery_results[which]=result
                        app='Tai' if which=='tai' else 'Hindsight'
                        summaries.append(f'{app}：找到 {len(result.candidates)} 个数据库')
                        self.select_path(which,result,self.discovery_interactive)
                    self.bar.set(1)
                    self.stage.set('；'.join(summaries)+'。可用“智能定位”查看结果，或扫描文件夹。')
        except queue.Empty: pass
        self.after(100,self.poll)

    def detect_all(self):
        if self.demo: return
        if not self.source.get() and not self.target.get():
            self.discovery_interactive=False
            def work():
                hints=locator.windows_hints()
                return [(kind,locator.discover(kind,cancel=self.cancel_event,hints=hints)) for kind in ('tai','hindsight')]
            self.run('正在检测数据位置…',work,True)

    def detect(self,kind,base=None,deep=False):
        if self.demo:
            messagebox.showinfo('示例模式','示例模式只操作临时合成数据库。请关闭后正常启动程序来定位真实数据。',parent=self); return
        if self.busy: return
        self.discovery_interactive=True
        def progress(count,path):
            self.events.put(('progress',min(.9,count/6000),f'正在定位 · 已检查 {count} 个目录…'))
        self.run('正在扫描所选文件夹…' if deep else '正在检测数据位置…',
            lambda:[(kind,locator.discover(kind,base,deep=deep,cancel=self.cancel_event,progress=progress))],True)

    def select_path(self,kind,result,interactive=True):
        var=self.source if kind=='tai' else self.target
        paths=[candidate.path for candidate in result.candidates]
        if not interactive:
            chosen=paths[0] if len(paths)==1 else None
            if kind=='hindsight' and len(paths)>1: chosen,_,_=locator.choose_hindsight(paths)
            if chosen: var.set(str(chosen))
            return
        choice=LocationDialog(self,result).show()
        if not choice: return
        action,path=choice
        if action=='choose':
            var.set(path)
            if not self.demo: locator.remember_path(kind,path)
        elif action=='scan': self.after(20,lambda:self.browse(kind,True))
        elif action=='file': self.after(20,lambda:self.browse(kind,False))

    def browse(self,kind,folder):
        if self.demo:
            messagebox.showinfo('示例模式','示例模式只操作临时合成数据库。请关闭后正常启动程序来选择真实数据。',parent=self); return
        current=(self.source if kind=='tai' else self.target).get().strip()
        initial=locator.normalize_path(current) if current else Path.home()
        if initial.is_file(): initial=initial.parent
        if not initial.is_dir(): initial=Path.home()
        if folder:
            path=filedialog.askdirectory(title='选择要扫描的文件夹（可选择软件目录或解压位置）',initialdir=str(initial),parent=self)
            if path: self.detect(kind,path,deep=True)
        else:
            path=filedialog.askopenfilename(title='选择数据库、程序、快捷方式或 Hindsight 配置文件',initialdir=str(initial),parent=self,
                filetypes=[('数据库 / 程序 / 快捷方式','*.db *.sqlite *.sqlite3 *.exe *.lnk *.json'),('所有文件','*.*')])
            if path: self.detect(kind,path)

    def preview(self):
        source=self.source.get().strip().strip('"'); target=self.target.get().strip().strip('"')
        if not source or not target:
            messagebox.showinfo('需要两个数据库','请先定位 Tai 来源和 Hindsight 目标数据库。',parent=self); return
        try: self.guard_demo_paths()
        except MigrationError as exc:
            messagebox.showerror('示例模式已阻止',str(exc),parent=self); return
        opts=Options(self.start.get().strip(),self.end.get().strip(),self.zone.get().strip(),self.categories.get(),self.daily.get(),'skip' if self.overlap.get().startswith('跳过') else 'import')
        def work():
            if not self.demo: locator.ensure_closed()
            return inspect_plan(source,target,opts)
        self.run('正在读取并核对数据库…',work)

    def show_plan(self,plan):
        self.plan=plan
        if not self.demo:
            locator.remember_path('tai',plan.source); locator.remember_path('hindsight',plan.target)
        for i in self.tree.get_children(): self.tree.delete(i)
        self.empty_note.grid_remove()
        groups=defaultdict(list)
        for r in plan.records: groups[r.process].append(r)
        self.app_details={}
        for index,(process,records) in enumerate(sorted(groups.items(),key=lambda item:-sum(r.seconds for r in item[1]))):
            total=sum(r.seconds for r in records); delta=sum(r.seconds-r.old_seconds for r in records if r.action in ('new','update'))
            n=sum(r.action=='new' for r in records); u=sum(r.action=='update' for r in records); same=sum(r.action=='same' for r in records); conflict=sum(r.action=='conflict' for r in records)
            states=[]
            if n: states.append(f'新增 {n}')
            if u: states.append(f'更新 {u}')
            if same: states.append(f'重复 {same}')
            if conflict: states.append(f'跳过 {conflict}')
            item=self.tree.insert('', 'end', values=(records[0].display,elapsed(total),elapsed(delta),' · '.join(states)),tags=('alternate',) if index%2 else ())
            self.app_details[item]=f'{process}  ·  {len(records)} 个小时记录  ·  {records[0].category or "未分类"}'
        self.summary.configure(text=elapsed(plan.delta_seconds))
        first,last=plan.date_range; self.range_label.configure(text=f'{first} → {last}' if first else '范围内没有使用记录')
        self.counts.configure(text=f'新增  {plan.new} 个小时记录\n更新  {plan.updated} 个小时记录\n重复  {plan.unchanged} 个小时记录\n重叠  {plan.conflicts} 个小时记录')
        self.preview_note.configure(text=f'{plan.app_count} 个应用 · 目标已有 {plan.target_count} 条')
        self.selection_note.configure(text='点击应用可查看进程名与分类。')
        self.set_notes(plan.warnings)
        self.stage.set('预览完成。确认路径与统计后即可迁移。' if plan.pending else '无需迁移：范围内无新数据，或记录均重复 / 重叠。')
        if self.demo: self.stage.set('合成示例模式：所有操作仅作用于临时示例数据库。')
        self.bar.set(1); self.lock(False)

    def app_detail(self,_):
        selected=self.tree.selection()
        if selected: self.selection_note.configure(text=self.app_details.get(selected[0],''))

    def start_migration(self):
        if not self.plan or self.busy: return
        try: self.guard_demo_paths()
        except MigrationError as exc:
            messagebox.showerror('示例模式已阻止',str(exc),parent=self); return
        plan=self.plan
        if not messagebox.askyesno('确认迁移',f'目标：{plan.target}\n\n新增 {plan.new} 条，更新 {plan.updated} 条\n净增加时长：{elapsed(plan.delta_seconds)}\n\n写入前自动备份。时间段为小时汇总的重建值。\n请确认目标账号正确，并已退出两个软件。',parent=self): return
        def work():
            if not self.demo: locator.ensure_closed()
            return migrate(plan,lambda p,t:self.events.put(('progress',p,t)),self.cancel_event)
        self.run('正在迁移…',work,True)

    def finished(self,result):
        self.result=result; self.plan=None; self.bar.set(1); self.migrate_btn.configure(state='disabled')
        self.stage.set(f'迁移完成：新增 {result.new} 条，更新 {result.updated} 条。备份和报告已保存。')
        self.preview_note.configure(text='已完成 · 可再次预览核对重复记录')
        self.set_notes(['迁移已完成。重新打开 Hindsight，选择本机设备与对应日期查看。',f'备份：\n{result.backup}',f'报告：\n{result.report}']+result.warnings)
        messagebox.showinfo('迁移完成',f'新增 {result.new} 条，更新 {result.updated} 条。\n净增加：{elapsed(result.seconds_added)}\n\n已保存自动备份与迁移报告。\n重新预览可确认不会重复计时。',parent=self)

    def cancel(self):
        self.cancel_event.set(); self.cancel_btn.configure(state='disabled'); self.stage.set('正在停止定位或取消操作；提交前会撤销当前迁移事务…')

    def restore(self):
        target=self.target.get().strip().strip('"')
        if not target: messagebox.showinfo('选择目标','请先选择需要恢复的 Hindsight 数据库。',parent=self); return
        try: self.guard_demo_paths()
        except MigrationError as exc:
            messagebox.showerror('示例模式已阻止',str(exc),parent=self); return
        initial=Path(target).parent/'tai-migration-backups'
        backup=filedialog.askopenfilename(title='选择本工具生成的备份（保留同名 .json 校验文件）',initialdir=str(initial) if initial.exists() else str(Path(target).parent),filetypes=[('迁移备份','*.sqlite')],parent=self)
        if not backup: return
        if not messagebox.askyesno('恢复整个数据库',f'恢复会将整个目标数据库还原到所选备份时刻。\n备份之后的全部变化都会撤回。\n\n目标：{target}\n备份：{backup}\n\n恢复前还会生成一份安全备份。继续？',parent=self): return
        def work():
            if not self.demo: locator.ensure_closed()
            return restore_backup(target,backup)
        self.run('正在恢复备份…',work)

    def open_backups(self):
        folder=Path(self.target.get().strip().strip('"')).parent/'tai-migration-backups' if self.target.get() else None
        if folder and folder.is_dir(): os.startfile(str(folder))
        else: messagebox.showinfo('备份与报告','第一次迁移成功后，备份、SHA-256 校验文件和 JSON 报告将保存在目标数据库旁的 tai-migration-backups 文件夹。',parent=self)

    def help(self):
        messagebox.showinfo('使用说明',
            '1. 点击“智能定位”，可从快捷方式、安装登记、运行进程与上次路径查找。\n2. 找不到时扫描软件所在文件夹；也可选择程序或 .lnk 快捷方式。定位时可保持软件运行，预览前请退出两个软件与托盘进程。\n3. 设置日期范围，点击预览，核对每个应用的时长。\n4. 点击开始迁移，完成后重新打开 Hindsight 查看本机记录。\n\nTai 通常位于安装目录的 Data/data.db。\nHindsight 通常位于 %APPDATA%/Hindsight；支持 HINDSIGHT_DATA_DIR 与 bootstrap.json 自定义路径。多账号请核对 hindsight.<uid>.sqlite。\n\n时区应与 Tai 记录时的电脑时区一致。小时汇总会从整点重建；每日补齐从当天可用小时放置，可取消勾选。重叠按同进程、同设备、同小时保守跳过，跳过可能遗漏该小时部分时长。\n\n不迁移截图、真实窗口标题或网站记录；不主动同步到云端。备份恢复会撤回备份后的全部数据库变化。\n\n本工具独立开发，与 Tai、Hindsight 官方无隶属关系。',parent=self)

    def load_demo(self):
        from .demo import make_demo
        self.demo_dir=tempfile.TemporaryDirectory(prefix='tai-hindsight-demo-')
        src,dst=make_demo(self.demo_dir.name); self.source.set(str(src)); self.target.set(str(dst)); self.preview()

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中','请等待当前操作完成。迁移期间可使用“取消”按钮。',parent=self); return
        self.destroy()
        if self.demo_dir: self.demo_dir.cleanup()
