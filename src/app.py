import sqlite3, threading, datetime as dt, time, os, sys, json, pathlib, ctypes as C
import winsound
import tkinter as tk
from tkinter import ttk
import trainer as core
import lang
from lang import T

VERSION='1.0.0'
BG='#111116';PANEL='#1c1c24';TEXT='#f2f2f5';MUTED='#9797a8';RED='#ec5967';GREEN='#7ee0ac';AMBER='#e5be73'
SETTINGS=core.DATA/'settings.json'
HISTORY=core.DATA/'history.sqlite3'
UI_SETTINGS=core.DATA/'ui.json'
DATA_LABEL='%LOCALAPPDATA%\HellraiserTrainer' if os.environ.get('LOCALAPPDATA') else str(core.DATA)
ASSETS=pathlib.Path(getattr(sys,'_MEIPASS',pathlib.Path(__file__).resolve().parent.parent))/'assets'
LAUNCH_KINDS={'trainer':'Трейнер','game':'Игра'}
LAUNCH_STATES={'running':'Работает','finished':'Завершён','ended':'Завершена','detached':'Отсоединено','interrupted':'Сеанс прерван','restore_error':'Ошибка восстановления'}
EVENT_KINDS={'app':'Приложение','game':'Игра','mode':'Функция','status':'Статус','level':'Уровень','compatibility':'Совместимость','diagnostic':'Диагностика'}
DESCRIPTIONS={'god':'Здоровье и защита от урона','ammo':'Магазин и имеющийся боезапас','durability':'Игровой режим без износа','energy':'Без расхода энергии способностей','resources':'Пополнение стопок до лимита','recoil':'Без рывка камеры и тряски выстрела','invisible':'Подавление восприятия врагов','lockpicks':'Без износа и расхода при открытии','coins':'Поддерживать 999 999 монет','onehit':'Высокий урон · здоровье врагов до 1','easylock':'Взлом при любом угле отмычки','accuracy':'Без разброса и смещения прицела','hold':'Бесконечное удержание телекинезом'}

def stamp(t=None):return dt.datetime.fromtimestamp(t or time.time()).strftime('%d.%m.%Y  %H:%M:%S')
def duration(seconds):
 seconds=max(0,int(seconds));h,r=divmod(seconds,3600);m,s=divmod(r,60);return f'{h:02}:{m:02}:{s:02}'
def atomic_json(path,value):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)
def read_json(path):
 try:return json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,ValueError):return {}

