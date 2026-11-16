#!/usr/bin/env python3
"""Build a self-contained Android DEX binary (`agentdroid-input.dex`) for `com.agentdroid.InputDaemon`.

The daemon runs persistently inside Android via `app_process` and injects touch/key/text
events directly through `android.hardware.input.InputManager.injectInputEvent(...)`,
eliminating the ~670ms ART JVM cold-start overhead of `adb shell input tap`.

Protocol (UTF-8 newline-delimited over loopback 127.0.0.1:18889):
    <token>\tping
    <token>\ttap\t<x>\t<y>
    <token>\tswipe\t<x1>\t<y1>\t<x2>\t<y2>\t<duration_ms>
    <token>\tlong_press\t<x>\t<y>\t<duration_ms>
    <token>\tkey\t<keycode_name_or_int>
    <token>\ttext_b64\t<base64_utf8>

Responses:
    OK\n | OK pong\n | ERR <message>\n
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import zlib

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DEX = REPO_ROOT / "packages" / "agentdroid-input-daemon" / "agentdroid-input.dex"


def uleb128(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val != 0:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def sleb128(val: int) -> bytes:
    out = bytearray()
    more = True
    while more:
        b = val & 0x7F
        val >>= 7
        if (val == 0 and (b & 0x40) == 0) or (val == -1 and (b & 0x40) != 0):
            more = False
        else:
            b |= 0x80
        out.append(b)
    return bytes(out)


def mutf8_encode(s: str) -> bytes:
    raw = s.encode("utf-8")
    return uleb128(len(s)) + raw + b"\x00"


class Asm:
    """Symbolic Dalvik 035 instruction assembler with automatic label and try/catch resolution."""

    def __init__(self, pool: DexBuilder) -> None:
        self.pool = pool
        self.words: list[int] = []
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str, str]] = []  # (word_pos_of_offset, origin_pc_word_pos, label)
        self.tries: list[tuple[str, str, list[tuple[str | None, str]]]] = []

    def pc(self) -> int:
        return len(self.words)

    def label(self, name: str) -> None:
        self.labels[name] = len(self.words)

    def try_catch(self, start_lbl: str, end_lbl: str, catches: list[tuple[str | None, str]]) -> None:
        self.tries.append((start_lbl, end_lbl, catches))

    def nop(self) -> None:
        self.words.append(0x0000)

    def move(self, dst: int, src: int) -> None:
        assert dst < 16 and src < 16
        self.words.append((src << 12) | (dst << 8) | 0x01)

    def move16(self, dst: int, src: int) -> None:
        self.words.extend([(dst << 8) | 0x02, src])

    def move_wide(self, dst: int, src: int) -> None:
        assert dst < 16 and src < 16
        self.words.append((src << 12) | (dst << 8) | 0x04)

    def move_wide16(self, dst: int, src: int) -> None:
        self.words.extend([(dst << 8) | 0x05, src])

    def move_obj(self, dst: int, src: int) -> None:
        if dst < 16 and src < 16:
            self.words.append((src << 12) | (dst << 8) | 0x07)
        else:
            self.words.extend([(dst << 8) | 0x08, src])

    def move_res(self, dst: int) -> None:
        self.words.append((dst << 8) | 0x0A)

    def move_res_wide(self, dst: int) -> None:
        self.words.append((dst << 8) | 0x0B)

    def move_res_obj(self, dst: int) -> None:
        self.words.append((dst << 8) | 0x0C)

    def move_exc(self, dst: int) -> None:
        self.words.append((dst << 8) | 0x0D)

    def ret_void(self) -> None:
        self.words.append(0x000E)

    def ret(self, reg: int) -> None:
        self.words.append((reg << 8) | 0x0F)

    def ret_obj(self, reg: int) -> None:
        self.words.append((reg << 8) | 0x11)

    def const4(self, reg: int, val: int) -> None:
        assert reg < 16 and -8 <= val <= 7
        self.words.append(((val & 0xF) << 12) | (reg << 8) | 0x12)

    def const16(self, reg: int, val: int) -> None:
        self.words.extend([(reg << 8) | 0x13, val & 0xFFFF])

    def const32(self, reg: int, val: int) -> None:
        u = val & 0xFFFFFFFF
        self.words.extend([(reg << 8) | 0x14, u & 0xFFFF, (u >> 16) & 0xFFFF])

    def const_float(self, reg: int, fval: float) -> None:
        bits = struct.unpack("<I", struct.pack("<f", fval))[0]
        self.const32(reg, bits)

    def const_wide16(self, reg: int, val: int) -> None:
        self.words.extend([(reg << 8) | 0x16, val & 0xFFFF])

    def const_str(self, reg: int, text: str) -> None:
        idx = self.pool.str_idx(text)
        self.words.extend([(reg << 8) | 0x1A, idx])

    def array_len(self, dst: int, arr: int) -> None:
        assert dst < 16 and arr < 16
        self.words.append((arr << 12) | (dst << 8) | 0x21)

    def new_inst(self, reg: int, desc: str) -> None:
        idx = self.pool.type_idx(desc)
        self.words.extend([(reg << 8) | 0x22, idx])

    def goto(self, lbl: str) -> None:
        origin = len(self.words)
        self.words.extend([0x0029, 0x0000])
        self.fixups.append((origin + 1, origin, lbl))

    def cmp_long(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0x31, (b << 8) | a])

    def if_cmp(self, op: int, a: int, b: int, lbl: str) -> None:
        assert a < 16 and b < 16
        origin = len(self.words)
        self.words.extend([(b << 12) | (a << 8) | op, 0x0000])
        self.fixups.append((origin + 1, origin, lbl))

    def if_eq(self, a: int, b: int, lbl: str) -> None:
        self.if_cmp(0x32, a, b, lbl)

    def if_ne(self, a: int, b: int, lbl: str) -> None:
        self.if_cmp(0x33, a, b, lbl)

    def if_lt(self, a: int, b: int, lbl: str) -> None:
        self.if_cmp(0x34, a, b, lbl)

    def if_ge(self, a: int, b: int, lbl: str) -> None:
        self.if_cmp(0x35, a, b, lbl)

    def if_z(self, op: int, reg: int, lbl: str) -> None:
        origin = len(self.words)
        self.words.extend([(reg << 8) | op, 0x0000])
        self.fixups.append((origin + 1, origin, lbl))

    def if_eqz(self, reg: int, lbl: str) -> None:
        self.if_z(0x38, reg, lbl)

    def if_nez(self, reg: int, lbl: str) -> None:
        self.if_z(0x39, reg, lbl)

    def if_gez(self, reg: int, lbl: str) -> None:
        self.if_z(0x3B, reg, lbl)

    def if_ltz(self, reg: int, lbl: str) -> None:
        self.if_z(0x3A, reg, lbl)

    def if_lez(self, reg: int, lbl: str) -> None:
        self.if_z(0x3D, reg, lbl)

    def aget_obj(self, dst: int, arr: int, idx_reg: int) -> None:
        self.words.extend([(dst << 8) | 0x46, (idx_reg << 8) | arr])

    def iget_obj(self, dst: int, obj: int, cls: str, name: str, typ: str) -> None:
        assert dst < 16 and obj < 16
        fidx = self.pool.field_idx(cls, name, typ)
        self.words.extend([(obj << 12) | (dst << 8) | 0x54, fidx])

    def iput_obj(self, src: int, obj: int, cls: str, name: str, typ: str) -> None:
        assert src < 16 and obj < 16
        fidx = self.pool.field_idx(cls, name, typ)
        self.words.extend([(obj << 12) | (src << 8) | 0x5B, fidx])

    def sget_obj(self, dst: int, cls: str, name: str, typ: str) -> None:
        fidx = self.pool.field_idx(cls, name, typ)
        self.words.extend([(dst << 8) | 0x62, fidx])

    def sput_obj(self, src: int, cls: str, name: str, typ: str) -> None:
        fidx = self.pool.field_idx(cls, name, typ)
        self.words.extend([(src << 8) | 0x69, fidx])

    def _invoke35c(self, op: int, regs: list[int], midx: int) -> None:
        assert len(regs) <= 5 and all(r < 16 for r in regs)
        n = len(regs)
        padded = regs + [0] * (5 - n)
        c, d, e, f, g = padded
        self.words.extend([
            (n << 12) | (g << 8) | op,
            midx,
            (f << 12) | (e << 8) | (d << 4) | c,
        ])

    def _invoke3rc(self, op: int, start_reg: int, count: int, midx: int) -> None:
        assert 0 <= count <= 255
        self.words.extend([(count << 8) | op, midx, start_reg])

    def invoke_virtual(self, regs: list[int], cls: str, name: str, ret: str, params: list[str]) -> None:
        midx = self.pool.method_idx(cls, name, ret, params)
        self._invoke35c(0x6E, regs, midx)

    def invoke_direct(self, regs: list[int], cls: str, name: str, ret: str, params: list[str]) -> None:
        midx = self.pool.method_idx(cls, name, ret, params)
        self._invoke35c(0x70, regs, midx)

    def invoke_static(self, regs: list[int], cls: str, name: str, ret: str, params: list[str]) -> None:
        midx = self.pool.method_idx(cls, name, ret, params)
        self._invoke35c(0x71, regs, midx)

    def invoke_virtual_range(self, start: int, count: int, cls: str, name: str, ret: str, params: list[str]) -> None:
        midx = self.pool.method_idx(cls, name, ret, params)
        self._invoke3rc(0x74, start, count, midx)

    def invoke_direct_range(self, start: int, count: int, cls: str, name: str, ret: str, params: list[str]) -> None:
        midx = self.pool.method_idx(cls, name, ret, params)
        self._invoke3rc(0x76, start, count, midx)

    def invoke_static_range(self, start: int, count: int, cls: str, name: str, ret: str, params: list[str]) -> None:
        midx = self.pool.method_idx(cls, name, ret, params)
        self._invoke3rc(0x77, start, count, midx)

    def int_to_long(self, dst: int, src: int) -> None:
        assert dst < 16 and src < 16
        self.words.append((src << 12) | (dst << 8) | 0x81)

    def int_to_float(self, dst: int, src: int) -> None:
        assert dst < 16 and src < 16
        self.words.append((src << 12) | (dst << 8) | 0x82)

    def long_to_float(self, dst: int, src: int) -> None:
        assert dst < 16 and src < 16
        self.words.append((src << 12) | (dst << 8) | 0x85)

    def add_long(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0x9B, (b << 8) | a])

    def sub_long(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0x9C, (b << 8) | a])

    def add_float(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0xA6, (b << 8) | a])

    def sub_float(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0xA7, (b << 8) | a])

    def mul_float(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0xA8, (b << 8) | a])

    def div_float(self, dst: int, a: int, b: int) -> None:
        self.words.extend([(dst << 8) | 0xA9, (b << 8) | a])

    def add_int_lit8(self, dst: int, src: int, lit: int) -> None:
        self.words.extend([(dst << 8) | 0xD8, ((lit & 0xFF) << 8) | src])

    def resolve(self) -> None:
        for fix_pos, origin, lbl in self.fixups:
            target = self.labels[lbl]
            delta = target - origin
            self.words[fix_pos] = delta & 0xFFFF


class DexBuilder:
    def __init__(self) -> None:
        self.strings: set[str] = set()
        self.types: set[str] = set()
        self.protos: set[tuple[str, tuple[str, ...]]] = set()
        self.fields: set[tuple[str, str, str]] = set()
        self.methods: set[tuple[str, str, str, tuple[str, ...]]] = set()
        self.class_fields: list[tuple[tuple[str, str, str], int]] = []
        self.direct_methods: list[tuple[tuple[str, str, str, tuple[str, ...]], int, Asm, int, int, int]] = []
        self.virtual_methods: list[tuple[tuple[str, str, str, tuple[str, ...]], int, Asm, int, int, int]] = []
        self._sorted_strings: list[str] = []
        self._sorted_types: list[str] = []
        self._sorted_protos: list[tuple[str, tuple[str, ...]]] = []
        self._sorted_fields: list[tuple[str, str, str]] = []
        self._sorted_methods: list[tuple[str, str, str, tuple[str, ...]]] = []
        self._finalized = False

    def add_str(self, s: str) -> str:
        self.strings.add(s)
        return s

    def add_type(self, desc: str) -> str:
        self.strings.add(desc)
        self.types.add(desc)
        return desc

    def add_proto(self, ret: str, params: list[str]) -> tuple[str, tuple[str, ...]]:
        self.add_type(ret)
        for p in params:
            self.add_type(p)
        shorty = self._shorty(ret, params)
        self.add_str(shorty)
        key = (ret, tuple(params))
        self.protos.add(key)
        return key

    def add_field(self, cls: str, name: str, typ: str) -> tuple[str, str, str]:
        self.add_type(cls)
        self.add_str(name)
        self.add_type(typ)
        key = (cls, name, typ)
        self.fields.add(key)
        return key

    def add_method(self, cls: str, name: str, ret: str, params: list[str]) -> tuple[str, str, str, tuple[str, ...]]:
        self.add_type(cls)
        self.add_str(name)
        self.add_proto(ret, params)
        key = (cls, name, ret, tuple(params))
        self.methods.add(key)
        return key

    @staticmethod
    def _shorty(ret: str, params: list[str]) -> str:
        def ch(t: str) -> str:
            return "L" if t[0] in ("L", "[") else t

        return ch(ret) + "".join(ch(p) for p in params)

    def str_idx(self, s: str) -> int:
        if not self._finalized:
            self.add_str(s)
            return 0
        return self._sorted_strings.index(s)

    def type_idx(self, desc: str) -> int:
        if not self._finalized:
            self.add_type(desc)
            return 0
        return self._sorted_types.index(desc)

    def proto_idx(self, ret: str, params: list[str]) -> int:
        if not self._finalized:
            self.add_proto(ret, params)
            return 0
        return self._sorted_protos.index((ret, tuple(params)))

    def field_idx(self, cls: str, name: str, typ: str) -> int:
        if not self._finalized:
            self.add_field(cls, name, typ)
            return 0
        return self._sorted_fields.index((cls, name, typ))

    def method_idx(self, cls: str, name: str, ret: str, params: list[str]) -> int:
        if not self._finalized:
            self.add_method(cls, name, ret, params)
            return 0
        return self._sorted_methods.index((cls, name, ret, tuple(params)))

    def define_field(self, cls: str, name: str, typ: str, flags: int) -> None:
        self.class_fields.append((self.add_field(cls, name, typ), flags))

    def define_method(
        self,
        cls: str,
        name: str,
        ret: str,
        params: list[str],
        flags: int,
        regs: int,
        ins: int,
        outs: int,
        virtual: bool = False,
    ) -> Asm:
        key = self.add_method(cls, name, ret, params)
        asm = Asm(self)
        entry = (key, flags, asm, regs, ins, outs)
        if virtual:
            self.virtual_methods.append(entry)
        else:
            self.direct_methods.append(entry)
        return asm


class MethodDef:
    def __init__(self, cls: str, name: str, ret: str, params: list[str], flags: int, regs: int, ins: int, outs: int, virtual: bool, emit_fn):
        self.cls = cls
        self.name = name
        self.ret = ret
        self.params = params
        self.flags = flags
        self.regs = regs
        self.ins = ins
        self.outs = outs
        self.virtual = virtual
        self.emit_fn = emit_fn


def compile_dex(main_cls: str, super_cls: str, ifaces: list[str], fields: list[tuple[str, str, int]], methods: list[MethodDef]) -> bytes:
    pool = DexBuilder()
    pool.add_type(main_cls)
    pool.add_type(super_cls)
    for iface in ifaces:
        pool.add_type(iface)
    for fname, ftype, _ in fields:
        pool.add_field(main_cls, fname, ftype)
    for m in methods:
        pool.add_method(m.cls, m.name, m.ret, m.params)
        dummy = Asm(pool)
        m.emit_fn(dummy)
        for _, _, catches in dummy.tries:
            for t, _ in catches:
                if t is not None:
                    pool.add_type(t)

    pool._sorted_strings = sorted(pool.strings)
    pool._sorted_types = sorted(pool.types, key=lambda d: pool._sorted_strings.index(d))
    pool._sorted_protos = sorted(
        pool.protos,
        key=lambda p: (pool._sorted_types.index(p[0]), tuple(pool._sorted_types.index(x) for x in p[1])),
    )
    pool._sorted_fields = sorted(
        pool.fields,
        key=lambda f: (
            pool._sorted_types.index(f[0]),
            pool._sorted_strings.index(f[1]),
            pool._sorted_types.index(f[2]),
        ),
    )
    pool._sorted_methods = sorted(
        pool.methods,
        key=lambda m: (
            pool._sorted_types.index(m[0]),
            pool._sorted_strings.index(m[1]),
            pool._sorted_protos.index((m[2], m[3])),
        ),
    )
    pool._finalized = True

    # Emit actual bytecode with finalized constant pool indices
    compiled_methods: list[tuple[MethodDef, int, Asm]] = []
    for m in methods:
        asm = Asm(pool)
        m.emit_fn(asm)
        asm.resolve()
        midx = pool.method_idx(m.cls, m.name, m.ret, m.params)
        compiled_methods.append((m, midx, asm))

    # Build data section pieces in clean deterministic order
    # Layout:
    # 1. Header (0x70)
    # 2. string_ids (4 * N)
    # 3. type_ids (4 * N)
    # 4. proto_ids (12 * N)
    # 5. field_ids (8 * N)
    # 6. method_ids (8 * N)
    # 7. class_defs (32 * 1)
    # 8. Data section:
    #    - type_lists (4-byte aligned)
    #    - code_items (4-byte aligned)
    #    - string_data_items (1-byte aligned)
    #    - class_data_item (1-byte aligned)
    #    - map_list (4-byte aligned)

    header_size = 0x70
    str_ids_off = header_size
    type_ids_off = str_ids_off + 4 * len(pool._sorted_strings)
    proto_ids_off = type_ids_off + 4 * len(pool._sorted_types)
    field_ids_off = proto_ids_off + 12 * len(pool._sorted_protos)
    method_ids_off = field_ids_off + 8 * len(pool._sorted_fields)
    class_defs_off = method_ids_off + 8 * len(pool._sorted_methods)
    data_off = class_defs_off + 32  # 1 class_def

    data = bytearray()
    map_entries: list[tuple[int, int, int]] = []  # (type_code, count, file_offset)

    def align4() -> None:
        while (data_off + len(data)) % 4 != 0:
            data.append(0)

    # Type lists: for interfaces + proto parameter lists
    type_list_offsets: dict[tuple[str, ...], int] = {}
    needed_type_lists: list[tuple[str, ...]] = []
    if ifaces:
        needed_type_lists.append(tuple(ifaces))
    for _, params in pool._sorted_protos:
        if params and params not in needed_type_lists:
            needed_type_lists.append(params)

    if needed_type_lists:
        align4()
        tl_section_start = data_off + len(data)
        for tl in needed_type_lists:
            align4()
            type_list_offsets[tl] = data_off + len(data)
            data.extend(struct.pack("<I", len(tl)))
            for t in tl:
                data.extend(struct.pack("<H", pool.type_idx(t)))
        map_entries.append((0x1001, len(needed_type_lists), tl_section_start))

    # Code items
    align4()
    code_section_start = data_off + len(data)
    code_offsets: dict[int, int] = {}
    for m, midx, asm in compiled_methods:
        align4()
        code_offsets[midx] = data_off + len(data)
        tries_size = len(asm.tries)
        insns_size = len(asm.words)
        data.extend(struct.pack("<HHHHI", m.regs, m.ins, m.outs, tries_size, 0))
        data.extend(struct.pack("<I", insns_size))
        for w in asm.words:
            data.extend(struct.pack("<H", w))
        if tries_size > 0:
            if insns_size % 2 == 1:
                data.extend(b"\x00\x00")
            # Build encoded_catch_handler_list
            handler_blob = bytearray(uleb128(tries_size))
            try_items = bytearray()
            for start_lbl, end_lbl, catches in asm.tries:
                s_pc = asm.labels[start_lbl]
                e_pc = asm.labels[end_lbl]
                h_off = len(handler_blob)
                try_items.extend(struct.pack("<IHH", s_pc, e_pc - s_pc, h_off))
                has_catch_all = any(t is None for t, _ in catches)
                explicit = [(t, lbl) for t, lbl in catches if t is not None]
                catch_all_lbl = next((lbl for t, lbl in catches if t is None), None)
                size_val = -len(explicit) if has_catch_all else len(explicit)
                handler_blob.extend(sleb128(size_val))
                for t, lbl in explicit:
                    handler_blob.extend(uleb128(pool.type_idx(t)))
                    handler_blob.extend(uleb128(asm.labels[lbl]))
                if catch_all_lbl is not None:
                    handler_blob.extend(uleb128(asm.labels[catch_all_lbl]))
            data.extend(try_items)
            data.extend(handler_blob)
    map_entries.append((0x2001, len(compiled_methods), code_section_start))

    # String data items
    str_data_section_start = data_off + len(data)
    str_data_offsets: list[int] = []
    for s in pool._sorted_strings:
        str_data_offsets.append(data_off + len(data))
        data.extend(mutf8_encode(s))
    map_entries.append((0x2002, len(pool._sorted_strings), str_data_section_start))

    # Class data item (1 class)
    class_data_off = data_off + len(data)
    static_fields = sorted([(pool.field_idx(main_cls, n, t), fl) for n, t, fl in fields if fl & 0x0008])
    inst_fields = sorted([(pool.field_idx(main_cls, n, t), fl) for n, t, fl in fields if not (fl & 0x0008)])
    direct_m = sorted([(midx, m.flags, code_offsets[midx]) for m, midx, _ in compiled_methods if not m.virtual])
    virt_m = sorted([(midx, m.flags, code_offsets[midx]) for m, midx, _ in compiled_methods if m.virtual])

    data.extend(uleb128(len(static_fields)))
    data.extend(uleb128(len(inst_fields)))
    data.extend(uleb128(len(direct_m)))
    data.extend(uleb128(len(virt_m)))

    for group in (static_fields, inst_fields):
        prev = 0
        for idx, fl in group:
            data.extend(uleb128(idx - prev))
            data.extend(uleb128(fl))
            prev = idx
    for group in (direct_m, virt_m):
        prev = 0
        for idx, fl, coff in group:
            data.extend(uleb128(idx - prev))
            data.extend(uleb128(fl))
            data.extend(uleb128(coff))
            prev = idx
    map_entries.append((0x2000, 1, class_data_off))

    # Map list (4-byte aligned)
    align4()
    map_off = data_off + len(data)
    full_map: list[tuple[int, int, int]] = [
        (0x0000, 1, 0),
        (0x0001, len(pool._sorted_strings), str_ids_off),
        (0x0002, len(pool._sorted_types), type_ids_off),
        (0x0003, len(pool._sorted_protos), proto_ids_off),
        (0x0004, len(pool._sorted_fields), field_ids_off),
        (0x0005, len(pool._sorted_methods), method_ids_off),
        (0x0006, 1, class_defs_off),
        *map_entries,
        (0x1000, 1, map_off),
    ]
    full_map.sort(key=lambda x: x[2])
    data.extend(struct.pack("<I", len(full_map)))
    for mtype, mcnt, moff in full_map:
        data.extend(struct.pack("<HHII", mtype, 0, mcnt, moff))

    data_size = len(data)
    file_size = data_off + data_size

    # Assemble header + IDs + class_def
    buf = bytearray()
    buf.extend(b"dex\n035\x00")
    buf.extend(b"\x00" * 4)  # checksum placeholder
    buf.extend(b"\x00" * 20)  # signature placeholder
    buf.extend(struct.pack(
        "<IIIIIIIIIIIIIIIIIIII",
        file_size,
        header_size,
        0x12345678,
        0, 0,  # link
        map_off,
        len(pool._sorted_strings), str_ids_off,
        len(pool._sorted_types), type_ids_off,
        len(pool._sorted_protos), proto_ids_off,
        len(pool._sorted_fields), field_ids_off,
        len(pool._sorted_methods), method_ids_off,
        1, class_defs_off,
        data_size, data_off,
    ))
    assert len(buf) == header_size

    for off in str_data_offsets:
        buf.extend(struct.pack("<I", off))
    for t in pool._sorted_types:
        buf.extend(struct.pack("<I", pool.str_idx(t)))
    for ret, params in pool._sorted_protos:
        shorty_idx = pool.str_idx(DexBuilder._shorty(ret, list(params)))
        ret_idx = pool.type_idx(ret)
        par_off = type_list_offsets[params] if params else 0
        buf.extend(struct.pack("<III", shorty_idx, ret_idx, par_off))
    for cls, name, typ in pool._sorted_fields:
        buf.extend(struct.pack("<HHI", pool.type_idx(cls), pool.type_idx(typ), pool.str_idx(name)))
    for cls, name, ret, params in pool._sorted_methods:
        buf.extend(struct.pack("<HHI", pool.type_idx(cls), pool.proto_idx(ret, list(params)), pool.str_idx(name)))

    # 1 class_def
    iface_off = type_list_offsets[tuple(ifaces)] if ifaces else 0
    buf.extend(struct.pack(
        "<IIIIIIII",
        pool.type_idx(main_cls),
        0x0001,  # ACC_PUBLIC
        pool.type_idx(super_cls),
        iface_off,
        0xFFFFFFFF,  # NO_INDEX source_file
        0,  # annotations
        class_data_off,
        0,  # static_values
    ))
    buf.extend(data)
    assert len(buf) == file_size

    # SHA-1 signature over bytes[32:]
    sig = hashlib.sha1(buf[32:]).digest()
    buf[12:32] = sig
    # Adler-32 checksum over bytes[12:]
    csum = zlib.adler32(buf[12:]) & 0xFFFFFFFF
    buf[8:12] = struct.pack("<I", csum)
    return bytes(buf)


def build_input_daemon_dex() -> bytes:
    CLS = "Lcom/agentdroid/InputDaemon;"
    OBJ = "Ljava/lang/Object;"
    STR = "Ljava/lang/String;"
    SOCK = "Ljava/net/Socket;"
    SSOCK = "Ljava/net/ServerSocket;"
    INET = "Ljava/net/InetAddress;"
    IM = "Landroid/hardware/input/InputManager;"
    ME = "Landroid/view/MotionEvent;"
    KE = "Landroid/view/KeyEvent;"
    IE = "Landroid/view/InputEvent;"
    KCM = "Landroid/view/KeyCharacterMap;"
    THRD = "Ljava/lang/Thread;"
    RUN = "Ljava/lang/Runnable;"
    BR = "Ljava/io/BufferedReader;"
    ISR = "Ljava/io/InputStreamReader;"
    FR = "Ljava/io/FileReader;"
    IS = "Ljava/io/InputStream;"
    OS = "Ljava/io/OutputStream;"
    SYS = "Ljava/lang/System;"
    PS = "Ljava/io/PrintStream;"

    # Instance field: sock (Socket)
    # Static fields: sToken (String), sInputManager (InputManager)
    fields = [
        ("sToken", STR, 0x000A),        # private static
        ("sInputManager", IM, 0x000A),  # private static
        ("sock", SOCK, 0x0012),         # private final
    ]

    # 1. <init>(Socket s)
    def emit_init(a: Asm) -> None:
        # regs=2, ins=2 (v0=this, v1=s), outs=1
        a.invoke_direct([0], OBJ, "<init>", "V", [])
        a.iput_obj(1, 0, CLS, "sock", SOCK)
        a.ret_void()

    # 2. run() -> calls handleClient(this.sock)
    def emit_run(a: Asm) -> None:
        # regs=2, ins=1 (v1=this), outs=1
        a.iget_obj(0, 1, CLS, "sock", SOCK)
        a.invoke_static([0], CLS, "handleClient", "V", [SOCK])
        a.ret_void()

    # 3. injectMotion(int action, long downTime, long eventTime, float x, float y, float pressure)
    def emit_inject_motion(a: Asm) -> None:
        # ins=8:
        # v16=action, v17:18=downTime, v19:20=eventTime, v21=x, v22=y, v23=pressure
        # local v0..v15 for obtain(JJIFFFFIFFII)
        # regs=24, ins=8, outs=14
        a.move_wide16(0, 17)         # v0:1 = downTime
        a.move_wide16(2, 19)         # v2:3 = eventTime
        a.move16(4, 16)              # v4 = action
        a.move16(5, 21)              # v5 = x
        a.move16(6, 22)              # v6 = y
        a.move16(7, 23)              # v7 = pressure
        a.const_float(8, 1.0)        # v8 = size = 1.0f
        a.const4(9, 0)               # v9 = metaState = 0
        a.const_float(10, 1.0)       # v10 = xPrecision = 1.0f
        a.const_float(11, 1.0)       # v11 = yPrecision = 1.0f
        a.const4(12, 0)              # v12 = deviceId = 0
        a.const4(13, 0)              # v13 = edgeFlags = 0
        a.invoke_static_range(
            0, 14, ME, "obtain", ME,
            ["J", "J", "I", "F", "F", "F", "F", "I", "F", "F", "I", "I"],
        )
        a.move_res_obj(0)            # v0 = MotionEvent
        a.const16(1, 4098)           # SOURCE_TOUCHSCREEN = 0x1002
        a.invoke_virtual([0, 1], ME, "setSource", "V", ["I"])
        a.sget_obj(1, CLS, "sInputManager", IM)
        a.const4(2, 2)               # INJECT_INPUT_EVENT_MODE_WAIT_FOR_FINISH = 2
        a.invoke_virtual([1, 0, 2], IM, "injectInputEvent", "Z", [IE, "I"])
        a.invoke_virtual([0], ME, "recycle", "V", [])
        a.ret_void()

    # 4. tap(float x, float y)
    def emit_tap(a: Asm) -> None:
        # regs=12, ins=2 (v10=x, v11=y), outs=8
        # Need contiguous v0..v7 for injectMotion(I, J, J, F, F, F)
        a.invoke_static([], "Landroid/os/SystemClock;", "uptimeMillis", "J", [])
        a.move_res_wide(8)           # v8:9 = now
        # DOWN
        a.const4(0, 0)               # action = ACTION_DOWN (0)
        a.move_wide(1, 8)            # downTime
        a.move_wide(3, 8)            # eventTime
        a.move(5, 10)                # x
        a.move(6, 11)                # y
        a.const_float(7, 1.0)        # pressure = 1.0f
        a.invoke_static_range(0, 8, CLS, "injectMotion", "V", ["I", "J", "J", "F", "F", "F"])
        # UP
        a.const4(0, 1)               # action = ACTION_UP (1)
        a.move_wide(1, 8)
        a.move_wide(3, 8)
        a.move(5, 10)
        a.move(6, 11)
        a.const_float(7, 0.0)        # pressure = 0.0f
        a.invoke_static_range(0, 8, CLS, "injectMotion", "V", ["I", "J", "J", "F", "F", "F"])
        a.ret_void()

    # 5. swipe(float x1, float y1, float x2, float y2, int durMs)
    def emit_swipe(a: Asm) -> None:
        # ins=5: v20=x1, v21=y1, v22=x2, v23=y2, v24=durMs, regs=25, outs=8
        a.const4(0, 1)
        a.move16(1, 24)
        a.if_ge(1, 0, "dur_ok")
        a.const16(24, 1)
        a.label("dur_ok")
        a.invoke_static([], "Landroid/os/SystemClock;", "uptimeMillis", "J", [])
        a.move_res_wide(8)           # v8:9 = down
        a.const4(0, 0)               # ACTION_DOWN
        a.move_wide(1, 8)
        a.move_wide(3, 8)
        a.move16(5, 20)
        a.move16(6, 21)
        a.const_float(7, 1.0)
        a.invoke_static_range(0, 8, CLS, "injectMotion", "V", ["I", "J", "J", "F", "F", "F"])

        a.move16(0, 24)
        a.int_to_long(14, 0)
        a.add_long(10, 8, 14)        # v10:11 = end
        a.int_to_float(1, 0)
        a.move16(19, 1)              # v19 = (float) durMs

        a.label("loop")
        a.invoke_static([], "Landroid/os/SystemClock;", "uptimeMillis", "J", [])
        a.move_res_wide(12)          # v12:13 = now
        a.cmp_long(0, 12, 10)
        a.if_gez(0, "loop_done")

        a.sub_long(14, 12, 8)
        a.long_to_float(1, 14)
        a.move16(16, 1)
        a.div_float(16, 16, 19)
        a.move16(17, 22)
        a.move16(0, 20)
        a.sub_float(17, 17, 0)
        a.mul_float(17, 17, 16)
        a.add_float(17, 17, 0)
        a.move16(18, 23)
        a.move16(0, 21)
        a.sub_float(18, 18, 0)
        a.mul_float(18, 18, 16)
        a.add_float(18, 18, 0)

        a.const4(0, 2)               # ACTION_MOVE
        a.move_wide(1, 8)
        a.move_wide(3, 12)
        a.move16(5, 17)
        a.move16(6, 18)
        a.const_float(7, 1.0)
        a.invoke_static_range(0, 8, CLS, "injectMotion", "V", ["I", "J", "J", "F", "F", "F"])

        a.invoke_static([], "Landroid/os/SystemClock;", "uptimeMillis", "J", [])
        a.move_res_wide(12)
        a.sub_long(14, 10, 12)
        a.const_wide16(0, 0)
        a.cmp_long(2, 14, 0)
        a.if_lez(2, "loop_done")
        a.const_wide16(0, 8)
        a.cmp_long(2, 14, 0)
        a.if_ltz(2, "sleep_rem")
        a.move_wide(14, 0)
        a.label("sleep_rem")
        a.invoke_static([14, 15], "Ljava/lang/Thread;", "sleep", "V", ["J"])
        a.goto("loop")

        a.label("loop_done")
        a.invoke_static([], "Landroid/os/SystemClock;", "uptimeMillis", "J", [])
        a.move_res_wide(12)
        a.const4(0, 1)               # ACTION_UP
        a.move_wide(1, 8)
        a.move_wide(3, 12)
        a.move16(5, 22)
        a.move16(6, 23)
        a.const_float(7, 0.0)
        a.invoke_static_range(0, 8, CLS, "injectMotion", "V", ["I", "J", "J", "F", "F", "F"])
        a.ret_void()

    # 6. sendKey(String keyName)
    def emit_send_key(a: Asm) -> None:
        # ins=1 (v18=keyName), regs=19, outs=13
        # v0..v12 for KeyEvent.<init>(JJIIIIIIII), v13=im, v14=mode, v15=code, v16:17=now
        a.move_obj(0, 18)
        a.invoke_static([0], KE, "keyCodeFromString", "I", [STR])
        a.move_res(15)
        a.invoke_static([], "Landroid/os/SystemClock;", "uptimeMillis", "J", [])
        a.move_res_wide(16)
        a.sget_obj(13, CLS, "sInputManager", IM)
        a.const4(14, 2)

        # DOWN
        a.new_inst(0, KE)
        a.move_wide16(1, 16)
        a.move_wide16(3, 16)
        a.const4(5, 0)               # ACTION_DOWN
        a.move16(6, 15)              # code
        a.const4(7, 0)               # repeat
        a.const4(8, 0)               # metaState
        a.const4(9, -1)              # deviceId
        a.const4(10, 0)              # scancode
        a.const4(11, 0)              # flags
        a.const16(12, 257)           # SOURCE_KEYBOARD = 0x101
        a.invoke_direct_range(0, 13, KE, "<init>", "V", ["J", "J", "I", "I", "I", "I", "I", "I", "I", "I"])
        a.invoke_virtual([13, 0, 14], IM, "injectInputEvent", "Z", [IE, "I"])

        # UP
        a.new_inst(0, KE)
        a.move_wide16(1, 16)
        a.move_wide16(3, 16)
        a.const4(5, 1)               # ACTION_UP
        a.move16(6, 15)
        a.const4(7, 0)
        a.const4(8, 0)
        a.const4(9, -1)
        a.const4(10, 0)
        a.const4(11, 0)
        a.const16(12, 257)
        a.invoke_direct_range(0, 13, KE, "<init>", "V", ["J", "J", "I", "I", "I", "I", "I", "I", "I", "I"])
        a.invoke_virtual([13, 0, 14], IM, "injectInputEvent", "Z", [IE, "I"])
        a.ret_void()

    # 7. sendTextB64(String b64) -> boolean
    def emit_send_text_b64(a: Asm) -> None:
        # ins=1 (v8=b64), regs=9, outs=3
        a.const4(0, 0)
        a.invoke_static([8, 0], "Landroid/util/Base64;", "decode", "[B", [STR, "I"])
        a.move_res_obj(0)
        a.new_inst(1, STR)
        a.const_str(2, "UTF-8")
        a.invoke_direct([1, 0, 2], STR, "<init>", "V", ["[B", STR])
        a.invoke_virtual([1], STR, "toCharArray", "[C", [])
        a.move_res_obj(0)            # v0 = char[]
        a.const4(1, -1)
        a.invoke_static([1], KCM, "load", KCM, ["I"])
        a.move_res_obj(1)            # v1 = kcm
        a.invoke_virtual([1, 0], KCM, "getEvents", f"[{KE}", ["[C"])
        a.move_res_obj(0)            # v0 = KeyEvent[]
        a.if_nez(0, "has_events")
        a.const4(0, 0)
        a.ret(0)

        a.label("has_events")
        a.array_len(1, 0)            # v1 = len
        a.const4(2, 0)               # v2 = i
        a.sget_obj(3, CLS, "sInputManager", IM)
        a.const4(4, 2)               # mode = 2
        a.const16(5, 4098)           # SOURCE_TOUCHSCREEN
        a.label("ev_loop")
        a.if_ge(2, 1, "ev_done")
        a.aget_obj(6, 0, 2)
        a.invoke_virtual([6, 5], KE, "setSource", "V", ["I"])
        a.invoke_virtual([3, 6, 4], IM, "injectInputEvent", "Z", [IE, "I"])
        a.add_int_lit8(2, 2, 1)
        a.goto("ev_loop")
        a.label("ev_done")
        a.const4(0, 1)
        a.ret(0)

    # 8. handleClient(Socket sock)
    def emit_handle_client(a: Asm) -> None:
        # ins=1 (v15=sock), regs=16, outs=6
        # v14=br, v13=os, v12=line, v11=parts, v10=cmd
        a.label("try_setup_start")
        a.const4(0, 1)
        a.invoke_virtual([15, 0], SOCK, "setTcpNoDelay", "V", ["Z"])
        a.invoke_virtual([15], SOCK, "getInputStream", IS, [])
        a.move_res_obj(0)
        a.new_inst(1, ISR)
        a.const_str(2, "UTF-8")
        a.invoke_direct([1, 0, 2], ISR, "<init>", "V", [IS, STR])
        a.new_inst(14, BR)
        a.invoke_direct([14, 1], BR, "<init>", "V", ["Ljava/io/Reader;"])
        a.invoke_virtual([15], SOCK, "getOutputStream", OS, [])
        a.move_res_obj(13)

        a.label("read_loop")
        a.invoke_virtual([14], BR, "readLine", STR, [])
        a.move_res_obj(12)
        a.label("try_setup_end")
        a.if_eqz(12, "close_sock")

        a.label("try_cmd_start")
        a.const_str(0, "\t")
        a.const4(1, -1)
        a.invoke_virtual([12, 0, 1], STR, "split", f"[{STR}", [STR, "I"])
        a.move_res_obj(11)           # v11 = parts
        a.array_len(0, 11)
        a.const4(1, 2)
        a.if_lt(0, 1, "auth_fail")
        a.sget_obj(0, CLS, "sToken", STR)
        a.const4(1, 0)
        a.aget_obj(1, 11, 1)
        a.invoke_virtual([0, 1], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_nez(0, "auth_ok")

        a.label("auth_fail")
        a.const_str(0, "ERR auth\n")
        a.goto("write_str")

        a.label("auth_ok")
        a.const4(0, 1)
        a.aget_obj(10, 11, 0)        # v10 = cmd

        # ping
        a.const_str(0, "ping")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "not_ping")
        a.const_str(0, "OK pong\n")
        a.goto("write_str")

        a.label("not_ping")
        a.const_str(0, "tap")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "not_tap")
        a.const4(0, 2)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(1)
        a.const4(0, 3)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(2)
        a.invoke_static([1, 2], CLS, "tap", "V", ["F", "F"])
        a.goto("write_ok")

        a.label("not_tap")
        a.const_str(0, "swipe")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "not_swipe")
        a.const4(0, 2)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(1)
        a.const4(0, 3)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(2)
        a.const4(0, 4)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(3)
        a.const4(0, 5)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(4)
        a.const4(0, 6)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Integer;", "parseInt", "I", [STR])
        a.move_res(5)
        a.invoke_static([1, 2, 3, 4, 5], CLS, "swipe", "V", ["F", "F", "F", "F", "I"])
        a.goto("write_ok")

        a.label("not_swipe")
        a.const_str(0, "long_press")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "not_lp")
        a.const4(0, 2)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(1)
        a.const4(0, 3)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Float;", "parseFloat", "F", [STR])
        a.move_res(2)
        a.const4(0, 4)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], "Ljava/lang/Integer;", "parseInt", "I", [STR])
        a.move_res(5)
        a.invoke_static([1, 2, 1, 2, 5], CLS, "swipe", "V", ["F", "F", "F", "F", "I"])
        a.goto("write_ok")

        a.label("not_lp")
        a.const_str(0, "key")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "not_key")
        a.const4(0, 2)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], CLS, "sendKey", "V", [STR])
        a.goto("write_ok")

        a.label("not_key")
        a.const_str(0, "text_b64")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "unknown_cmd")
        a.const4(0, 2)
        a.aget_obj(0, 11, 0)
        a.invoke_static([0], CLS, "sendTextB64", "Z", [STR])
        a.move_res(0)
        a.if_eqz(0, "text_fail")
        a.goto("write_ok")
        a.label("text_fail")
        a.const_str(0, "ERR unsupported_chars\n")
        a.goto("write_str")

        a.label("unknown_cmd")
        a.const_str(0, "ERR unknown_cmd\n")
        a.goto("write_str")

        a.label("write_ok")
        a.const_str(0, "OK\n")
        a.label("write_str")
        a.const_str(1, "UTF-8")
        a.invoke_virtual([0, 1], STR, "getBytes", "[B", [STR])
        a.move_res_obj(0)
        a.invoke_virtual([13, 0], OS, "write", "V", ["[B"])
        a.invoke_virtual([13], OS, "flush", "V", [])
        a.label("try_cmd_end")
        a.goto("read_loop")

        a.label("catch_cmd")
        a.move_exc(0)
        a.new_inst(1, "Ljava/lang/StringBuilder;")
        a.invoke_direct([1], "Ljava/lang/StringBuilder;", "<init>", "V", [])
        a.const_str(2, "ERR ")
        a.invoke_virtual([1, 2], "Ljava/lang/StringBuilder;", "append", "Ljava/lang/StringBuilder;", [STR])
        a.invoke_virtual([0], "Ljava/lang/Throwable;", "toString", STR, [])
        a.move_res_obj(0)
        a.invoke_virtual([1, 0], "Ljava/lang/StringBuilder;", "append", "Ljava/lang/StringBuilder;", [STR])
        a.const_str(2, "\n")
        a.invoke_virtual([1, 2], "Ljava/lang/StringBuilder;", "append", "Ljava/lang/StringBuilder;", [STR])
        a.invoke_virtual([1], "Ljava/lang/StringBuilder;", "toString", STR, [])
        a.move_res_obj(0)
        a.label("try_err_write_start")
        a.const_str(1, "UTF-8")
        a.invoke_virtual([0, 1], STR, "getBytes", "[B", [STR])
        a.move_res_obj(0)
        a.invoke_virtual([13, 0], OS, "write", "V", ["[B"])
        a.invoke_virtual([13], OS, "flush", "V", [])
        a.label("try_err_write_end")
        a.goto("read_loop")

        a.label("catch_outer")
        a.move_exc(0)
        a.label("close_sock")
        a.label("try_close_start")
        a.invoke_virtual([15], SOCK, "close", "V", [])
        a.label("try_close_end")
        a.ret_void()
        a.label("catch_close")
        a.move_exc(0)
        a.ret_void()

        # Strictly disjoint and sorted try/catch blocks
        a.try_catch("try_setup_start", "try_setup_end", [(None, "catch_outer")])
        a.try_catch("try_cmd_start", "try_cmd_end", [(None, "catch_cmd")])
        a.try_catch("try_err_write_start", "try_err_write_end", [(None, "catch_outer")])
        a.try_catch("try_close_start", "try_close_end", [(None, "catch_close")])

    # 9. main(String[] args)
    def emit_main(a: Asm) -> None:
        # ins=1 (v6=args), regs=7, outs=4
        # v0=port, v1=tokenPath, v2=br/ss, v3=sock, v4=thread/addr, v5=tmp
        a.const4(5, 0)
        a.aget_obj(0, 6, 5)
        a.invoke_static([0], "Ljava/lang/Integer;", "parseInt", "I", [STR])
        a.move_res(0)                # v0 = port

        a.const4(5, 1)
        a.aget_obj(1, 6, 5)          # v1 = tokenPath

        # Read token line
        a.new_inst(2, FR)
        a.invoke_direct([2, 1], FR, "<init>", "V", [STR])
        a.new_inst(3, BR)
        a.invoke_direct([3, 2], BR, "<init>", "V", ["Ljava/io/Reader;"])
        a.invoke_virtual([3], BR, "readLine", STR, [])
        a.move_res_obj(4)
        a.invoke_virtual([3], BR, "close", "V", [])
        a.invoke_virtual([4], STR, "trim", STR, [])
        a.move_res_obj(4)
        a.sput_obj(4, CLS, "sToken", STR)

        # InputManager.getInstance()
        a.invoke_static([], IM, "getInstance", IM, [])
        a.move_res_obj(4)
        a.sput_obj(4, CLS, "sInputManager", IM)

        # ServerSocket(port, 50, InetAddress.getByName("127.0.0.1"))
        a.const_str(4, "127.0.0.1")
        a.invoke_static([4], INET, "getByName", INET, [STR])
        a.move_res_obj(4)
        a.new_inst(2, SSOCK)
        a.const16(5, 50)
        a.invoke_direct([2, 0, 5, 4], SSOCK, "<init>", "V", ["I", "I", INET])

        # System.out.println("READY")
        a.sget_obj(4, SYS, "out", PS)
        a.const_str(5, "READY")
        a.invoke_virtual([4, 5], PS, "println", "V", [STR])

        # Accept loop
        a.label("accept_loop")
        a.invoke_virtual([2], SSOCK, "accept", SOCK, [])
        a.move_res_obj(3)
        a.new_inst(4, CLS)
        a.invoke_direct([4, 3], CLS, "<init>", "V", [SOCK])
        a.new_inst(5, THRD)
        a.invoke_direct([5, 4], THRD, "<init>", "V", [RUN])
        a.invoke_virtual([5], THRD, "start", "V", [])
        a.goto("accept_loop")

    methods = [
        MethodDef(CLS, "<init>", "V", [SOCK], 0x10002, 2, 2, 1, False, emit_init),
        MethodDef(CLS, "handleClient", "V", [SOCK], 0x000A, 16, 1, 6, False, emit_handle_client),
        MethodDef(CLS, "injectMotion", "V", ["I", "J", "J", "F", "F", "F"], 0x000A, 24, 8, 14, False, emit_inject_motion),
        MethodDef(CLS, "main", "V", [f"[{STR}"], 0x0009, 7, 1, 4, False, emit_main),
        MethodDef(CLS, "sendKey", "V", [STR], 0x000A, 19, 1, 13, False, emit_send_key),
        MethodDef(CLS, "sendTextB64", "Z", [STR], 0x000A, 9, 1, 3, False, emit_send_text_b64),
        MethodDef(CLS, "swipe", "V", ["F", "F", "F", "F", "I"], 0x000A, 25, 5, 8, False, emit_swipe),
        MethodDef(CLS, "tap", "V", ["F", "F"], 0x000A, 12, 2, 8, False, emit_tap),
        MethodDef(CLS, "run", "V", [], 0x0001, 2, 1, 1, True, emit_run),
    ]

    return compile_dex(CLS, OBJ, [RUN], fields, methods)


def main() -> None:
    dex_bytes = build_input_daemon_dex()
    OUT_DEX.parent.mkdir(parents=True, exist_ok=True)
    OUT_DEX.write_bytes(dex_bytes)
    print(f"Wrote {OUT_DEX} ({len(dex_bytes)} bytes)")


if __name__ == "__main__":
    main()
