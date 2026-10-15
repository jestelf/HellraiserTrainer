import ctypes as C
from ctypes import wintypes as W
import struct, time, threading, json, sys, pathlib, math, os
import ue as compatibility
from lang import T

K=C.WinDLL('kernel32',use_last_error=True)
U=C.WinDLL('user32',use_last_error=True)
K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];K.OpenProcess.restype=W.HANDLE
K.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];K.ReadProcessMemory.restype=W.BOOL
K.WriteProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];K.WriteProcessMemory.restype=W.BOOL
K.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];K.CreateToolhelp32Snapshot.restype=W.HANDLE
K.CloseHandle.argtypes=[W.HANDLE]
K.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)];K.GetExitCodeProcess.restype=W.BOOL
K.GetProcessTimes.argtypes=[W.HANDLE,C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME)];K.GetProcessTimes.restype=W.BOOL
K.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];K.CreateMutexW.restype=W.HANDLE
U.GetAsyncKeyState.argtypes=[C.c_int];U.GetAsyncKeyState.restype=C.c_short
U.GetForegroundWindow.restype=W.HWND
U.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
class PROCESSENTRY(C.Structure):
 _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',C.c_size_t),('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('exe',W.WCHAR*260)]
class MODULEENTRY(C.Structure):
 _fields_=[('size',W.DWORD),('module',W.DWORD),('pid',W.DWORD),('usage',W.DWORD),('procusage',W.DWORD),('base',C.c_void_p),('length',W.DWORD),('handle',W.HMODULE),('name',W.WCHAR*256),('path',W.WCHAR*260)]
for name,typ in [('Process32FirstW',PROCESSENTRY),('Process32NextW',PROCESSENTRY),('Module32FirstW',MODULEENTRY),('Module32NextW',MODULEENTRY)]:
 f=getattr(K,name);f.argtypes=[W.HANDLE,C.POINTER(typ)];f.restype=W.BOOL
EXE='Hellraiser-Win64-Shipping.exe'
POOL_RVA=0xae85d00
WORLD_RVAS=(0xb0f7c98,0xac61870)
OBJECTS_RVA=0xaf69860
TIMESTAMP=0xa91530ff
IMAGE_SIZE=0xbce3000
IGNORE_PLAYERS_RVA=0xb128f38
DATA=pathlib.Path(os.environ.get('LOCALAPPDATA') or pathlib.Path.home())/'HellraiserTrainer'
DATA.mkdir(parents=True,exist_ok=True)
STATUS=DATA/'status.json'
CONTROL=DATA/'control.json'
MODES=[('god','F1','Бессмертие'),('ammo','F2','Патроны и полный магазин'),('durability','F3','Прочность оружия'),('energy','F4','Энергия способностей'),('resources','F5','Пополнение ресурсов'),('recoil','F6','Без отдачи'),('invisible','F7','Невидимость для врагов')]
MODES += [('lockpicks','F8','Отмычки не ломаются'),('coins','F9','Бесконечные монеты'),('onehit','F11','Убийство с одного удара'),('easylock','Insert','Лёгкий взлом отмычками')]
MODES += [('accuracy','Delete','Точность по центру прицела'),('hold','Home','Удержание без таймера')]
HOTKEYS={**{0x6f+int(key[1:]):mode for mode,key,_ in MODES if key.startswith('F')},0x2d:'easylock',0x2e:'accuracy',0x24:'hold'}

def find_game():
 snap=K.CreateToolhelp32Snapshot(2,0)
 if snap==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
 try:
  e=PROCESSENTRY();e.size=C.sizeof(e);ok=K.Process32FirstW(snap,C.byref(e));fallback=None
  while ok:
   if e.exe.lower()==EXE.lower():return e.pid
   if e.exe.lower() in ('hellraiser-wingdk-shipping.exe','hellraiser-win64-test.exe','hellraiser-windows-shipping.exe'):fallback=e.pid
   ok=K.Process32NextW(snap,C.byref(e))
 finally:K.CloseHandle(snap)
 return fallback

class Memory:
 def __init__(self,pid,progress=None):
  self.pid=pid;self.h=K.OpenProcess(0x438,False,pid)
  if not self.h:raise C.WinError(C.get_last_error())
  snap=K.CreateToolhelp32Snapshot(0x18,pid)
  try:
   e=MODULEENTRY();e.size=C.sizeof(e)
   if not K.Module32FirstW(snap,C.byref(e)):
    error=C.WinError(C.get_last_error());self.close();raise error
   self.base=e.base;self.path=e.path
  finally:
   if snap!=C.c_void_p(-1).value:K.CloseHandle(snap)
  try:
   self.timestamp,self.image_size,self.sections=compatibility.pe_layout(self)
   self.known_build=(self.timestamp,self.image_size)==(TIMESTAMP,IMAGE_SIZE)
   names,objects=compatibility.resolve(self,POOL_RVA if self.known_build else None,OBJECTS_RVA if self.known_build else None,progress)
   self.pool=names.pool;self.name_shift=names.shift;self.objects=self.base+objects['rva'];self.object_stride=objects['stride'];self.chunk_size=objects['chunk_size']
   self.build_id=f'{self.timestamp:08X}-{self.image_size:X}'
  except Exception:
   self.close();raise
  creation,exit,kernel,user=W.FILETIME(),W.FILETIME(),W.FILETIME(),W.FILETIME()
  self.created=None
  if K.GetProcessTimes(self.h,C.byref(creation),C.byref(exit),C.byref(kernel),C.byref(user)):self.created=((creation.dwHighDateTime<<32)|creation.dwLowDateTime)/10000000-11644473600
 def read(self,a,n):
  if not 0x10000<a<0x7fffffffffff or not 0<n<=262144:return b''
  b=C.create_string_buffer(n);got=C.c_size_t()
  K.ReadProcessMemory(self.h,C.c_void_p(a),b,n,C.byref(got))
  return b.raw[:got.value]
 def u64(self,a):
  b=self.read(a,8);return struct.unpack('<Q',b)[0] if len(b)==8 else 0
 def u32(self,a):
  b=self.read(a,4);return struct.unpack('<I',b)[0] if len(b)==4 else 0
 def flt(self,a):
  b=self.read(a,4);return struct.unpack('<f',b)[0] if len(b)==4 else float('nan')
 def write(self,a,b):
  if self.read(a,len(b))==b:return
  got=C.c_size_t()
  if not K.WriteProcessMemory(self.h,C.c_void_p(a),b,len(b),C.byref(got)) or got.value!=len(b):raise OSError(T('Не удалось обновить память игры.'))
 def alive(self):
  code=W.DWORD();return bool(self.h and K.GetExitCodeProcess(self.h,C.byref(code)) and code.value==259)
 def close(self):
  if self.h:K.CloseHandle(self.h);self.h=None