class ToggleAudio:
 def __init__(self,options,enabled=True):
  self.previous=dict(options);self.enabled=enabled;self.failed=False
 def update(self,options):
  changed=[bool(value) for key,value in options.items() if self.previous.get(key)!=value]
  self.previous=dict(options)
  if not changed or not self.enabled:return
  name='enabled' if any(changed) else 'disabled'
  try:winsound.PlaySound(str(ASSETS/(name+'.wav')),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
  except (OSError,RuntimeError):self.failed=True

class History:
 def __init__(self,path=HISTORY):
  self.lock=threading.RLock();self.db=sqlite3.connect(str(path),check_same_thread=False)
  with self.db:
   self.db.execute('CREATE TABLE IF NOT EXISTS launches (id INTEGER PRIMARY KEY, kind TEXT, started REAL, ended REAL, pid INTEGER, status TEXT)')
   self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time REAL, kind TEXT, message TEXT, extra TEXT)')
  self.run_id=None;self.game_id=None;self.revision=0
 def begin(self):
  with self.lock,self.db:
   self.db.execute("UPDATE launches SET status='interrupted' WHERE kind='trainer' AND ended IS NULL")
   self.run_id=self.db.execute('INSERT INTO launches(kind,started,pid,status) VALUES (?,?,?,?)',('trainer',time.time(),os.getpid(),'running')).lastrowid
  self.event('app',T('Приложение запущено'),{})
 def event(self,kind,message,extra=None):
  extra=extra or {}
  with self.lock,self.db:
   self.db.execute('INSERT INTO events(time,kind,message,extra) VALUES (?,?,?,?)',(time.time(),kind,message,json.dumps(extra,ensure_ascii=False)))
   if kind=='game' and 'created' in extra:
    pid=extra.get('pid');started=extra.get('created') or time.time()
    row=self.db.execute("SELECT id FROM launches WHERE kind='game' AND pid=? AND ABS(started-?)<1",(pid,started)).fetchone()
    if row:self.game_id=row[0];self.db.execute("UPDATE launches SET status='running', ended=NULL WHERE id=?",(self.game_id,))
    else:self.game_id=self.db.execute('INSERT INTO launches(kind,started,pid,status) VALUES (?,?,?,?)',('game',started,pid,'running')).lastrowid
   elif kind=='game' and self.game_id:
    self.db.execute("UPDATE launches SET ended=?,status='ended' WHERE id=?",(time.time(),self.game_id));self.game_id=None
   self.revision+=1
 def finish(self,restored=True):
  self.event('app',T('Приложение закрыто; функции отключены') if restored else T('Приложение закрыто с ошибкой восстановления'),{})
  with self.lock,self.db:
   if self.run_id:self.db.execute("UPDATE launches SET ended=?,status=? WHERE id=?",(time.time(),'finished' if restored else 'restore_error',self.run_id))
   if self.game_id:self.db.execute("UPDATE launches SET ended=?,status='detached' WHERE id=? AND ended IS NULL",(time.time(),self.game_id))
 def rows(self):
  with self.lock:
   launches=self.db.execute('SELECT id,kind,started,ended,pid,status FROM launches ORDER BY started DESC LIMIT 100').fetchall()
   events=self.db.execute('SELECT id,time,kind,message FROM events ORDER BY id DESC LIMIT 150').fetchall()
   count=self.db.execute("SELECT COUNT(*) FROM launches WHERE kind='trainer'").fetchone()[0]
   return launches,events,count

