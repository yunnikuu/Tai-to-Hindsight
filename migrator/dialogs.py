"""Shared modal styling for discovery, confirmations and operation feedback."""
from __future__ import annotations
from datetime import datetime
import tkinter as tk
import customtkinter as ctk

BG='#F7F8FA'; INK='#172C43'; MUTED='#69788A'; LINE='#DCE3EC'; TEAL='#238777'; AMBER='#D79536'
FONT='Microsoft YaHei UI'


def label(parent,text,size=13,bold=False,color=INK,**kwargs):
    return ctk.CTkLabel(parent,text=text,font=(FONT,size,'bold' if bold else 'normal'),text_color=color,**kwargs)


def button(parent,text,command,primary=False,**kwargs):
    return ctk.CTkButton(parent,text=text,command=command,height=36,corner_radius=6,
        font=(FONT,12),fg_color=TEAL if primary else '#E9EEF3',
        hover_color='#1C7063' if primary else '#DCE4ED',text_color='white' if primary else INK,**kwargs)


class Modal(ctk.CTkToplevel):
    def __init__(self,parent,title,width=740,height=540):
        super().__init__(parent)
        self.withdraw(); self.title(title); self.configure(fg_color=BG)
        self.transient(parent); self.result=None
        self.geometry(f'{width}x{height}'); self.minsize(min(width,600),min(height,420))
        self.grid_columnconfigure(0,weight=1); self.grid_rowconfigure(1,weight=1)
        self.protocol('WM_DELETE_WINDOW',self.dismiss)
        self.bind('<Escape>',lambda _:self.dismiss())
        self.parent=parent

    def show(self):
        self.update_idletasks()
        x=max(0,self.parent.winfo_rootx()+(self.parent.winfo_width()-self.winfo_width())//2)
        y=max(0,self.parent.winfo_rooty()+(self.parent.winfo_height()-self.winfo_height())//2)
        self.geometry(f'+{x}+{y}'); self.deiconify(); self.wait_visibility()
        self.grab_set(); self.focus_set(); self.wait_window()
        return self.result

    def dismiss(self,result=None):
        self.result=result
        self.grab_release(); self.destroy()

    def copy(self,text,control):
        self.clipboard_clear(); self.clipboard_append(text)
        control.configure(text='已复制')
        self.after(1400,lambda:control.configure(text='复制内容') if control.winfo_exists() else None)


class MessageDialog(Modal):
    def __init__(self,parent,title,message,kind='info',confirm=False):
        super().__init__(parent,title,width=700,height=500 if len(message)>260 else 440)
        accent={'error':'#B54740','confirm':AMBER,'info':TEAL}[kind]
        header=ctk.CTkFrame(self,fg_color='white',corner_radius=0)
        header.grid(row=0,column=0,sticky='ew'); header.grid_columnconfigure(1,weight=1)
        badge=ctk.CTkFrame(header,width=40,height=40,fg_color=accent,corner_radius=10)
        badge.grid(row=0,column=0,rowspan=2,padx=(24,14),pady=22); badge.grid_propagate(False)
        label(badge,'!' if kind!='info' else '✓',22,True,'white').place(relx=.5,rely=.5,anchor='center')
        label(header,title,19,True,anchor='w').grid(row=0,column=1,sticky='ew',padx=(0,24),pady=(21,0))
        label(header,'请核对后继续' if confirm else ('调整后可重新操作' if kind=='error' else 'Tai → Hindsight'),11,color=MUTED,anchor='w').grid(row=1,column=1,sticky='ew',pady=(0,19))
        content=ctk.CTkTextbox(self,fg_color='white',border_width=1,border_color=LINE,
            corner_radius=8,font=(FONT,13),text_color=INK,wrap='word',spacing3=7)
        content.grid(row=1,column=0,sticky='nsew',padx=24,pady=20)
        content.insert('1.0',message); content.configure(state='disabled')
        footer=ctk.CTkFrame(self,fg_color='transparent'); footer.grid(row=2,column=0,sticky='ew',padx=24,pady=(0,20))
        copy=button(footer,'复制内容',lambda:None,width=90); copy.configure(command=lambda:self.copy(message,copy)); copy.pack(side='left')
        if confirm:
            action={'确认迁移':'开始迁移','恢复整个数据库':'恢复备份'}.get(title,'确认继续')
            button(footer,action,lambda:self.dismiss(True),primary=True,width=116).pack(side='right')
            cancel=button(footer,'取消',lambda:self.dismiss(False),width=90); cancel.pack(side='right',padx=(0,8)); cancel.focus_set()
        else:
            close=button(footer,'知道了',lambda:self.dismiss(True),primary=True,width=100); close.pack(side='right')
            self.bind('<Return>',lambda _:self.dismiss(True))


class Messages:
    @staticmethod
    def showinfo(title,message,parent): return MessageDialog(parent,title,message).show()
    @staticmethod
    def showerror(title,message,parent): return MessageDialog(parent,title,message,kind='error').show()
    @staticmethod
    def askyesno(title,message,parent): return bool(MessageDialog(parent,title,message,kind='confirm',confirm=True).show())


messages=Messages()


class LocationDialog(Modal):
    def __init__(self,parent,result):
        self.discovery=result; self.kind=result.kind
        app='Tai' if result.kind=='tai' else 'Hindsight'
        super().__init__(parent,f'定位 {app} 数据库',width=850,height=650)
        self.selected=tk.StringVar(value=str(result.candidates[0].path) if result.candidates else '')
        self.filter=tk.StringVar()
        header=ctk.CTkFrame(self,fg_color=INK,corner_radius=0); header.grid(row=0,column=0,sticky='ew')
        label(header,f'定位 {app} 数据库',21,True,'white',anchor='w').pack(fill='x',padx=26,pady=(21,3))
        subtitle=(f'找到 {len(result.candidates)} 个数据库 · 选择后填入主界面' if result.candidates else '未找到可识别的数据库 · 可以继续扫描或手动选择')
        label(header,subtitle,12,color='#C6D4DF',anchor='w').pack(fill='x',padx=26,pady=(0,21))
        body=ctk.CTkFrame(self,fg_color='transparent'); body.grid(row=1,column=0,sticky='nsew',padx=22,pady=(16,8))
        body.grid_columnconfigure(0,weight=1); body.grid_rowconfigure(2,weight=1)
        label(body,'选择数据库，不需要记住安装位置。快捷方式、程序或文件夹都可以作为线索。',12,color=MUTED,anchor='w').grid(row=0,column=0,sticky='ew',pady=(0,10))
        search=ctk.CTkEntry(body,textvariable=self.filter,placeholder_text='筛选路径或账号',height=34,
            border_color=LINE,fg_color='white',font=(FONT,12))
        search.grid(row=1,column=0,sticky='ew',pady=(0,10))
        self.list=ctk.CTkScrollableFrame(body,fg_color='transparent',corner_radius=0)
        self.list.grid(row=2,column=0,sticky='nsew'); self.list.grid_columnconfigure(0,weight=1)
        self.filter.trace_add('write',lambda *_:self.render())
        footer=ctk.CTkFrame(self,fg_color='white',corner_radius=0); footer.grid(row=2,column=0,sticky='ew')
        footer.grid_columnconfigure(0,weight=1)
        note=f'已检查 {result.scanned_dirs} 个目录、{result.checked} 个数据库文件'
        if result.cancelled: note='扫描已取消，保留已找到的结果。'
        elif result.warnings: note+=' · '+result.warnings[0]
        label(footer,note,11,color=MUTED,anchor='w',wraplength=790,justify='left').grid(row=0,column=0,columnspan=2,sticky='ew',padx=24,pady=(12,9))
        alternatives=ctk.CTkFrame(footer,fg_color='transparent'); alternatives.grid(row=1,column=0,sticky='w',padx=(24,8),pady=(0,18))
        button(alternatives,'扫描文件夹…',lambda:self.dismiss(('scan',None)),width=110).pack(side='left',padx=(0,7))
        button(alternatives,'选择文件…',lambda:self.dismiss(('file',None)),width=100).pack(side='left')
        actions=ctk.CTkFrame(footer,fg_color='transparent'); actions.grid(row=1,column=1,sticky='e',padx=(0,24),pady=(0,18))
        button(actions,'取消',self.dismiss,width=70).pack(side='left',padx=(0,7))
        self.choose_btn=button(actions,'使用所选数据库',self.choose,primary=True,width=135)
        self.choose_btn.pack(side='left'); self.choose_btn.configure(state='normal' if result.candidates else 'disabled')
        self.render()

    def render(self):
        for widget in self.list.winfo_children(): widget.destroy()
        query=self.filter.get().strip().casefold()
        visible=[c for c in self.discovery.candidates if query in (str(c.path)+' '+c.account+' '+' '.join(c.sources)).casefold()]
        if not visible:
            title='没有匹配的结果' if self.discovery.candidates else '从你知道的位置继续查找'
            label(self.list,title,17,True,anchor='w').grid(row=0,column=0,sticky='ew',padx=10,pady=(22,8))
            text=('尝试更短的路径片段，或清空筛选条件。' if self.discovery.candidates else
                '• 扫描安装文件夹、解压目录，或存放软件的磁盘目录。\n\n• 也可选择桌面 / 开始菜单中的快捷方式，或 Tai.exe / hindsight.exe。\n\n• Hindsight 需要先运行一次完成数据库初始化。\n\n定位时可以保持软件运行；预览和迁移前请退出软件与托盘进程。')
            label(self.list,text,13,color=MUTED,anchor='w',justify='left',wraplength=720).grid(row=1,column=0,sticky='ew',padx=10,pady=10)
            return
        for i,candidate in enumerate(visible):
            card=ctk.CTkFrame(self.list,fg_color='white',border_width=1,border_color=LINE,corner_radius=8)
            card.grid(row=i,column=0,sticky='ew',padx=(0,5),pady=(0,9)); card.grid_columnconfigure(0,weight=1)
            title=candidate.path.name+('   · 当前账号' if candidate.active and self.kind=='hindsight' else '')
            ctk.CTkRadioButton(card,text=title,variable=self.selected,value=str(candidate.path),font=(FONT,13,'bold'),
                text_color=INK,fg_color=TEAL,border_color='#97AABA',radiobutton_width=17,radiobutton_height=17).grid(row=0,column=0,sticky='w',padx=16,pady=(13,5))
            path=ctk.CTkTextbox(card,height=46,fg_color='#F4F7FA',text_color=INK,font=('Segoe UI',12),wrap='char',border_width=0)
            path.grid(row=1,column=0,sticky='ew',padx=16,pady=(0,5)); path.insert('1.0',str(candidate.path)); path.configure(state='disabled')
            details=f'{candidate.size/1024/1024:.1f} MB  ·  修改于 {datetime.fromtimestamp(candidate.modified):%Y-%m-%d %H:%M}  ·  '+ ' / '.join(candidate.sources)
            label(card,details,11,color=MUTED,anchor='w',wraplength=720,justify='left').grid(row=2,column=0,sticky='ew',padx=16,pady=(0,12))

    def choose(self):
        selected=self.selected.get()
        if any(str(c.path)==selected for c in self.discovery.candidates): self.dismiss(('choose',selected))