class Unreal:
 def __init__(self,m):self.m=m;self.names={};self.properties={};self.layouts={};self.structures={};self.worlds=[];self.script_headers={};self.child_offset=0x50;self.super_offset=0x40;self.size_offset=0x58
 def name(self,i):
  if i in self.names:return self.names[i]
  block=i>>16
  if block>8191:return '?'
  p=self.m.u64(self.m.pool+16+8*block)+(i&65535)*2
  b=self.m.read(p,2)
  if len(b)!=2:return '?'
  h=struct.unpack('<H',b)[0];n=h>>self.m.name_shift
  if not 0<n<1024:return '?'
  b=self.m.read(p+2,n*(2 if h&1 else 1))
  try:s=b.decode('utf-16le' if h&1 else 'utf-8')
  except UnicodeError:return '?'
  if any(ord(c)<32 for c in s):return '?'
  self.names[i]=s;return s
 def cls(self,p):return self.m.u64(p+16)
 def clsname(self,p):return self.name(self.m.u32(self.cls(p)+24))
 def valid(self,p):
  b=self.m.read(p,40)
  if len(b)!=40:return False
  v,flags,idx,cl=struct.unpack_from('<QIIQ',b)
  if flags & (0x10|0x20|0x8000|0x10000) or idx>=self.m.u32(self.m.objects+20) or not self.m.base<v<self.m.base+self.m.image_size:return False
  chunks=self.m.u64(self.m.objects);chunk=self.m.u64(chunks+8*(idx//self.m.chunk_size))
  item=self.m.read(chunk+self.m.object_stride*(idx%self.m.chunk_size),self.m.object_stride)
  if len(item)!=self.m.object_stride or struct.unpack_from('<Q',item)[0]!=p:return False
  return not (struct.unpack_from('<I',item,8)[0] & 0x30000000)
 def is_a(self,p,name):
  cl=self.cls(p);seen=set()
  while cl and cl not in seen and len(seen)<40:
   if self.name(self.m.u32(cl+24))==name:return True
   seen.add(cl);cl=self.m.u64(cl+self.super_offset)
  return False
 def props(self,p):
  cl=self.cls(p)
  if cl in self.properties:return self.properties[cl]
  out={};layouts={};s=cl;seen=set()
  while s and s not in seen and len(seen)<40:
   seen.add(s);f=self.m.u64(s+self.child_offset);fs=set()
   while f and f not in fs and len(fs)<2000:
    fs.add(f);b=self.m.read(f,0x80)
    if len(b)!=0x80:break
    n=self.name(struct.unpack_from('<I',b,0x20)[0]);typ=self.name(self.m.u32(self.m.u64(f+8)))
    off=struct.unpack_from('<I',b,0x44)[0]
    if 0<off<0x20000 and n not in out:
     if not typ.endswith('Property') or n=='?':break
     out[n]=(off,typ,b[0x72],b[0x73])
     if typ=='StructProperty':
      st=struct.unpack_from('<Q',b,0x70)[0];layouts[n]=(self.name(self.m.u32(st+24)),self.m.u32(st+self.size_offset));self.structures[(cl,n)]=st
    f=struct.unpack_from('<Q',b,0x18)[0]
   s=self.m.u64(s+self.super_offset)
  self.properties[cl]=out;self.layouts[cl]=layouts;return out
 def layout(self,p,name):self.props(p);return self.layouts.get(self.cls(p),{}).get(name,('',0))
 def off(self,p,name):return self.props(p).get(name,(0,'',0,0))[0]
 def ptr(self,p,name):
  prop=self.props(p).get(name)
  return self.m.u64(p+prop[0]) if prop and prop[1] in ('ObjectProperty','ClassProperty','ObjectPtrProperty') else 0
 def objects_iter(self):
  m=self.m;chunks=m.u64(m.objects);n=m.u32(m.objects+20)
  if not 8<=n<=16000000:return
  batch=262144//m.object_stride
  for ch in range((n+m.chunk_size-1)//m.chunk_size):
   ptr=m.u64(chunks+8*ch);count=min(m.chunk_size,n-ch*m.chunk_size)
   if not compatibility.pointer(ptr):continue
   for start in range(0,count,batch):
    raw=m.read(ptr+m.object_stride*start,min(batch,count-start)*m.object_stride)
    for j in range(0,len(raw)-m.object_stride+1,m.object_stride):
     q=struct.unpack_from('<Q',raw,j)[0]
     if q and not struct.unpack_from('<I',raw,j+8)[0]&0x30000000:yield q
 def validate_reflection(self):

  actor=0
  for i,q in enumerate(self.objects_iter()):
   if i>50000:break
   if self.name(self.m.u32(q+24))=='Actor' and self.clsname(q)=='Class':actor=q;break
  if not actor:raise RuntimeError(T('Эта сборка: класс Actor не найден; функции недоступны.'))
  for child,superoff,size in ((0x50,0x40,0x58),(0x58,0x40,0x60),(0x58,0x48,0x60)):
   f=self.m.u64(actor+child);found={};seen=set()
   while compatibility.pointer(f) and f not in seen and len(seen)<1000:
    seen.add(f);raw=self.m.read(f,0x80)
    if len(raw)!=0x80:break
    name=self.name(struct.unpack_from('<I',raw,0x20)[0]);typ=self.name(self.m.u32(struct.unpack_from('<Q',raw,8)[0]));off=struct.unpack_from('<I',raw,0x44)[0]
    if 0<off<0x20000:found[name]=typ
    f=struct.unpack_from('<Q',raw,0x18)[0]
   if found.get('bCanBeDamaged')=='BoolProperty' and found.get('Owner') in ('ObjectProperty','ObjectPtrProperty'):
    self.child_offset=child;self.super_offset=superoff;self.size_offset=size;return
  raise RuntimeError(T('Эта сборка: расположение игровых свойств не распознано; запись отключена.'))
 def script(self,fn):

  if not self.valid(fn) or self.clsname(fn)!='Function':return 0,0,0
  prior=self.script_headers.get(fn)
  offsets=[prior] if prior is not None else (0x60,0x68,0x70,0x58,0x78,0x80)
  matches=[]
  for off in offsets:
   header=self.m.read(fn+off,16)
   if len(header)!=16:continue
   address,size,capacity=struct.unpack('<QII',header)
   if not compatibility.pointer(address) or not 3<=size<=capacity<=262144:continue
   if self.m.read(address+size-3,3)!=b'\x04\x0b\x53':continue
   matches.append((address,size,off))
  if len(matches)!=1:return 0,0,0
  address,size,off=matches[0];self.script_headers[fn]=off;return address,size,off
 def void_function(self,fn):
  f=self.m.u64(fn+self.child_offset);seen=set()
  while f:
   if f in seen or len(seen)>200 or not compatibility.pointer(f):return False
   seen.add(f);raw=self.m.read(f,0x80)
   if len(raw)!=0x80 or not self.name(self.m.u32(self.m.u64(f+8))).endswith('Property'):return False
   if struct.unpack_from('<Q',raw,0x38)[0]&(0x100|0x400):return False
   f=struct.unpack_from('<Q',raw,0x18)[0]
  return True
 def attribute(self,p,name):
  prop=self.props(p).get(name)
  if not prop or prop[1]!='StructProperty' or self.layout(p,name)!=('GameplayAttributeData',16):return 0
  raw=self.m.read(p+prop[0]+8,8)
  if len(raw)!=8 or not all(math.isfinite(v) and abs(v)<1e9 for v in struct.unpack('<ff',raw)):return 0
  return prop[0]+8
 def array(self,a,stride=8):
  p=self.m.u64(a);n=self.m.u32(a+8);cap=self.m.u32(a+12)
  if not 0<n<=cap<=4096:return []
  b=self.m.read(p,n*stride)
  if len(b)!=n*stride:return []
  return [struct.unpack_from('<Q',b,i*stride)[0] for i in range(n)]
 def player(self):
  candidates=self.worlds+[self.m.u64(self.m.base+rva) for rva in WORLD_RVAS if self.m.known_build]
  for w in dict.fromkeys(candidates):
   if not self.valid(w) or self.clsname(w)!='World':continue
   gi=self.ptr(w,'OwningGameInstance');o=self.off(gi,'LocalPlayers')
   local=self.array(gi+o) if o else []
   if not local:continue
   pc=self.ptr(local[0],'PlayerController');p=self.ptr(pc,'Pawn')
   if self.valid(p):
    tag=self.off(p,'ClassTag')
    if self.is_a(p,'PlayerCharacter') or tag and self.name(self.m.u32(p+tag)).startswith('Character.Class.Player.'):return p,w
  return 0,0

class Trainer:
 def __init__(self,options=None):
  self.options={k:bool((options or {}).get(k,False)) for k,_,_ in MODES};self.m=None;self.ue=None;self.restore={};self.tag_actors={};self.globals_restore={};self.running=True;self.last=T('Ожидание игры');self.details={};self.errors=0;self.seen_control=None;self.started=time.time();self.on_event=None
  self.script_restore={};self.script_objects=[];self.puzzles=[];self.perceptions=[];self.enemy_managers=[];self.ranged_weapons=[];self.scan_thread=None;self.next_scan=0;self.cheat_tags={}
  self.scan_done=False;self.feature_errors={};self.feature_success={};self.compatibility_states={};self.last_connect_error='';self.rescan_requested=False
 def rescan(self):self.next_scan=0;self.rescan_requested=True
 def emit(self,kind,message,**extra):
  if self.on_event:
   try:self.on_event(kind,message,extra)
   except Exception:pass
 def connect(self):
  pid=find_game()
  if not pid:self.last_connect_error='';return False
  m=Memory(pid,lambda text:setattr(self,'last',text));u=Unreal(m)
  try:u.validate_reflection()
  except Exception:m.close();raise
  self.m=m;self.ue=u;self.scan_done=False;self.next_scan=0;self.last_connect_error=''
  self.emit('game',T('Подключение к игре'),pid=m.pid,created=m.created,path=m.path,build=m.build_id,adaptive=not m.known_build)
  self.emit('compatibility',T('Таблицы движка проверены')+(T(' · известная сборка') if m.known_build else T(' · адреса найдены автоматически')),pool=hex(m.pool-m.base),objects=hex(m.objects-m.base),stride=m.object_stride)
  return True
 def identity(self,p):return (self.m.u32(p+12),self.ue.cls(p),self.m.u64(p+32))
 def write_mode(self,address,data,mode):
  if mode in self.feature_errors:return False
  try:
   self.m.write(address,data)
   if self.m.read(address,len(data))!=data:raise OSError(T('Игра не подтвердила запись.'))
   self.feature_success[mode]=self.feature_success.get(mode,0)+1;return True
  except (OSError,ValueError,struct.error) as error:
   self.feature_errors[mode]=str(error);return False
 def change(self,p,o,b,mode,mask=0):
  if not o or not self.ue.valid(p) or mode in self.feature_errors:return False
  key=(p,o,mode)
  before=self.m.read(p+o,len(b))
  if len(before)!=len(b):return False
  if key not in self.restore:self.restore[key]=(self.identity(p),before,mask,b)
  else:
   identity,orig,oldmask,last=self.restore[key]
   if identity!=self.identity(p):self.restore[key]=(self.identity(p),before,mask,b)
  if mask:b=bytes([(before[0]&~mask)|(b[0]&mask)])
  if not self.write_mode(p+o,b,mode):return False
  identity,orig,mask,_=self.restore[key];self.restore[key]=(identity,orig,mask,b)
  return True
 def flag(self,p,name,on,mode):
  prop=self.ue.props(p).get(name)
  if prop and prop[1]=='BoolProperty' and prop[3] and prop[2]:return self.change(p,prop[0],bytes([prop[2] if on else 0]),mode,prop[3])
  return False
 def restore_off(self,all_modes=False):
  for key,(identity,script,original,replacement) in list(self.script_restore.items()):
   fn,offset,mode=key
   if not all_modes and self.options.get(mode):continue
   if self.m and self.m.alive() and self.ue.valid(fn) and self.identity(fn)==identity and self.ue.script(fn)[0]==script:
    if self.m.read(script+offset,len(replacement))==replacement:self.m.write(script+offset,original)
   self.script_restore.pop(key,None)
  for (asc,tag,mode),identity in list(self.cheat_tags.items()):
   if not all_modes and self.options.get(mode):continue
   if self.m and self.m.alive() and self.ue.valid(asc) and self.identity(asc)==identity:self.existing_tag(asc,tag,False,mode)
   self.cheat_tags.pop((asc,tag,mode),None)
  for mode,(rva,original) in list(self.globals_restore.items()):
   if all_modes or not self.options.get(mode):
    if self.m and self.m.alive():self.m.write(self.m.base+rva,original)
    self.globals_restore.pop(mode,None)
  if all_modes or not self.options['god']:
   for asc,identity in list(self.tag_actors.items()):
    if self.m and self.m.alive() and self.ue.valid(asc) and self.identity(asc)==identity:self.invulnerable_tag(asc,False)
    self.tag_actors.pop(asc,None)
  for key,value in list(self.restore.items()):
   p,o,mode=key
   if not all_modes and self.options.get(mode):continue
   identity,orig,mask,last=value
   if self.m and self.m.alive() and self.ue.valid(p) and self.identity(p)==identity:
    current=self.m.read(p+o,len(orig))
    if len(current)==len(orig):
     if mask:self.m.write(p+o,bytes([(current[0]&~mask)|(orig[0]&mask)]))
     elif current==last:self.m.write(p+o,orig)
   self.restore.pop(key,None)
 def number(self,p,name,value,fmt='f',mode='resources'):
  prop=self.ue.props(p).get(name)
  types={'i':('IntProperty','Int32Property'),'f':('FloatProperty',),'d':('DoubleProperty',)}
  if prop and prop[1] in types.get(fmt,()) and self.ue.valid(p):return self.write_mode(p+prop[0],struct.pack('<'+fmt,value),mode)
  return False
 def tagmap(self,asc,off):

  m=self.m;u=self.ue;data=m.u64(asc+off);n=m.u32(asc+off+8);cap=m.u32(asc+off+12)
  if not 0<n<=cap<=2048:return 0,[]
  bp=m.u64(asc+off+0x20);bits=m.read(bp,(n+7)//8) if bp else m.read(asc+off+0x10,16)
  b=m.read(data,n*20)
  if len(b)!=n*20 or len(bits)<(n+7)//8:return 0,[]
  out=[]
  for j in range(n):
   if bits[j//8]&(1<<(j%8)):
    idx,num,count=struct.unpack_from('<IIi',b,j*20)
    if num==0 and 0<=count<100000:out.append((data+j*20+8,u.name(idx),count))
  return data,out
 def invulnerable_tag(self,asc,on):
  if not self.m.known_build:return False
  data,counts=self.tagmap(asc,0xf68);_,explicit=self.tagmap(asc,0xfb8)
  tag='Character.State.Invulnerable'
  entry=next((x for x in counts if x[1]==tag),None)
  if not entry:return False
  actual=sum(x[2] for x in explicit if x[1]==tag or x[1].startswith(tag+'.'))
  if self.ue.valid(asc) and self.m.u64(asc+0xf68)==data:
   if on and not self.write_mode(entry[0],struct.pack('<i',max(1,actual)),'god'):return False
   if not on:self.m.write(entry[0],struct.pack('<i',actual))
   if on:self.tag_actors[asc]=self.identity(asc)
   return True
  return False
 def attrs(self,actor):
  asc=self.ue.ptr(actor,'AbilitySystem')
  if not self.ue.valid(asc):return []
  o=self.ue.off(asc,'SpawnedAttributes')
  return [p for p in self.ue.array(asc+o) if self.ue.valid(p)] if o else []
 def existing_tag(self,asc,tag,on,mode):
  if not self.m.known_build:return False
  data,counts=self.tagmap(asc,0xf68);_,explicit=self.tagmap(asc,0xfb8)
  entry=next((x for x in counts if x[1]==tag),None)
  if not entry:return False
  actual=sum(x[2] for x in explicit if x[1]==tag or x[1].startswith(tag+'.'))
  if not self.ue.valid(asc) or self.m.u64(asc+0xf68)!=data:return False
  if on and not self.write_mode(entry[0],struct.pack('<i',max(1,actual)),mode):return False
  if not on:self.m.write(entry[0],struct.pack('<i',actual))
  if on:self.cheat_tags[(asc,tag,mode)]=self.identity(asc)
  return self.m.u32(entry[0])>0 if on else True
 def discover(self):

  m,u=self.m,self.ue;functions=[];puzzles=[];perceptions=[];enemy_managers=[];ranged_weapons=[];ranged_classes={};worlds=[]
  targets={'ExecuteUbergraph_GA_Melee','ExecuteUbergraph_BP_EnvPuzzleBaseActor_LockpickPuzzle','SpendLockpick','SetLockpickDurability','TryToRecoil','StartWeaponCameraShake','ChangeInaccuracyOnFire'}
  try:
   for q in u.objects_iter():
    if not self.running or self.m is not m:return
    header=m.read(q,32)
    if len(header)!=32:continue
    nm=u.name(struct.unpack_from('<I',header,24)[0]);cl=struct.unpack_from('<Q',header,16)[0];class_name=u.name(m.u32(cl+24))
    if nm in targets and class_name=='Function' and u.script(q)[0]:functions.append(q)
    if class_name=='World' and u.valid(q):worlds.append(q)
    if class_name=='BP_EnvPuzzleBaseActor_LockpickPuzzle_C' and u.valid(q):puzzles.append(q)
    if class_name=='CoreAIPerceptionComponent' and u.valid(q):perceptions.append(q)
    if class_name=='EnemyManagerSubsystem' and u.valid(q):enemy_managers.append(q)
    if cl not in ranged_classes:ranged_classes[cl]=u.is_a(q,'CoreRangedWeapon')
    if ranged_classes[cl] and u.valid(q):ranged_weapons.append(q)
   if self.m is m:
    self.script_objects=functions;self.puzzles=puzzles;self.perceptions=perceptions;self.enemy_managers=enemy_managers;self.ranged_weapons=ranged_weapons;u.worlds=worlds;self.scan_done=True
  except Exception as e:self.emit('diagnostic',T('Поиск игровых механизмов: ')+str(e))
 def script_patch(self,fn,offset,original,replacement,mode):
  m,u=self.m,self.ue;script,size,_=u.script(fn);key=(fn,offset,mode)
  if not script or offset+len(original)>size:return False
  current=m.read(script+offset,len(original))
  saved=self.script_restore.get(key)
  if saved and (saved[0]!=self.identity(fn) or saved[1]!=script):self.script_restore.pop(key,None);saved=None
  if current!=original and not (saved and current==replacement):return False
  if not saved:self.script_restore[key]=(self.identity(fn),script,original,replacement)
  if not self.write_mode(script+offset,replacement,mode):return False
  return m.read(script+offset,len(replacement))==replacement
 def mechanisms(self,p,details):
  m,u=self.m,self.ue
  if time.monotonic()>=self.next_scan and not (self.scan_thread and self.scan_thread.is_alive()):
   self.next_scan=time.monotonic()+8;self.scan_thread=threading.Thread(target=self.discover,daemon=True);self.scan_thread.start()
  classoff=u.off(p,'ClassTag');playeridx=m.u32(p+classoff) if classoff else 0
  player_tag_valid=u.name(playeridx).startswith('Character.Class.Player.')
  for fn in self.script_objects:
   if not u.valid(fn):continue
   name=u.name(m.u32(fn+24));script,size,_=u.script(fn);b=m.read(script,size) if script else b''
   owner=u.name(m.u32(m.u64(fn+32)+24))

   stopmode='recoil' if name in ('TryToRecoil','StartWeaponCameraShake') else 'accuracy'
   stopnames={'TryToRecoil','StartWeaponCameraShake','ChangeInaccuracyOnFire'}
   if owner=='BP_Ranged_Weapon_C' and name in stopnames and self.options[stopmode]:
    saved=self.script_restore.get((fn,0,stopmode))
    if b.endswith(b'\x04\x0b\x53') and u.void_function(fn) and (b[0]!=0x53 or saved):
     original=saved[2] if saved else b[:3]
     if self.script_patch(fn,0,original,b'\x04\x0b\x53',stopmode):details[name+'_blocked']=True
    continue
   choices=[]
   if name=='ExecuteUbergraph_GA_Melee' and self.options['durability']:choices=[('Cheats.Character.infiniteDurability','durability')]
   if name=='ExecuteUbergraph_BP_EnvPuzzleBaseActor_LockpickPuzzle' and self.options['easylock']:choices=[('Cheats.Character.LockpickHack','easylock')]
   if name=='SpendLockpick' and self.options['lockpicks']:choices=[('Cheats.Character.LockpickHack','lockpicks')]
   for tag,mode in choices if player_tag_valid else []:
    applied=0
    for i in range(len(b)-12):
     if b[i]!=0x21:continue
     idx=struct.unpack_from('<I',b,i+1)[0];key=(fn,i+1,mode);saved=self.script_restore.get(key)
     if u.name(idx)==tag or (saved and idx==playeridx):
      original=saved[2] if saved else struct.pack('<I',idx)
      if self.script_patch(fn,i+1,original,struct.pack('<I',playeridx),mode):applied+=1
    if applied:details[mode+'_mechanism']=True
   if name=='SetLockpickDurability' and self.options['lockpicks'] and m.known_build:

    token=b'\x37'+struct.pack('<d',100.)
    for i in range(len(b)-len(token)+1):
     saved=self.script_restore.get((fn,i+1,'lockpicks'))
     if b[i:i+len(token)]==token or (saved and b[i]==0x37):
      if self.script_patch(fn,i+1,struct.pack('<d',100.),struct.pack('<d',0.),'lockpicks'):details['lockpick_formula']=True
  for q in self.puzzles:
   if not u.valid(q):continue
   o=u.off(q,'bPuzzleActive')
   if not o or m.read(q+o,1)!=b'\x01':continue
   details['active_lock']=True
   if self.options['lockpicks']:self.flag(q,'bShouldSpendLockpickOnFinish',False,'lockpicks')
   if self.options['easylock']:
    prop=u.props(q).get('CorrectAngleOffset')
    if prop and prop[1] in ('FloatProperty','DoubleProperty'):
     if self.change(q,prop[0],struct.pack('<d' if prop[1]=='DoubleProperty' else '<f',180.),'easylock'):details['easylock_mechanism']=True
 def forget_player(self,ai,p):
  if not self.m.known_build:return 0

  m,u=self.m,self.ue;header=m.read(ai+0x590,16)
  if len(header)!=16:return 0
  data,n,cap=struct.unpack('<QII',header)
  if not 0<n<=cap<=256:return 0
  chunks=m.u64(m.objects);index=m.u32(p+12)
  item=m.u64(chunks+8*(index//m.chunk_size))+m.object_stride*(index%m.chunk_size)
  serial=m.u32(item+0x10);target=struct.pack('<II',index,serial);cleared=0
  for i in range(n):
   row=data+i*0x98
   if m.read(row,8)!=target:continue
   mapheader=m.read(row+0x38,16)
   if len(mapheader)!=16:continue
   entries,count,capacity=struct.unpack('<QII',mapheader)
   bits_count=m.u32(row+0x60)
   if not 0<count<=capacity<=128 or bits_count!=count:continue
   bp=m.u64(row+0x58);bits=m.read(bp,(count+7)//8) if bp else m.read(row+0x48,16)
   if len(bits)<(count+7)//8:continue
   for j in range(count):
    if not bits[j//8]&(1<<(j%8)):continue
    element=entries+j*0x30;before=m.read(element,0x24)
    if len(before)!=0x24:continue
    value=struct.unpack_from('<f',before,0x14)[0]
    if not math.isfinite(value) or not -1<=value<=100000:continue
    if not u.valid(ai) or m.read(ai+0x590,16)!=header or m.read(row,8)!=target or m.read(row+0x38,16)!=mapheader:break
    if m.read(element,0x24)!=before:continue
    if value!=0 and self.write_mode(element+0x14,struct.pack('<f',0.),'invisible'):cleared+=1
  return cleared
 def stealth(self,p,details):
  m,u=self.m,self.ue;details['stealth_targets']=0;details['awareness_cleared']=0

  gate=m.known_build and m.read(m.base+0x56dc460,8)==b'\xc6\x81\xc8\x02\x00\x00\x00\xc3'
  details['stealth_gate_verified']=gate;details['stealth_partial_targets']=0
  candidates=set(self.perceptions)
  for manager in self.enemy_managers:
   if not u.valid(manager):continue
   off=u.off(manager,'AliveEnemies')
   for enemy in u.array(manager+off) if off else []:
    if not u.valid(enemy):continue
    ai=u.ptr(enemy,'Controller')
    if u.valid(ai):candidates.add(u.ptr(ai,'CoreAIPerceptionComponent'))
  for q in candidates:
   if not u.valid(q) or not u.is_a(q,'CoreAIPerceptionComponent'):continue
   ai=u.ptr(q,'CoreAIController')
   if not u.valid(ai) or not u.is_a(ai,'CoreAIController') or u.ptr(ai,'CoreAIPerceptionComponent')!=q:continue
   enemy=u.ptr(ai,'Pawn')
   if not u.valid(enemy) or not u.is_a(enemy,'EnemyCharacter'):continue
   if gate:self.change(q,0x2c8,b'\x00','invisible')
   reduced=0
   for field in ('DamageAwarenessIncreaseAmount','TouchAwarenessIncreaseAmount','ProximityAwarenessIncreaseAmount','FlashlightAwarenessIncreaseAmount','SightAwarenessBuildupSpeed','HearingStimulusMultiplier','AlwaysHearRange'):
    prop=u.props(q).get(field)
    if prop and prop[1]=='FloatProperty' and self.change(q,prop[0],struct.pack('<f',0.),'invisible'):reduced+=1
   details['awareness_cleared']+=self.forget_player(ai,p)
   if gate and m.read(q+0x2c8,1)==b'\x00':details['stealth_targets']+=1
   if reduced:details['stealth_partial_targets']+=1
 def attack_attributes(self,actor):
  for a in self.attrs(actor):
   if self.ue.clsname(a)=='AttackAttributeSet':
    for field in ('PhysicalDamage','PhysicalDamageHeavy','TotalDamage'):
     off=self.ue.attribute(a,field)
     if off:self.change(a,off,struct.pack('<ff',1000000.,1000000.),'onehit')
 def single_hit(self,details):

  m,u=self.m,self.ue;count=0
  for manager in self.enemy_managers:
   if not u.valid(manager):continue
   off=u.off(manager,'AliveEnemies')
   for enemy in u.array(manager+off) if off else []:
    if not u.valid(enemy) or not u.is_a(enemy,'EnemyCharacter'):continue
    for a in self.attrs(enemy):
     if not u.attribute(a,'MaxHealth'):continue
     h=u.attribute(a,'Health');current=m.flt(a+h+4) if h else float('nan')
     if not math.isfinite(current) or not 0<current<100000000:continue
     if self.change(a,h,struct.pack('<ff',min(1.,current),min(1.,current)),'onehit'):count+=1
     defense=u.attribute(a,'PhysicalDefense')
     if defense:self.change(a,defense,struct.pack('<ff',0.,0.),'onehit')
  details['onehit_enemies']=count
 def firearm(self,weapon,p,details):
  m,u=self.m,self.ue
  if not u.valid(weapon) or not u.is_a(weapon,'CoreRangedWeapon'):return
  if u.ptr(weapon,'Owner')!=p and u.ptr(u.ptr(weapon,'ItemInfo'),'Owner')!=p:return
  if self.options['recoil']:
   prop=u.props(weapon).get('RecoilMultiplier')
   if prop and prop[1]=='FloatProperty':self.change(weapon,prop[0],struct.pack('<f',0.),'recoil');details['recoil_multiplier']=True
  if self.options['accuracy']:

   applied=0
   for field in ('AimInaccuracyHipFire','AimInaccuracyADS','DefaultAimInaccuracyHipFire','DefaultAimInaccuracyADS','CurrentAimInaccuracy','FirstShotInaccuracy','CurrentExpectedAimInaccuracy'):
    prop=u.props(weapon).get(field)
    if prop and u.layout(weapon,field)==('WeaponInaccuracy',16):self.change(weapon,prop[0],b'\x00'*16,'accuracy');applied+=1
   for field in ('BloomMultiplier','BloomMultiplierADS'):
    prop=u.props(weapon).get(field)
    if prop and prop[1]=='FloatProperty':self.change(weapon,prop[0],struct.pack('<f',0.),'accuracy')
   info=u.ptr(weapon,'ItemInfo');item=u.ptr(info,'Item')
   if u.valid(item):
    for field in ('TargetOffset','ADSTargetOffset'):
     prop=u.props(item).get(field)
     if prop and u.layout(item,field)==('Vector2D',16):self.change(item,prop[0],b'\x00'*16,'accuracy')
    for field in ('StaticBloomHipFire','StaticBloomADS','MovementBloomHipFire','MovementBloomADS','BloomRate'):
     prop=u.props(item).get(field)
     if prop and u.layout(item,field)==('WeaponBloom',8):self.change(item,prop[0],b'\x00'*8,'accuracy')
    prop=u.props(item).get('BloomLimitScale')
    if prop and prop[1]=='FloatProperty':self.change(item,prop[0],struct.pack('<f',0.),'accuracy')
   assist=u.ptr(weapon,'COMP_WeaponAimAssist')
   if m.known_build and u.valid(assist) and u.layout(assist,'AimAssistConfig')==('WeaponAimAssistConfig',112):
    off=u.off(assist,'AimAssistConfig')

    for sub in (0x14,0x15,0x20,0x2c,0x2d,0x38):self.change(assist,off+sub,b'\x00','accuracy')
    for sub in (4,8,0x18,0x1c,0x30,0x34,0x3c,*range(0x4c,0x6c,4)):self.change(assist,off+sub,struct.pack('<f',0.),'accuracy')
   details['accuracy_targets']=details.get('accuracy_targets',0)+(applied==7)
   details['accuracy_partial']=details.get('accuracy_partial',0)+(applied>0)
 def infinite_hold(self,p,details):

  m,u=self.m,self.ue;prop=u.props(p).get('bTelekinesisForever')
  if not u.is_a(p,'PlayerCharacter') or not prop or prop[1]!='BoolProperty':return
  details['hold_mechanism']=bool(self.flag(p,'bTelekinesisForever',True,'hold'))
  obj=u.ptr(p,'CurrentTelekinesisObject')
  details['held_object']=hex(obj) if u.valid(obj) and u.is_a(obj,'TelekinesisBase') else None
 def tick(self):
  self.restore_off();u=self.ue;m=self.m;self.feature_errors={};self.feature_success={}
  if time.monotonic()>=self.next_scan and not (self.scan_thread and self.scan_thread.is_alive()):
   self.next_scan=time.monotonic()+8;self.scan_thread=threading.Thread(target=self.discover,daemon=True);self.scan_thread.start()
  p,w=u.player()
  if not p:self.last=T('Ожидание персонажа / поиск уровня');self.details={};self.compatibility_states={};return
  attrs=self.attrs(p);a=next((a for a in attrs if u.clsname(a)=='PlayerAttributeSet'),0)
  details={'player':hex(p),'health':None,'energy':None,'level':u.name(m.u32(w+24)),'weapons':0,'ammo_stacks':0,'melee':0,'resources':0,'lockpicks':0,'coins':None,'recoil_target':False,'invisible':False,'native_invulnerability':False}
  asc=u.ptr(p,'AbilitySystem')
  if self.options['invisible'] and u.valid(asc):details['invisible']=self.existing_tag(asc,'Cheats.Character.Invisible',True,'invisible')
  self.mechanisms(p,details)
  if self.options['hold']:self.infinite_hold(p,details)
  if self.options['invisible']:self.stealth(p,details)
  if self.options['onehit']:self.attack_attributes(p);self.single_hit(details)
  if self.options['god']:
   details['god_flag']=bool(self.flag(p,'bCanBeDamaged',False,'god'))
   asc=u.ptr(p,'AbilitySystem')
   if u.valid(asc):details['native_invulnerability']=self.invulnerable_tag(asc,True)
   if a:
    h=u.attribute(a,'Health');mx=u.attribute(a,'MaxHealth');health=m.flt(a+mx+4) if mx else float('nan')
    if h and mx and math.isfinite(health) and 0<health<1000000:
     details['god_health']=self.write_mode(a+h,struct.pack('<ff',health,health),'god')
  if a:
   h=u.attribute(a,'Health');details['health']=round(m.flt(a+h+4),1) if h else None
   if self.options['onehit']:
    o=u.attribute(a,'PhysicalAttackPower')
    if o and self.change(a,o,struct.pack('<ff',1000000.,1000000.),'onehit'):details['onehit_target']=True
  if self.options['energy']:
   details['energy_flag']=bool(self.flag(p,'bInfiniteSuffering',True,'energy'))
   details['energy_cost_flag']=bool(self.flag(p,'bIgnoreSufferingCost',True,'energy'))
   if a:
    s=u.attribute(a,'Suffering');mx=u.attribute(a,'MaxSuffering');value=m.flt(a+mx+4) if mx else float('nan')
    if s and mx and math.isfinite(value) and 0<value<100000:
     details['energy_fill']=self.write_mode(a+s,struct.pack('<ff',value,value),'energy')
  if a:
   s=u.attribute(a,'Suffering');details['energy']=round(m.flt(a+s+4),1) if s else None
  gs=u.ptr(w,'GameState');manager=u.ptr(gs,'ItemManagerReference');infos=[]
  if u.valid(manager):
   prop=u.props(manager).get('ItemsInfos');o=prop[0] if prop and prop[1]=='SetProperty' else 0
   if o:

    data=m.u64(manager+o);n=m.u32(manager+o+8);cap=m.u32(manager+o+12)
    if 0<n<=cap<=4096:
     bitmap_ptr=m.u64(manager+o+0x20)
     bitmap=m.read(bitmap_ptr,(n+7)//8) if bitmap_ptr else m.read(manager+o+0x10,16)
     if len(bitmap)>=(n+7)//8:
      b=m.read(data,n*16)
      if len(b)==n*16:infos=[struct.unpack_from('<Q',b,j*16)[0] for j in range(n) if bitmap[j//8]&(1<<(j%8))]
  for q in infos:
   if not u.valid(q) or u.ptr(q,'Owner')!=p:continue
   item=u.ptr(q,'Item')
   if not u.valid(item):continue
   ammo=u.off(q,'AmmoInClip')
   if ammo:
    details['weapons']+=1
    if self.options['ammo']:
     clip=u.off(q,'ClipSizeInfo');size=m.flt(q+clip) if clip else float('nan')
     if not math.isfinite(size) or not 1<=size<=500:size=max(1,min(99,m.u32(q+ammo)))
     self.number(q,'AmmoInClip',int(size),'i','ammo')
     after=u.off(q,'AmmoAfterReload')
     if after:self.number(q,'AmmoAfterReload',int(size),'i','ammo')
     self.flag(q,'bHasBulletInChamber',True,'ammo')
   stack=u.off(q,'StackableCount');isammo=u.is_a(item,'AmmoItem')
   if stack:details['resources']+=1
   if isammo:details['ammo_stacks']+=1
   iscurrency=u.is_a(item,'CurrencyItem')
   if stack and iscurrency:
    if self.options['coins']:self.number(q,'StackableCount',999999,'i','coins')
    details['coins']=m.u32(q+stack)
   if stack and not iscurrency and (self.options['resources'] or (self.options['ammo'] and isammo)):
    off=u.off(item,'MaxStackSize');maximum=m.u32(item+off) if off else 0
    if 1<=maximum<=9999:self.number(q,'StackableCount',maximum,'i','ammo' if self.options['ammo'] and isammo else 'resources')
   dur=u.off(q,'Durability')
   if dur and u.is_a(q,'ItemInfoLockpick'):
    details['lockpicks']+=1
    if self.options['lockpicks']:self.number(q,'Durability',100,'i','lockpicks')
   if dur and u.is_a(q,'ItemInfoMeleeWeapon'):
    details['melee']+=1
    if self.options['durability']:

     off=u.off(item,'MaxDurability');maximum=m.flt(item+off) if off and (m.known_build or u.layout(item,'MaxDurability')[0]=='ScalableFloat') else float('nan')
     current=m.u32(q+dur)
     if not math.isfinite(maximum) or not 1<=maximum<=10000:maximum=max(current,100)
     self.number(q,'Durability',max(current,int(maximum)),'i','durability')
  weapon=u.ptr(p,'CurrentEquipment')
  details['accuracy_targets']=0
  for gun in set(self.ranged_weapons+[weapon]):self.firearm(gun,p,details)
  if u.valid(weapon):
   if self.options['onehit']:self.attack_attributes(weapon)
   for wa in self.attrs(weapon):
    if self.options['onehit']:
     for field in ('WeaponDamage','WeaponDamageHeavy'):
      off=u.attribute(wa,field)
      if off and self.change(wa,off,struct.pack('<ff',1000000.,1000000.),'onehit'):details['onehit_target']=True
    o=u.attribute(wa,'Recoil')
    if o:
     details['recoil_target']=True
     if self.options['recoil']:self.change(wa,o,struct.pack('<ff',0,0),'recoil')
  self.details=details;new_states=self.feature_states(details)
  for key,_,label in MODES:
   current=new_states.get(key,{})
   if self.options[key] and current.get('state') in ('partial','unavailable') and current!=self.compatibility_states.get(key):self.emit('compatibility',T(label)+': '+current['message'],mode=key,state=current['state'])
  self.compatibility_states=new_states
  self.last=T('Подключено: Hellraiser')+(T(' · адаптация к сборке ')+m.build_id if not m.known_build else '');self.errors=0
 def feature_states(self,d):
  states={}
  def put(key,state,message):states[key]={'state':state,'message':message}
  for key,_,_ in MODES:
   if key in self.feature_errors:
    put(key,'unavailable',T('Не работает: ')+self.feature_errors[key]);continue
   ok=self.feature_success.get(key,0)>0
   if key=='god':
    if d.get('native_invulnerability'):put(key,'available',T('Неуязвимость: игровой тег и защита'))
    elif d.get('god_flag') or d.get('god_health'):put(key,'partial',T('Защита работает · абсолютный тег не подтверждён'))
    else:put(key,'unavailable',T('Эта версия: механизм защиты не найден'))
   elif key=='energy':
    if d.get('energy_flag') and d.get('energy_cost_flag'):put(key,'available',T('Энергия и стоимость способностей отключены'))
    elif ok:put(key,'partial',T('Энергия пополняется · часть механизмов не найдена'))
    else:put(key,'unavailable',T('Эта версия: механизм энергии не найден'))
   elif key=='hold':put(key,'available' if d.get('hold_mechanism') else 'unavailable',T('Удержание без таймера') if d.get('hold_mechanism') else T('Эта версия: режим бесконечного удержания не найден'))
   elif key=='invisible':
    if d.get('stealth_targets'):put(key,'available',T('Восприятие отключено · врагов: ')+str(d["stealth_targets"]))
    elif d.get('stealth_partial_targets'):put(key,'partial',T('Восприятие снижено · полная невидимость не подтверждена'))
    elif not self.scan_done:put(key,'searching',T('Поиск механизмов невидимости'))
    else:put(key,'waiting',T('Ожидание врагов') if self.m.known_build else T('Ожидание врагов · полная невидимость этой версии не подтверждена'))
   elif key=='recoil':
    if d.get('TryToRecoil_blocked') and d.get('StartWeaponCameraShake_blocked'):put(key,'available',T('Рывок камеры и тряска отключены'))
    elif ok:put(key,'partial',T('Частично: найдена не вся система отдачи'))
    else:put(key,'unavailable' if self.scan_done and d.get('weapons') else 'waiting',T('Эта версия: механизмы отдачи не найдены') if self.scan_done and d.get('weapons') else T('Поиск функций / ожидание оружия'))
   elif key=='accuracy':
    if d.get('accuracy_targets'):put(key,'available' if self.m.known_build else 'partial',T('Разброс и смещение сняты') if self.m.known_build else T('Разброс снят · доведение прицела не подтверждено'))
    elif d.get('accuracy_partial') or ok:put(key,'partial',T('Частично: найдены не все параметры точности'))
    else:put(key,'waiting',T('Ожидание выбранного огнестрельного оружия'))
   elif key=='durability':
    if d.get('durability_mechanism'):put(key,'available',T('Расход прочности в атаке отключён'))
    elif ok:put(key,'partial',T('Прочность пополняется · запрет износа не найден'))
    else:put(key,'unavailable' if self.scan_done and d.get('melee') else 'waiting',T('Эта версия: защита прочности не найдена') if self.scan_done and d.get('melee') else T('Поиск функций / ожидание оружия'))
   elif key=='lockpicks':
    if d.get('lockpick_formula') and d.get('lockpicks_mechanism'):put(key,'available',T('Износ и расход отмычек отключены'))
    elif ok:put(key,'partial',T('Отмычки защищены частично · часть механизмов не найдена'))
    else:put(key,'waiting',T('Ожидание отмычек / загрузки взлома'))
   elif key=='easylock':put(key,'available' if d.get('easylock_mechanism') else 'waiting',T('Лёгкий взлом включён') if d.get('easylock_mechanism') else T('Поиск функций / ожидание замка'))
   elif key=='onehit':
    if d.get('onehit_target'):put(key,'available',T('Урон усилен · врагов с 1 HP: ')+str(d.get("onehit_enemies",0)))
    elif ok:put(key,'partial',T('Частично: изменены не все параметры урона'))
    else:put(key,'unavailable' if self.scan_done else 'searching',T('Эта версия: параметры урона не найдены') if self.scan_done else T('Поиск параметров урона'))
   elif key in ('ammo','coins','resources'):
    if ok:put(key,'available',T('Монет: ')+f'{d["coins"]:,}'.replace(',',' ') if key=='coins' and d.get('coins') is not None else T('Пополнение работает'))
    elif (key=='coins' and d.get('coins') is not None) or (key=='resources' and d.get('resources')) or (key=='ammo' and (d.get('weapons') or d.get('ammo_stacks'))):put(key,'unavailable',T('Эта версия: подходящее свойство не найдено'))
    else:put(key,'waiting',T('Ожидание монет в инвентаре') if key=='coins' else T('Ожидание предметов / оружия в инвентаре'))
  return states
 def snapshot(self):return {'status':self.last,'pid':self.m.pid if self.m and self.m.alive() else None,'game_started':getattr(self.m,'created',None),'game_path':getattr(self.m,'path',None),'trainer_pid':os.getpid(),'trainer_started':self.started,'enabled':dict(self.options),'details':dict(self.details),'features':dict(self.compatibility_states),'build':getattr(self.m,'build_id',None),'adaptive':bool(self.m and not self.m.known_build),'compatibility_error':self.last_connect_error,'errors':self.errors,'time':time.time()}
 def control(self):
  try:
   stamp=CONTROL.stat().st_mtime_ns
   if stamp==self.seen_control:return
   self.seen_control=stamp;data=json.loads(CONTROL.read_text(encoding='utf-8-sig'))
   for k in self.options:
    if k in data:self.options[k]=bool(data[k])
   if data.get('quit'):self.running=False
  except (OSError,ValueError):pass
 def loop(self):
  next_status=0;next_connect=0;previous_options=dict(self.options);previous_status=None;previous_player=None
  try:
   while self.running:
    self.control()
    if self.rescan_requested:self.rescan_requested=False;next_connect=0
    for k,_,label in MODES:
     if self.options[k]!=previous_options[k]:self.emit('mode',T(label)+(T(' — включено') if self.options[k] else T(' — выключено')),mode=k,enabled=self.options[k])
    previous_options=dict(self.options)
    try:
     if self.m and not self.m.alive():self.emit('game',T('Игра завершена'),pid=self.m.pid);self.restore.clear();self.tag_actors.clear();self.globals_restore.clear();self.script_restore.clear();self.cheat_tags.clear();self.script_objects=[];self.puzzles=[];self.perceptions=[];self.enemy_managers=[];self.ranged_weapons=[];self.m.close();self.m=None;self.ue=None;self.details={}
     if not self.m and time.monotonic()>=next_connect:
      next_connect=time.monotonic()+2
      if not self.connect():self.last=T('Ожидание запущенной Hellraiser')
     if self.m:self.tick()
    except Exception as e:
     self.errors+=1;self.last=str(e)
     if not self.m:self.last_connect_error=str(e);next_connect=time.monotonic()+15
    if self.last!=previous_status:self.emit('status',self.last,errors=self.errors);previous_status=self.last
    if self.details.get('player')!=previous_player:
     previous_player=self.details.get('player')
     if previous_player:self.emit('level',T('Найден персонаж: ')+self.details.get('level',''),player=previous_player)
    if time.monotonic()>=next_status:
     next_status=time.monotonic()+1
     try:STATUS.write_text(json.dumps(self.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')
     except OSError:pass
    time.sleep(.05)
  finally:
   try:self.restore_off(True)
   finally:
    if self.m:self.m.close()
    self.last=T('Трейнер остановлен; флаги восстановлены');self.m=None
    try:STATUS.write_text(json.dumps(self.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')
    except OSError:pass