class Dashboard:
 def __init__(self,trainer,history,ui,hidden=False):
  self.t=trainer;self.history=history;self.t.on_event=history.event;self.started=time.time();self.closing=False;self.last_show=None;self.last_save=dict(self.t.options)
  self.ui=ui;self.audio=ToggleAudio(self.t.options,bool(ui.get('sound_enabled',True)))
  self.root=tk.Tk();self.root.geometry('1320x970');self.root.minsize(1280,900);self.root.configure(bg=BG);self.root.protocol('WM_DELETE_WINDOW',self.close)
  try:self.root.iconbitmap(str(ASSETS/'Hellraiser.ico'))
  except tk.TclError:pass
  if hidden:self.root.withdraw()
  self.style=ttk.Style();self.style.theme_use('clam')
  self.style.configure('TNotebook',background=BG,borderwidth=0,bordercolor=BG,lightcolor=BG,darkcolor=BG);self.style.configure('TNotebook.Tab',background=PANEL,foreground=MUTED,padding=(18,8),font=('Segoe UI',10),bordercolor=BG,lightcolor=BG,darkcolor=BG)
  self.style.map('TNotebook.Tab',background=[('selected','#2c2c39')],foreground=[('selected',TEXT)])
  self.style.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=29,font=('Segoe UI',9),borderwidth=0,bordercolor=PANEL,lightcolor=PANEL,darkcolor=PANEL)
  self.style.configure('Treeview.Heading',background='#292933',foreground=MUTED,font=('Segoe UI',9),padding=7,bordercolor=PANEL,lightcolor=PANEL,darkcolor=PANEL)
  self.style.map('Treeview',background=[('selected','#3a2933')],foreground=[('selected',TEXT)])
  self.style.configure('Vertical.TScrollbar',background='#383844',troughcolor=PANEL,borderwidth=0,arrowsize=12)
  self.root.grid_columnconfigure(0,weight=1);self.root.grid_rowconfigure(3,weight=1)
  self.build()
  self.thread=threading.Thread(target=self.t.loop,daemon=True);self.thread.start();self.down={};self.root.after(80,self.poll)
 def build(self):
  self.last_revision=-1
  self.root.title(T('Hellraiser Trainer'))
  head=tk.Frame(self.root,bg=BG);head.grid(row=0,column=0,sticky='ew',padx=28,pady=(16,12));head.grid_columnconfigure(1,weight=1)
  self.label(head,'HELLRAISER',25,RED,True).grid(row=0,column=0,sticky='w')
  self.label(head,'TRAINER  /  v'+VERSION,10,MUTED).grid(row=1,column=0,sticky='w')
  self.session_label=self.label(head,'',10,MUTED);self.session_label.grid(row=0,column=1,sticky='e')
  self.label(head,T('F10 — окно  ·  F12 — отключить всё'),10,MUTED).grid(row=1,column=1,sticky='e')
  switch=tk.Frame(head,bg=BG);switch.grid(row=0,column=2,rowspan=2,sticky='ne',padx=(18,0))
  for code,text in (('ru','RU'),('en','EN')):
   active=lang.current()==code
   tk.Button(switch,text=text,command=lambda code=code:self.set_language(code),bg=RED if active else PANEL,fg=TEXT if active else MUTED,activebackground=RED,activeforeground=TEXT,
             font=('Segoe UI',10,'bold'),relief='flat',width=4,pady=4,cursor='hand2',bd=0,highlightthickness=0).pack(side='left',padx=(0,4))
  hero=tk.Frame(self.root,bg=PANEL);hero.grid(row=1,column=0,sticky='ew',padx=28);hero.grid_columnconfigure(0,weight=1)
  self.game_label=self.label(hero,'Hellraiser: Revival',16,TEXT,True);self.game_label.grid(row=0,column=0,sticky='w',padx=18,pady=(14,3))
  self.connection=self.label(hero,T('Поиск игры…'),10,MUTED);self.connection.config(wraplength=980,justify='left');self.connection.grid(row=1,column=0,sticky='w',padx=18,pady=(0,12))
  self.pid_label=self.label(hero,'PID  —',11,MUTED);self.pid_label.grid(row=0,column=1,padx=20)
  self.build_label=self.label(hero,T('Сборка UE5'),9,MUTED);self.build_label.grid(row=1,column=1,padx=20,sticky='e')
  metrics=tk.Frame(hero,bg=PANEL);metrics.grid(row=2,column=0,columnspan=2,sticky='ew',padx=18,pady=(0,14))
  self.metric_labels={}
  for j,(key,title) in enumerate([('hp','ЗДОРОВЬЕ'),('energy','ЭНЕРГИЯ'),('active','ФУНКЦИИ'),('game_time','ВРЕМЯ ИГРЫ')]):
   metrics.grid_columnconfigure(j,weight=1);f=tk.Frame(metrics,bg='#24242e');f.grid(row=0,column=j,sticky='ew',padx=(0,8) if j<3 else 0)
   self.label(f,T(title),8,MUTED).pack(anchor='w',padx=12,pady=(8,0));v=self.label(f,'—',18,TEXT,True);v.pack(anchor='w',padx=12,pady=(0,7));self.metric_labels[key]=v
  controls=tk.Frame(self.root,bg=BG);controls.grid(row=2,column=0,sticky='ew',padx=28,pady=(12,10))
  for c in range(4):controls.grid_columnconfigure(c,weight=1)
  self.vars={};self.state_labels={}
  for i,(key,hotkey,title) in enumerate(core.MODES):
   row,col=divmod(i,4);f=tk.Frame(controls,bg=PANEL);f.grid(row=row,column=col,sticky='nsew',padx=4,pady=5);f.grid_columnconfigure(1,weight=1)
   self.label(f,hotkey,10,RED,True).grid(row=0,column=0,padx=(14,9),pady=(9,0),sticky='w')
   title_label=self.label(f,T(title),10,TEXT,True);title_label.config(wraplength=195,justify='left');title_label.grid(row=0,column=1,pady=(9,0),sticky='w')
   v=tk.BooleanVar(value=self.t.options[key]);self.vars[key]=v
   box=tk.Checkbutton(f,variable=v,command=lambda key=key:self.toggle(key),bg=PANEL,activebackground=PANEL,fg=GREEN,activeforeground=GREEN,selectcolor='#32323e',highlightthickness=0,cursor='hand2')
   box.grid(row=0,column=2,rowspan=2,padx=(8,14))
   description=self.label(f,T(DESCRIPTIONS[key]),9,MUTED);description.config(wraplength=230,justify='left');description.grid(row=1,column=0,columnspan=2,padx=14,sticky='w')
   status=self.label(f,T('Выключено'),9,MUTED);status.config(wraplength=265,justify='left');status.grid(row=2,column=0,columnspan=3,padx=14,pady=(2,7),sticky='w');self.state_labels[key]=status
  actions=tk.Frame(controls,bg=BG);actions.grid(row=4,column=0,columnspan=4,sticky='ew',padx=4,pady=5)
  self.button(actions,T('Включить основные'),self.enable_core,RED).pack(side='left',padx=(0,8))
  self.button(actions,T('Отключить всё'),self.disable_all,'#32323e').pack(side='left')
  self.button(actions,T('Повторить поиск'),self.t.rescan,'#32323e').pack(side='left',padx=8)
  self.sound_var=tk.BooleanVar(value=self.audio.enabled)
  tk.Checkbutton(actions,text=T('Звук переключений'),variable=self.sound_var,command=self.toggle_sound,bg=BG,activebackground=BG,fg=TEXT,activeforeground=TEXT,selectcolor=PANEL,highlightthickness=0,font=('Segoe UI',10),cursor='hand2').pack(side='right',padx=8)
  self.notebook=ttk.Notebook(self.root);self.notebook.grid(row=3,column=0,sticky='nsew',padx=28,pady=(0,12))
  self.launches=self.table(T('Запуски'),[('kind',T('Что запущено'),100),('start',T('Начало'),170),('duration',T('Время'),90),('pid','PID',70),('status',T('Состояние'),160)])
  self.events=self.table(T('Журнал'),[('time',T('Время'),170),('kind',T('Тип'),105),('message',T('Событие'),600)])
  self.footer=self.label(self.root,'',9,MUTED);self.footer.grid(row=4,column=0,sticky='w',padx=28,pady=(0,15))
 def set_language(self,code):
  if lang.current()==code:return
  lang.set_language(code);self.ui['language']=code;self.save_ui()
  for child in self.root.winfo_children():child.destroy()
  self.build();self.refresh_history()
 def label(self,parent,text,size=10,color=TEXT,bold=False):return tk.Label(parent,text=text,bg=parent['bg'],fg=color,font=('Segoe UI',size,'bold' if bold else 'normal'),anchor='w')
 def button(self,parent,text,command,color):return tk.Button(parent,text=text,command=command,bg=color,fg=TEXT,activebackground=color,activeforeground=TEXT,font=('Segoe UI',10,'bold'),relief='flat',padx=14,pady=8,cursor='hand2')
 def table(self,title,columns):
  f=tk.Frame(self.notebook,bg=PANEL);self.notebook.add(f,text=title)
  tree=ttk.Treeview(f,columns=[c[0] for c in columns],show='headings',selectmode='browse');bar=ttk.Scrollbar(f,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=bar.set)
  tree.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
  for key,label,width in columns:tree.heading(key,text=label,anchor='w');tree.column(key,width=width,minwidth=60,anchor='w',stretch=key in ['status','message'])
  return tree
 def toggle(self,key):self.t.options[key]=self.vars[key].get()
 def save_ui(self):
  try:atomic_json(UI_SETTINGS,self.ui)
  except OSError:pass
 def toggle_sound(self):
  self.audio.enabled=self.sound_var.get();self.ui['sound_enabled']=self.audio.enabled;self.save_ui()
 def enable_core(self):
  for key in ('god','ammo','durability','energy'):self.t.options[key]=True
 def disable_all(self):
  for key in self.t.options:self.t.options[key]=False
 def save(self):
  if self.t.options!=self.last_save:
   try:atomic_json(SETTINGS,self.t.options);self.last_save=dict(self.t.options)
   except OSError:pass
 def show(self):self.root.deiconify();self.root.lift()
 def close(self):
  if self.closing:return
  self.closing=True;self.save();self.t.running=False;self.connection.config(text=T('Отключение функций…'));self.root.after(50,self.await_close)
 def await_close(self):
  if self.thread.is_alive():self.root.after(100,self.await_close);return
  self.history.finish(not bool(self.t.globals_restore or self.t.restore or self.t.tag_actors or self.t.script_restore or self.t.cheat_tags));self.root.destroy()
 def mode_status(self,key,snapshot):
  if not self.t.options[key]:return T('Выключено'),MUTED
  if not snapshot['pid']:return (T('Не работает: движок не распознан'),RED) if snapshot.get('compatibility_error') else (T('Ожидание игры'),AMBER)
  feature=snapshot.get('features',{}).get(key)
  if feature:return feature['message'],GREEN if feature['state']=='available' else RED if feature['state']=='unavailable' else AMBER
  d=snapshot['details']
  if key=='invisible':
   if not d.get('invisible') or not d.get('stealth_gate_verified'):return T('Ожидание игровых механизмов'),AMBER
   return (T('Подавление восприятия · врагов: ')+str(d['stealth_targets']),GREEN) if d.get('stealth_targets') else (T('Включено · ожидание врагов'),AMBER)
  if not d:return T('Ожидание персонажа'),AMBER
  if key=='hold':return (T('Удержание без ограничения времени'),GREEN) if d.get('hold_mechanism') else (T('Поиск механизма телекинеза'),AMBER)
  if key=='ammo' and not (d.get('weapons') or d.get('ammo_stacks')):return T('Включено · ожидание оружия / патронов'),AMBER
  if key=='durability':return (T('Защита от износа включена'),GREEN) if d.get('durability_mechanism') else (T('Поиск игрового механизма'),AMBER)
  if key=='lockpicks':return (T('Защита от износа включена'),GREEN) if d.get('lockpick_formula') and d.get('lockpicks_mechanism') else (T('Поиск игрового механизма'),AMBER)
  if key=='easylock':return (T('Лёгкий взлом включён'),GREEN) if d.get('easylock_mechanism') else (T('Поиск механизма / ожидание замка'),AMBER)
  if key=='coins':return (T('Монет: ')+f'{d["coins"]:,}'.replace(',',' '),GREEN) if d.get('coins') is not None else (T('Ожидание монет в инвентаре'),AMBER)
  if key=='onehit':return (T('Урон усилен · врагов с 1 HP: ')+str(d.get('onehit_enemies',0)),GREEN) if d.get('onehit_target') else (T('Ожидание персонажа / оружия'),AMBER)
  if key=='accuracy':return (T('Нулевой разброс и смещение'),GREEN) if d.get('accuracy_targets') else (T('Ожидание огнестрельного оружия'),AMBER)
  if key=='resources' and not d.get('resources'):return T('Включено · ожидание ресурсов'),AMBER
  if key=='recoil':return (T('Рывок камеры и тряска отключены'),GREEN) if d.get('TryToRecoil_blocked') and d.get('StartWeaponCameraShake_blocked') else (T('Поиск механизма отдачи'),AMBER)
  if key=='god':return (T('Включено · игровой тег неуязвимости'),GREEN) if d.get('native_invulnerability') else (T('Включено · здоровье и защита от урона'),GREEN)
  return T('Включено'),GREEN
 def refresh_history(self):
  launches,events,count=self.history.rows()
  rows={str(row[0]) for row in launches}
  for child in self.launches.get_children():
   if child not in rows:self.launches.delete(child)
  for id,kind,start,end,pid,status in launches:
   values=(T(LAUNCH_KINDS.get(kind,kind)),stamp(start),duration((end or time.time())-start) if status!='interrupted' else '—',pid or '—',T(LAUNCH_STATES.get(status,status)))
   if self.launches.exists(str(id)):self.launches.item(str(id),values=values)
   else:self.launches.insert('',0,iid=str(id),values=values)
  self.launches.set_children('',*[str(row[0]) for row in launches])
  if self.last_revision!=self.history.revision:
   self.events.delete(*self.events.get_children())
   for id,when,kind,message in events:self.events.insert('','end',iid=str(id),values=(stamp(when),T(EVENT_KINDS.get(kind,kind)),message))
   self.last_revision=self.history.revision
  self.session_label.config(text=T('Запусков трейнера: ')+str(count)+T('  ·  Сеанс ')+duration(time.time()-self.started))
 def poll(self):
  if self.closing:return
  if not self.t.running:self.close();return
  foreground=core.W.DWORD();core.U.GetWindowThreadProcessId(core.U.GetForegroundWindow(),C.byref(foreground));allowed=foreground.value in (os.getpid(),self.t.m.pid if self.t.m else 0)
  for vk in list(core.HOTKEYS)+[0x79,0x7b]:
   pressed=bool(core.U.GetAsyncKeyState(vk)&0x8000)
   if pressed and not self.down.get(vk) and allowed:
    if vk==0x79:
     if self.root.state()=='withdrawn':self.show()
     else:self.root.withdraw()
    elif vk==0x7b:self.disable_all()
    else:
     key=core.HOTKEYS[vk];self.t.options[key]=not self.t.options[key]
   self.down[vk]=pressed
  control=read_json(core.CONTROL);show=control.get('show')
  if show and show!=self.last_show:self.last_show=show;self.show()
  s=self.t.snapshot();d=s['details'];pid=s['pid']
  self.audio.update(s['enabled'])
  self.connection.config(text=s['status']+('  ·  '+d.get('level','') if d else ''),fg=GREEN if pid and not s['errors'] else AMBER)
  self.pid_label.config(text=f'PID  {pid or "—"}');self.build_label.config(text=(T('UE · автоадаптация') if s.get('adaptive') else T('UE · известная сборка')) if pid else T('Поиск игры / механизмов'))
  for key,var in self.vars.items():
   if var.get()!=self.t.options[key]:var.set(self.t.options[key])
   text,color=self.mode_status(key,s);self.state_labels[key].config(text=text,fg=color)
  self.metric_labels['hp'].config(text=str(d.get('health')) if d.get('health') is not None else '—')
  self.metric_labels['energy'].config(text=str(d.get('energy')) if d.get('energy') is not None else '—')
  self.metric_labels['active'].config(text=f'{sum(self.t.options.values())} / {len(core.MODES)}')
  self.metric_labels['game_time'].config(text=duration(time.time()-s['game_started']) if s.get('game_started') else '—')
  self.footer.config(text=T('Настройки и история: ')+DATA_LABEL+T('  ·  Ошибок: ')+str(s['errors'])+T('  ·  Закрытие приложения отключает функции'))
  self.save()
  if not hasattr(self,'last_history') or time.monotonic()-self.last_history>=1:self.refresh_history();self.last_history=time.monotonic()
  self.root.after(100,self.poll)
 def run(self):self.root.mainloop()

