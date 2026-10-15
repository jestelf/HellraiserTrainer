import struct
from lang import T

def pointer(value):
    return 0x10000 < value < 0x7fffffffffff and value % 8 == 0

def pe_layout(m):
    header = m.read(m.base, 0x1000)
    if len(header) < 64 or header[:2] != b'MZ':
        raise RuntimeError(T('Не удалось прочитать заголовок игры.'))
    pe = struct.unpack_from('<I', header, 0x3c)[0]
    if not 0x40 <= pe <= 0x800 or header[pe:pe+4] != b'PE\0\0':
        raise RuntimeError(T('Не распознан формат игрового EXE.'))
    machine, count = struct.unpack_from('<HH', header, pe+4)
    optional = struct.unpack_from('<H', header, pe+20)[0]
    if machine != 0x8664 or struct.unpack_from('<H', header, pe+24)[0] != 0x20b:
        raise RuntimeError(T('Поддерживается только Windows x64.'))
    size = struct.unpack_from('<I', header, pe+0x50)[0]
    if not 0x100000 <= size <= 0x40000000 or not 1 <= count <= 96:
        raise RuntimeError(T('Неверные границы игрового модуля.'))
    end = pe+24+optional+count*40
    if end > len(header):
        header = m.read(m.base, end)
    if len(header) < end:
        raise RuntimeError(T('Не прочитана таблица секций EXE.'))
    sections = []
    for i in range(count):
        off = pe+24+optional+i*40
        name = header[off:off+8].rstrip(b'\0').decode('ascii', errors='replace')
        length, rva = struct.unpack_from('<II', header, off+8)
        flags = struct.unpack_from('<I', header, off+36)[0]
        if length and rva >= 0x1000 and rva+length <= size:
            sections.append((name, rva, length, flags))
    if not any(s[3] & 0x20000000 for s in sections):
        raise RuntimeError(T('Не найдены секции кода игры.'))
    return struct.unpack_from('<I', header, pe+8)[0], size, sections

def executable(m, address):
    rva = address-m.base
    return any(start <= rva < start+length and flags & 0x20000000
               for _, start, length, flags in m.sections)

class Names:
    def __init__(self, m, pool, shift):
        self.m, self.pool, self.shift = m, pool, shift

    def name(self, index):
        block = index >> 16
        if block > 8191:
            return '?'
        ptr = self.m.u64(self.pool+16+block*8)
        if not pointer(ptr):
            return '?'
        address = ptr+(index & 65535)*2
        raw = self.m.read(address, 2)
        if len(raw) != 2:
            return '?'
        header = struct.unpack('<H', raw)[0]
        length = header >> self.shift
        if not 0 < length < 1024:
            return '?'
        raw = self.m.read(address+2, length*(2 if header & 1 else 1))
        if len(raw) != length*(2 if header & 1 else 1):
            return '?'
        try:
            value = raw.decode('utf-16le' if header & 1 else 'utf-8')
        except UnicodeError:
            return '?'
        return value if all(ord(c) >= 32 for c in value) else '?'

def name_pool(m, rva):
    raw = m.read(m.base+rva, 24)
    if len(raw) != 24:
        return None
    block, cursor, first = struct.unpack_from('<IIQ', raw, 8)
    if not 0 <= block < 8192 or not 8 <= cursor <= 131072 or not pointer(first):
        return None
    if m.base <= first < m.base+m.image_size:
        return None
    for shift in (6, 1, 5):
        names = Names(m, m.base+rva, shift)
        if names.name(0) != 'None':
            continue

        sample = m.read(first, 1024)
        if sum(value in sample for value in (b'ByteProperty', b'IntProperty', b'BoolProperty', b'ObjectProperty')) < 3:
            continue
        if not pointer(m.u64(m.base+rva+16+block*8)):
            continue
        return names
    return None

def object_array(m, rva, names):
    raw = m.read(m.base+rva, 32)
    if len(raw) != 32:
        return None
    chunks, _, maximum, count, max_chunks, num_chunks = struct.unpack('<QQIIII', raw)
    if not pointer(chunks) or not 8 <= count <= maximum <= 16000000:
        return None
    if not 1 <= num_chunks <= max_chunks <= 1024 or maximum % max_chunks:
        return None
    chunk_size = maximum//max_chunks
    if chunk_size not in (16384, 32768, 65536, 131072, 262144) or (count+chunk_size-1)//chunk_size > num_chunks:
        return None
    for stride in (24, 32):
        good = 0
        for index in (0, 1, 2, 3, 7, count//2, count-1):
            chunk = m.u64(chunks+8*(index//chunk_size))
            if not pointer(chunk):
                continue
            obj = m.u64(chunk+stride*(index % chunk_size))
            raw_obj = m.read(obj, 40) if pointer(obj) else b''
            if len(raw_obj) != 40:
                continue
            vtable, flags, actual_index, cls = struct.unpack_from('<QIIQ', raw_obj)
            if actual_index != index or flags & 0x8000 or not pointer(cls):
                continue
            if not m.base < vtable < m.base+m.image_size or not executable(m, m.u64(vtable)):
                continue
            if names.name(m.u32(cls+24)) not in ('Class', 'Package', 'ScriptStruct', 'Function', 'BlueprintGeneratedClass'):
                continue
            if names.name(struct.unpack_from('<I', raw_obj, 24)[0]) == '?':
                continue
            good += 1
        if good >= 3:
            return {'rva': rva, 'stride': stride, 'chunk_size': chunk_size}
    return None

def writable_blocks(m):

    for _, rva, size, flags in m.sections:
        if not flags & 0x80000000 or flags & 0x20000000:
            continue
        for offset in range(0, size, 0x30000):
            data = m.read(m.base+rva+offset, min(0x30000+32, size-offset))
            if data:
                yield rva+offset, data

def resolve(m, known_pool=None, known_objects=None, progress=None):
    say = progress or (lambda value: None)
    say(T('Поиск таблицы игровых имён…'))
    pools = []
    if known_pool is not None:
        names = name_pool(m, known_pool)
        if names:
            pools.append(names)
    object_candidates = []

    if pools and known_objects is not None:
        array = object_array(m, known_objects, pools[0])
        if array:
            return pools[0], array
    for rva, raw in writable_blocks(m):
        for off in range(0, len(raw)-31, 8):
            block, cursor, first = struct.unpack_from('<IIQ', raw, off+8)
            if block < 8192 and 8 <= cursor <= 131072 and pointer(first) and not m.base <= first < m.base+m.image_size:
                candidate = name_pool(m, rva+off)
                if candidate and all(candidate.pool != n.pool for n in pools):
                    pools.append(candidate)
            chunks, _, maximum, count, maximum_chunks, used = struct.unpack_from('<QQIIII', raw, off)
            if pointer(chunks) and 8 <= count <= maximum <= 16000000 and 1 <= used <= maximum_chunks <= 1024:
                object_candidates.append(rva+off)
    if not pools:
        raise RuntimeError(T('Эта сборка: таблица имён UE не найдена. Функции недоступны.'))
    say(T('Проверка игровых объектов и структуры движка…'))
    matches = []
    for names in pools:
        for rva in dict.fromkeys(object_candidates):
            array = object_array(m, rva, names)
            if array:
                matches.append((names, array))
    unique = {(names.pool, array['rva']): (names, array) for names, array in matches}
    if len(unique) != 1:
        reason = T('не найдена') if not unique else T('неоднозначна')
        raise RuntimeError(T('Эта сборка: таблица объектов UE ')+reason+T('. Запись отключена.'))
    return next(iter(unique.values()))