def main():
 shell=C.WinDLL('shell32');shell.SetCurrentProcessExplicitAppUserModelID.argtypes=[C.c_wchar_p];shell.SetCurrentProcessExplicitAppUserModelID.restype=C.c_long
 shell.SetCurrentProcessExplicitAppUserModelID('jestelf.HellraiserTrainer')
 mutex=core.K.CreateMutexW(None,False,'Local\\HellraiserTrainer.jestelf')
 if C.get_last_error()==183:
  atomic_json(core.CONTROL,{'show':time.time()});return
 atomic_json(core.CONTROL,{})
 ui=read_json(UI_SETTINGS)
 lang.set_language(ui.get('language') or lang.system_language())
 options={k:False for k,_,_ in core.MODES}
 options.update({k:bool(v) for k,v in read_json(SETTINGS).items() if k in options})
 if '--all' in sys.argv:
  for k in ('god','ammo','durability','energy'):options[k]=True
 if '--read-only' in sys.argv:options={k:False for k in options}
 history=History();history.begin()
 try:Dashboard(core.Trainer(options),history,ui,'--background' in sys.argv).run()
 except Exception as e:
  history.event('status',T('Ошибка приложения: ')+str(e));history.finish(False);raise
 finally:core.K.CloseHandle(mutex)

if __name__=='__main__':main()
