#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# -----------------------------
# Common helpers
# -----------------------------

def parse_int(value: str) -> int:
    s = value.strip().replace("_", "")
    if s.startswith("$"):
        return int(s[1:], 16)
    if s.lower().startswith("0x"):
        return int(s, 16)
    if s.startswith("%"):
        return int(s[1:], 2)
    if s.lower().startswith("0b"):
        return int(s, 2)
    if s.startswith("&"):
        return int(s[1:], 8)
    return int(s, 10)


def fmt_hex(value: int, width: int | None = None) -> str:
    value &= 0xFFFFFFFF
    if width is None:
        width = 2 if value <= 0xFF else 4
    return f"${value:0{width}X}"


def fmt_bin8(value: int) -> str:
    return f"%{value & 0xFF:08b}"


def signed8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def is_num(s: str) -> bool:
    return bool(re.fullmatch(r"\$[0-9a-fA-F]+|0x[0-9a-fA-F]+|%[01]+|0b[01]+|&[0-7]+|\d+", s.strip()))


def canonical(text: str) -> str:
    s = text.lower().strip().replace("(", "[").replace(")", "]")
    s = re.sub(r"\s+", "", s)
    s = s.replace("[hli]", "[hl+]").replace("[hld]", "[hl-]")
    if s.startswith("ldi"):
        rest = s[3:]
        if rest in {"a,[hl]", "[hl],a"}:
            rest = rest.replace("[hl]", "[hl+]")
        s = "ld" + rest
    if s.startswith("ldd"):
        rest = s[3:]
        if rest in {"a,[hl]", "[hl],a"}:
            rest = rest.replace("[hl]", "[hl-]")
        s = "ld" + rest
    return s


def is_label(line: str) -> bool:
    raw = line.strip()
    if raw.endswith(":") or raw.endswith("::"):
        return True
    if re.fullmatch(r"\.?[A-Za-z_][\w.$]*", raw):
        return not re.match(r"(?i)^(ld|ldh|jr|jp|ret|call|and|or|xor|cp|bit|inc|dec|push|pop|rst)\b", raw)
    return False


# -----------------------------
# Game Boy maps
# -----------------------------

IO_REGISTERS = {
    0xFF00: ("P1/JOYP", "Joypad input"),
    0xFF01: ("SB", "Serial transfer data"),
    0xFF02: ("SC", "Serial transfer control"),
    0xFF04: ("DIV", "Divider register"),
    0xFF05: ("TIMA", "Timer counter"),
    0xFF06: ("TMA", "Timer modulo"),
    0xFF07: ("TAC", "Timer control"),
    0xFF0F: ("IF", "Interrupt flags"),
    0xFF40: ("LCDC", "LCD control"),
    0xFF41: ("STAT", "LCD status"),
    0xFF42: ("SCY", "Viewport Y scroll"),
    0xFF43: ("SCX", "Viewport X scroll"),
    0xFF44: ("LY", "LCD Y coordinate"),
    0xFF45: ("LYC", "LY compare"),
    0xFF46: ("DMA", "OAM DMA source high byte"),
    0xFF47: ("BGP", "DMG background palette"),
    0xFF48: ("OBP0", "DMG object palette 0"),
    0xFF49: ("OBP1", "DMG object palette 1"),
    0xFF4A: ("WY", "Window Y position"),
    0xFF4B: ("WX", "Window X position plus 7"),
    0xFFFF: ("IE", "Interrupt enable"),
}

LCDC_BITS = {
    7: "LCD/window display enable",
    6: "Window tile map area select",
    5: "Window enable",
    4: "BG/window tile data area select",
    3: "BG tile map area select",
    2: "OBJ size",
    1: "OBJ enable",
    0: "BG/window enable / BG priority depending on model",
}
STAT_BITS = {
    6: "LYC=LY STAT interrupt enable",
    5: "Mode 2 OAM STAT interrupt enable",
    4: "Mode 1 VBlank STAT interrupt enable",
    3: "Mode 0 HBlank STAT interrupt enable",
    2: "LYC=LY flag",
    1: "PPU mode bit 1",
    0: "PPU mode bit 0",
}
SC_BITS = {
    7: "Transfer enable/start",
    1: "CGB fast clock speed",
    0: "Clock select: 0=external/slave, 1=internal/master",
}
INT_BITS = {4: "Joypad", 3: "Serial", 2: "Timer", 1: "LCD STAT", 0: "VBlank"}


def classify_addr(addr: int) -> tuple[str, str]:
    if 0x0000 <= addr <= 0x3FFF: return "ROM0", "Fixed ROM bank 0"
    if 0x4000 <= addr <= 0x7FFF: return "ROMX", "Switchable ROM bank area"
    if 0x8000 <= addr <= 0x9FFF: return "VRAM", "Video RAM"
    if 0xA000 <= addr <= 0xBFFF: return "SRAM", "External cartridge RAM / mapper area"
    if 0xC000 <= addr <= 0xCFFF: return "WRAM0", "Work RAM bank 0"
    if 0xD000 <= addr <= 0xDFFF: return "WRAMX", "Switchable WRAM on CGB; WRAM on DMG"
    if 0xE000 <= addr <= 0xFDFF: return "ECHO", "Echo of C000-DDFF; usually avoided"
    if 0xFE00 <= addr <= 0xFE9F: return "OAM", "Object Attribute Memory"
    if 0xFEA0 <= addr <= 0xFEFF: return "UNUSABLE", "Unusable/prohibited memory area"
    if 0xFF00 <= addr <= 0xFF7F: return "IO", "Hardware I/O registers"
    if 0xFF80 <= addr <= 0xFFFE: return "HRAM", "High RAM"
    if addr == 0xFFFF: return "IE", "Interrupt Enable register"
    return "OUT_OF_RANGE", "Not a 16-bit Game Boy address"


def print_addr(addr: int) -> None:
    addr &= 0xFFFF
    region, desc = classify_addr(addr)
    print(f"address: {fmt_hex(addr,4)}")
    print(f"region:  {region}")
    print(f"meaning: {desc}")
    if addr in IO_REGISTERS:
        name, desc = IO_REGISTERS[addr]
        print(f"io:      {name} - {desc}")


def ldh_addr(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    if is_num(raw):
        off = parse_int(raw)
        if not 0 <= off <= 0xFF:
            raise SystemExit("LDH immediate offset must be 00-FF")
        addr = 0xFF00 + off
        suffix = ""
        if addr in IO_REGISTERS:
            name, desc = IO_REGISTERS[addr]
            suffix = f" ({name} - {desc})"
        return fmt_hex(addr, 4), f"offset {fmt_hex(off,2)} -> {fmt_hex(addr,4)}{suffix}"
    return f"[{raw}]", "symbolic high-memory target; resolve symbol/constant for exact address"


# -----------------------------
# Commands: num / addr / range / hw
# -----------------------------

def cmd_num(args: argparse.Namespace) -> int:
    value = parse_int(args.value)
    print(f"input:      {args.value}")
    print(f"decimal:    {value}")
    print(f"hex8:       {fmt_hex(value & 0xFF,2)}")
    print(f"hex16:      {fmt_hex(value & 0xFFFF,4)}")
    print(f"binary8:    {fmt_bin8(value)}")
    print(f"unsigned8:  {value & 0xFF}")
    print(f"signed8:    {signed8(value)}")
    print(f"unsigned16: {value & 0xFFFF}")
    print(f"signed16:   {signed16(value)}")
    if args.bits:
        print("bits:")
        for bit in range(7, -1, -1):
            print(f"  bit {bit}: {(value >> bit) & 1}")
    if args.test_bit is not None:
        bit = args.test_bit
        if not 0 <= bit <= 15:
            raise SystemExit("--test-bit must be 0-15")
        print(f"test_bit_{bit}: {(value >> bit) & 1}")
    if args.mask is not None:
        mask = parse_int(args.mask)
        print(f"mask:       {fmt_hex(mask & 0xFFFF,4)}")
        print(f"value&mask: {fmt_hex(value & mask,4)}")
        print(f"mask_set:   {bool(value & mask)}")
    return 0


def cmd_addr(args: argparse.Namespace) -> int:
    if args.ldh is not None:
        off = parse_int(args.ldh)
        if not 0 <= off <= 0xFF:
            raise SystemExit("LDH offset must be 00-FF")
        print(f"ldh_offset: {fmt_hex(off,2)}")
        print_addr(0xFF00 + off)
        return 0

    if args.offset is not None:
        off = parse_int(args.offset)
        if off < 0x4000:
            bank, addr = 0, off
        else:
            bank, addr = off // 0x4000, 0x4000 + (off % 0x4000)
        print(f"rom_offset: {fmt_hex(off,6)}")
        print(f"bank:       {bank} ({fmt_hex(bank,2)})")
        print(f"address:    {fmt_hex(addr,4)}")
        return 0

    if args.bank is not None and args.addr is not None:
        bank = parse_int(args.bank)
        addr = parse_int(args.addr)
        if bank == 0:
            if not 0x0000 <= addr <= 0x3FFF:
                raise SystemExit("Bank 0 address must be 0000-3FFF")
            off = addr
        else:
            if not 0x4000 <= addr <= 0x7FFF:
                raise SystemExit("Switchable ROM bank address must be 4000-7FFF")
            off = bank * 0x4000 + (addr - 0x4000)
        print(f"bank:       {bank} ({fmt_hex(bank,2)})")
        print(f"address:    {fmt_hex(addr,4)}")
        print(f"rom_offset: {fmt_hex(off,6)}")
        return 0

    if args.address is None:
        raise SystemExit("Provide address, --ldh, --offset, or --bank + --addr")
    print_addr(parse_int(args.address))
    return 0


def segments(lo: int, hi: int):
    cur = lo
    while cur <= hi:
        r, d = classify_addr(cur)
        end = cur
        while end + 1 <= hi and classify_addr(end + 1)[0] == r:
            end += 1
        yield cur, end, r, d, end - cur + 1
        cur = end + 1


def cmd_range(args: argparse.Namespace) -> int:
    start = parse_int(args.start) & 0xFFFF
    count = parse_int(args.writes) if isinstance(args.writes, str) else args.writes
    if count <= 0: raise SystemExit("--writes must be greater than 0")
    if args.step == 0: raise SystemExit("--step cannot be 0")
    step = args.step

    if args.pre:
        first, last = (start + step) & 0xFFFF, (start + step * count) & 0xFFFF
        final, raw_last, mode = last, start + step * count, "pre-update"
    else:
        first, last = start, (start + step * (count - 1)) & 0xFFFF
        final, raw_last, mode = (start + step * count) & 0xFFFF, start + step * (count - 1), "post-update"

    print(f"start_register: {fmt_hex(start,4)}")
    print(f"accesses:       {count}")
    print(f"step:           {step:+d}")
    print(f"access_mode:    {mode}")
    print(f"first_access:   {fmt_hex(first,4)}")
    print(f"last_access:    {fmt_hex(last,4)}")
    print(f"final_register: {fmt_hex(final,4)}")
    if raw_last < 0 or raw_last > 0xFFFF:
        print("wraparound:     yes")
        print("regions_touched: not segmented; inspect manually")
        return 0
    lo, hi = min(first, last), max(first, last)
    print("wraparound:     no")
    print(f"inclusive_span: {fmt_hex(lo,4)}-{fmt_hex(hi,4)}")
    print(f"span_bytes:     {hi - lo + 1}")
    print("regions_touched:")
    for s, e, r, d, n in segments(lo, hi):
        print(f"- {fmt_hex(s,4)}-{fmt_hex(e,4)}: {r} ({n} bytes) - {d}")
    return 0


def print_bits(value: int, labels: dict[int, str]) -> None:
    print(f"value: {fmt_hex(value,2)} {fmt_bin8(value)}")
    for bit in range(7, -1, -1):
        label = labels.get(bit, "")
        suffix = f" - {label}" if label else ""
        print(f"bit {bit}: {(value >> bit) & 1}{suffix}")


def decode_palette(value: int, name: str) -> None:
    print(f"decode: {name} DMG palette")
    print(f"value:  {fmt_hex(value,2)} {fmt_bin8(value)}")
    print("shade: 0=lightest, 3=darkest")
    for color in range(4):
        shade = (value >> (color * 2)) & 0b11
        extra = " (OBJ color 0 transparent)" if name in {"OBP0", "OBP1"} and color == 0 else ""
        print(f"color {color} -> shade {shade}{extra}")


def cmd_hw(args: argparse.Namespace) -> int:
    addr = parse_int(args.address) & 0xFFFF
    print_addr(addr)
    if args.value is None:
        return 0
    value = parse_int(args.value) & 0xFF
    print()
    if addr == 0xFF40:
        print("decode: LCDC"); print_bits(value, LCDC_BITS)
    elif addr == 0xFF41:
        print("decode: STAT"); print_bits(value, STAT_BITS); print(f"ppu_mode: {value & 3}")
    elif addr == 0xFF02:
        print("decode: SC serial control"); print_bits(value, SC_BITS)
    elif addr in (0xFF47, 0xFF48, 0xFF49):
        decode_palette(value, IO_REGISTERS[addr][0])
    elif addr in (0xFF0F, 0xFFFF):
        print("decode: interrupt bits"); print_bits(value, INT_BITS)
    else:
        print("decode: no specialized decoder available")
    return 0


# -----------------------------
# sm83
# -----------------------------

def cmd_sm83(args: argparse.Namespace) -> int:
    if args.simulate_shift_a is not None:
        return simulate_shift_a(parse_int(args.simulate_shift_a))
    if not args.instruction:
        raise SystemExit("Provide instruction or --simulate-shift-a VALUE")
    instr = args.instruction.strip()
    k = canonical(instr)

    m = re.fullmatch(r"rst(\$[0-9a-f]+|0x[0-9a-f]+|\d+)", k)
    if m:
        target = parse_int(m.group(1))
        if target not in {0,8,0x10,0x18,0x20,0x28,0x30,0x38}:
            raise SystemExit("RST target must be one of 00,08,10,18,20,28,30,38")
        print(f"RST {fmt_hex(target,2)}: push PC; jump to {fmt_hex(target,4)}. Software restart/call, not a hardware interrupt vector.")
        return 0

    post = {
        "lda,[hl+]": "A <- [HL]; then HL++",
        "ld[hl+],a": "[HL] <- A; then HL++",
        "lda,[hl-]": "A <- [HL]; then HL--",
        "ld[hl-],a": "[HL] <- A; then HL--",
    }
    if k in post:
        print(f"{instr.upper()}: {post[k]}. Access happens before HL changes. Flags unchanged.")
        return 0

    m = re.fullmatch(r"ldha,\[(.+)\]", k)
    if m:
        target, note = ldh_addr(m.group(1))
        print(f"LDH A,[n/symbol]: A <- {target}. Flags unchanged.")
        print(f"Note: {note}.")
        return 0
    m = re.fullmatch(r"ldh\[(.+)\],a", k)
    if m:
        target, note = ldh_addr(m.group(1))
        print(f"LDH [n/symbol],A: {target} <- A. Flags unchanged.")
        print(f"Note: {note}.")
        return 0
    if k == "ldh[c],a":
        print("LDH [C],A: [$FF00+C] <- A. Flags unchanged."); return 0
    if k == "ldha,[c]":
        print("LDH A,[C]: A <- [$FF00+C]. Flags unchanged."); return 0

    m = re.fullmatch(r"(inc|dec)(bc|de|hl|sp)", k)
    if m:
        op, r = m.groups()
        sign = "+1" if op == "inc" else "-1"
        print(f"{op.upper()} {r.upper()}: {r.upper()} <- {r.upper()}{sign} (16-bit). Flags unchanged.")
        return 0
    m = re.fullmatch(r"(inc|dec)([abcdehl])", k)
    if m:
        op, r = m.groups()
        if op == "inc":
            print(f"INC {r.upper()}: {r.upper()} <- {r.upper()}+1. Flags: Z if zero; N=0; H from bit-3 carry; C unchanged.")
        else:
            print(f"DEC {r.upper()}: {r.upper()} <- {r.upper()}-1. Flags: Z if zero; N=1; H from bit-4 borrow; C unchanged.")
        return 0
    if k == "inc[hl]":
        print("INC [HL]: byte at HL <- byte+1. Flags: Z if zero; N=0; H from bit-3 carry; C unchanged."); return 0
    if k == "dec[hl]":
        print("DEC [HL]: byte at HL <- byte-1. Flags: Z if zero; N=1; H from bit-4 borrow; C unchanged."); return 0

    m = re.fullmatch(r"ld([abcdehl]),([abcdehl])", k)
    if m:
        d, s = m.groups(); print(f"LD {d.upper()},{s.upper()}: {d.upper()} <- {s.upper()}. Flags unchanged."); return 0
    m = re.fullmatch(r"ld([abcdehl]),(.+)", k)
    if m and is_num(m.group(2)):
        r, raw = m.groups(); print(f"LD {r.upper()},{fmt_hex(parse_int(raw)&0xFF,2)}: load 8-bit immediate. Flags unchanged."); return 0
    m = re.fullmatch(r"ld(bc|de|hl|sp),(.+)", k)
    if m and is_num(m.group(2)):
        r, raw = m.groups(); print(f"LD {r.upper()},{fmt_hex(parse_int(raw)&0xFFFF,4)}: load 16-bit immediate. Flags unchanged."); return 0
    m = re.fullmatch(r"ld([abcdehl]),\[(.+)\]", k)
    if m:
        r, src = m.groups(); print(f"LD {r.upper()},[{src}]: {r.upper()} <- memory byte. Flags unchanged."); return 0
    m = re.fullmatch(r"ld\[(.+)\],([abcdehl])", k)
    if m:
        dst, r = m.groups(); print(f"LD [{dst}],{r.upper()}: memory byte <- {r.upper()}. Flags unchanged."); return 0

    if k == "anda":
        print("AND A: A unchanged; Z=1 if A==0; N=0 H=1 C=0. Zero-test idiom. XOR A clears A; AND A does not."); return 0
    if k == "ora":
        print("OR A: A unchanged; Z=1 if A==0; N=0 H=0 C=0. Zero-test idiom. XOR A clears A; OR A does not."); return 0
    if k == "xora":
        print("XOR A: A <- $00. Flags: Z=1 N=0 H=0 C=0. Common zeroing idiom."); return 0
    m = re.fullmatch(r"xora,?(.+)", k)
    if m:
        op = m.group(1); print(f"XOR A,{op}: A <- A XOR {op}. Flags: Z if result zero; N/H/C reset. Only differing bits flip."); return 0
    m = re.fullmatch(r"cp(?:a,)?(.+)", k)
    if m:
        op = m.group(1); print(f"CP {op}: compare A with operand using A-operand for flags only. A unchanged; Z=1 if equal."); return 0
    m = re.fullmatch(r"bit(.+),([abcdehl]|\[hl\])", k)
    if m:
        bit, r = m.groups(); print(f"BIT {bit},{r.upper()}: test bit {bit}. Operand unchanged; Z=1 if bit is 0; N=0 H=1."); return 0
    if k == "slae":
        print("SLA E: E <<= 1; old bit 7 -> C; bit 0 becomes 0. Flags from result."); return 0
    if k == "rld":
        print("RL D: rotate D left through carry; old carry enters bit 0; old bit 7 -> C. Flags from result."); return 0

    m = re.fullmatch(r"jr(nz|z|nc|c),(.+)", k)
    if m:
        cond, target = m.groups(); desc = {"z":"Z=1","nz":"Z=0","c":"C=1","nc":"C=0"}[cond]
        print(f"JR {cond.upper()},{target}: relative jump if {desc}. Flags unchanged."); return 0
    if re.fullmatch(r"jr.+", k):
        print("JR target: unconditional relative jump. Flags unchanged."); return 0
    m = re.fullmatch(r"ret(nz|z|nc|c)?", k)
    if m:
        cond = m.group(1)
        if cond is None:
            print("RET: unconditional return. Flags unchanged.")
        else:
            desc = {"z":"Z=1","nz":"Z=0","c":"C=1","nc":"C=0"}[cond]
            print(f"RET {cond.upper()}: return if {desc}. Flags unchanged.")
        return 0
    m = re.fullmatch(r"call(nz|z|nc|c)?,?.+", k)
    if m:
        cond = m.group(1)
        print("CALL: push return address and jump. Callee side effects unknown." if cond is None else f"CALL {cond.upper()}: conditional call. Callee side effects unknown.")
        return 0
    if k == "pushaf":
        print("PUSH AF: save A and flags on stack. SP decreases by 2. Registers unchanged."); return 0
    if k == "popaf":
        print("POP AF: restore A and flags from stack. SP increases by 2. A and flags change."); return 0

    print(f"No built-in explanation for: {instr}")
    print("Do not conclude invalid. Use RAG for the mnemonic/instruction family, then state uncertainty if unresolved.")
    return 1


def simulate_shift_a(a: int) -> int:
    a &= 0xFF
    d, e, c = 0, a, 0
    print(f"initial: A={fmt_hex(a,2)} DE={fmt_hex((d<<8)|e,4)}")
    for op in ("sla e", "rl d", "sla e", "rl d"):
        if op == "sla e":
            c = (e >> 7) & 1; e = (e << 1) & 0xFF
        else:
            old = c; c = (d >> 7) & 1; d = ((d << 1) & 0xFF) | old
        print(f"{op:5}: D={fmt_hex(d,2)} E={fmt_hex(e,2)} DE={fmt_hex((d<<8)|e,4)} C={c}")
    print(f"result: DE={fmt_hex((d<<8)|e,4)} decimal={(d<<8)|e}")
    print("Effect: starting from DE=A, two SLA/RL pairs multiply DE by 4 modulo 16 bits.")
    return 0


# -----------------------------
# trace
# -----------------------------

@dataclass
class TraceState:
    a: int = 0; b: int = 0; c: int = 0; d: int = 0; e: int = 0; h: int = 0; l: int = 0
    z: int | None = None; n: int | None = None; hflag: int | None = None; carry: int = 0
    stack: list[tuple[int, int | None, int | None, int | None, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def hl(self) -> int: return ((self.h & 0xFF) << 8) | (self.l & 0xFF)
    @hl.setter
    def hl(self, v: int) -> None: self.h, self.l = ((v & 0xFFFF) >> 8) & 0xFF, v & 0xFF
    @property
    def de(self) -> int: return ((self.d & 0xFF) << 8) | (self.e & 0xFF)
    @de.setter
    def de(self, v: int) -> None: self.d, self.e = ((v & 0xFFFF) >> 8) & 0xFF, v & 0xFF
    def reg(self, r: str) -> int: return getattr(self, r.lower())
    def set_reg(self, r: str, v: int) -> None: setattr(self, r.lower(), v & 0xFF)
    def flags(self) -> str: return f"Z={self.z if self.z is not None else '?'} N={self.n if self.n is not None else '?'} H={self.hflag if self.hflag is not None else '?'} C={self.carry}"
    def summary(self) -> str: return f"A={fmt_hex(self.a,2)} B={fmt_hex(self.b,2)} C={fmt_hex(self.c,2)} D={fmt_hex(self.d,2)} E={fmt_hex(self.e,2)} HL={fmt_hex(self.hl,4)} DE={fmt_hex(self.de,4)} {self.flags()}"


def trace_one(s: TraceState, instr: str) -> str:
    raw, k = instr.strip(), canonical(instr)
    if is_label(raw): return f"{raw}: label/no-op for trace"

    if k in {"lda,[hl+]", "ld[hl+],a", "lda,[hl-]", "ld[hl-],a"}:
        addr, delta = s.hl, (1 if "+" in k else -1)
        if k.startswith("lda"):
            s.notes.append(f"A reads [{fmt_hex(addr,4)}]; byte unknown")
            msg = f"{raw}: A <- [{fmt_hex(addr,4)}]; HL <- {fmt_hex((addr+delta)&0xFFFF,4)}"
        else:
            s.notes.append(f"[{fmt_hex(addr,4)}] <- A({fmt_hex(s.a,2)})")
            msg = f"{raw}: [{fmt_hex(addr,4)}] <- A({fmt_hex(s.a,2)}); HL <- {fmt_hex((addr+delta)&0xFFFF,4)}"
        s.hl += delta
        return msg

    m = re.fullmatch(r"ld([abcdehl]),([abcdehl])", k)
    if m:
        d, src = m.groups(); s.set_reg(d, s.reg(src)); return f"{raw}: {d.upper()} <- {src.upper()}({fmt_hex(s.reg(d),2)}); flags unchanged"
    m = re.fullmatch(r"ld([abcdehl]),(.+)", k)
    if m and is_num(m.group(2)):
        r, val = m.groups(); s.set_reg(r, parse_int(val)); return f"{raw}: {r.upper()} <- {fmt_hex(s.reg(r),2)}; flags unchanged"
    m = re.fullmatch(r"ld(bc|de|hl),(.+)", k)
    if m and is_num(m.group(2)):
        r, val = m.groups()
        if r == "hl": s.hl = parse_int(val)
        if r == "de": s.de = parse_int(val)
        return f"{raw}: {r.upper()} <- {fmt_hex(parse_int(val)&0xFFFF,4)}; flags unchanged"

    if k == "anda":
        s.z, s.n, s.hflag, s.carry = (1 if s.a == 0 else 0), 0, 1, 0
        return f"{raw}: A unchanged({fmt_hex(s.a,2)}); {s.flags()}"
    if k == "ora":
        s.z, s.n, s.hflag, s.carry = (1 if s.a == 0 else 0), 0, 0, 0
        return f"{raw}: A unchanged({fmt_hex(s.a,2)}); {s.flags()}"
    if k == "xora":
        s.a, s.z, s.n, s.hflag, s.carry = 0, 1, 0, 0, 0
        return f"{raw}: A <- $00; {s.flags()}"
    m = re.fullmatch(r"xora,?(.+)", k)
    if m and is_num(m.group(1)):
        old, val = s.a, parse_int(m.group(1)) & 0xFF
        s.a ^= val
        s.z, s.n, s.hflag, s.carry = (1 if s.a == 0 else 0), 0, 0, 0
        return f"{raw}: A {fmt_hex(old,2)} XOR {fmt_hex(val,2)} -> {fmt_hex(s.a,2)}; {s.flags()}"
    m = re.fullmatch(r"cp(?:a,)?(.+)", k)
    if m and is_num(m.group(1)):
        val = parse_int(m.group(1)) & 0xFF
        s.z, s.n, s.hflag, s.carry = (1 if s.a == val else 0), 1, (1 if (s.a & 0xF) < (val & 0xF) else 0), (1 if s.a < val else 0)
        return f"{raw}: compare A={fmt_hex(s.a,2)} with {fmt_hex(val,2)}; A unchanged; {s.flags()}"
    m = re.fullmatch(r"bit([0-7]),([abcdehl])", k)
    if m:
        bit, reg = int(m.group(1)), m.group(2)
        v = s.reg(reg); s.z, s.n, s.hflag = (1 if ((v >> bit) & 1) == 0 else 0), 0, 1
        return f"{raw}: test bit {bit} of {reg.upper()}={fmt_hex(v,2)}; {reg.upper()} unchanged; {s.flags()}"

    if k == "pushaf":
        s.stack.append((s.a, s.z, s.n, s.hflag, s.carry)); return f"{raw}: push AF; saved A={fmt_hex(s.a,2)}, {s.flags()}"
    if k == "popaf":
        if not s.stack:
            s.z = s.n = s.hflag = None; return f"{raw}: pop AF; stack unknown -> A/flags unknown"
        s.a, s.z, s.n, s.hflag, s.carry = s.stack.pop(); return f"{raw}: pop AF; restored A={fmt_hex(s.a,2)}, {s.flags()}"

    m = re.fullmatch(r"jr(nz|z|nc|c),(.+)", k)
    if m:
        cond, target = m.groups()
        flag = s.z if cond in {"z","nz"} else s.carry
        if flag is None: return f"{raw}: branch depends on {cond.upper()} flag; current value unknown"
        taken = (flag == 0) if cond in {"nz","nc"} else (flag == 1)
        return f"{raw}: branch {'taken' if taken else 'not taken'} ({cond.upper()}); target={target}"
    if re.fullmatch(r"jr.+", k): return f"{raw}: unconditional jump; trace continues linearly unless snippet stops"
    m = re.fullmatch(r"ret(nz|z|nc|c)?", k)
    if m:
        cond = m.group(1)
        if cond is None: return f"{raw}: unconditional return"
        flag = s.z if cond in {"z","nz"} else s.carry
        if flag is None: return f"{raw}: return depends on {cond.upper()} flag; current value unknown"
        taken = (flag == 0) if cond in {"nz","nc"} else (flag == 1)
        return f"{raw}: return {'taken' if taken else 'not taken'} ({cond.upper()})"

    if k == "inc[hl]": s.z = None; s.n = 0; s.hflag = None; return f"{raw}: [HL={fmt_hex(s.hl,4)}] <- byte+1; flags partly unknown"
    if k == "dec[hl]": s.z = None; s.n = 1; s.hflag = None; return f"{raw}: [HL={fmt_hex(s.hl,4)}] <- byte-1; flags partly unknown"

    m = re.fullmatch(r"ldh\[(.+)\],a", k)
    if m:
        target, note = ldh_addr(m.group(1)); s.notes.append(f"{target} <- A({fmt_hex(s.a,2)}); {note}")
        return f"{raw}: {target} <- A({fmt_hex(s.a,2)}); flags unchanged"
    m = re.fullmatch(r"ldha,\[(.+)\]", k)
    if m:
        target, note = ldh_addr(m.group(1)); s.notes.append(f"A reads {target}; value unknown; {note}")
        return f"{raw}: A <- {target}; value unknown; flags unchanged"

    return f"{raw}: not simulated; use sm83/RAG if this affects a claim"


def cmd_trace(args: argparse.Namespace) -> int:
    s = TraceState()
    for r in "abcde":
        v = getattr(args, r)
        if v is not None: s.set_reg(r, parse_int(v))
    if args.hl is not None: s.hl = parse_int(args.hl)
    if args.de is not None: s.de = parse_int(args.de)
    print("initial:"); print(s.summary()); print()
    for i, instr in enumerate([p.strip() for p in re.split(r"[;\n]", args.instructions) if p.strip()], 1):
        print(f"{i}. {trace_one(s, instr)}")
        if args.show_state: print(f"   state: {s.summary()}")
    print("\nfinal:"); print(s.summary())
    if s.notes:
        print("\nnotes:")
        for n in s.notes: print(f"- {n}")
    return 0


# -----------------------------
# flow
# -----------------------------

@dataclass
class FlowValue:
    text: str
    kind: str = "unknown"  # concrete, symbolic, expression, unknown

    def __str__(self) -> str:
        return self.text


def value_from_token(token: str) -> FlowValue:
    token = token.strip()
    if is_num(token):
        return FlowValue(fmt_hex(parse_int(token) & 0xFF, 2), "concrete")
    if token:
        return FlowValue(token, "symbolic")
    return FlowValue("unknown", "unknown")


def value_from_memory(token: str) -> FlowValue:
    return FlowValue(f"[{token.strip()}]", "symbolic")


def concrete_int(v: FlowValue) -> int | None:
    if v.kind != "concrete":
        return None
    try:
        return parse_int(v.text)
    except Exception:
        return None


@dataclass
class FlowFlag:
    text: str = "unknown"
    kind: str = "unknown"  # concrete_true, concrete_false, runtime, unknown

    def __str__(self) -> str:
        return self.text


@dataclass
class FlowState:
    regs: dict[str, FlowValue] = field(default_factory=lambda: {r: FlowValue("unknown", "unknown") for r in "abcdehl"})
    z: FlowFlag = field(default_factory=FlowFlag)
    c: FlowFlag = field(default_factory=FlowFlag)
    last_test: str = "unknown"
    stack: list[tuple[FlowValue, FlowFlag]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def getv(self, r: str) -> FlowValue:
        return self.regs.get(r.lower(), FlowValue("unknown", "unknown"))

    def get(self, r: str) -> str:
        return str(self.getv(r))

    def setv(self, r: str, v: FlowValue) -> None:
        self.regs[r.lower()] = v

    def set(self, r: str, text: str, kind: str = "symbolic") -> None:
        self.setv(r, FlowValue(text, kind))

    def summary(self) -> str:
        regs = " ".join(f"{r.upper()}={self.regs[r].text}({self.regs[r].kind})" for r in "abcdehl")
        return f"{regs} | Z={self.z.text}({self.z.kind}) | C={self.c.text}({self.c.kind}) | last_test={self.last_test}"


def split_lines(text: str) -> list[str]:
    out = []
    # Treat multiline input as assembly. Inline comments are removed.
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line:
            out.append(line)
    # Treat single-line semicolon input as instruction separators.
    if len(out) <= 1 and ";" in text:
        out = [p.strip() for p in text.split(";") if p.strip()]
    return out


def z_from_value_test(v: FlowValue) -> FlowFlag:
    n = concrete_int(v)
    if n is not None:
        return FlowFlag("1" if (n & 0xFF) == 0 else "0", "concrete_true" if (n & 0xFF) == 0 else "concrete_false")
    if v.kind in {"symbolic", "expression"}:
        return FlowFlag(f"1 if {v.text} == 0 else 0", "runtime")
    return FlowFlag("unknown", "unknown")


def z_from_bit_test(v: FlowValue, bit: str) -> FlowFlag:
    n = concrete_int(v)
    if n is not None and bit.isdigit():
        b = int(bit)
        z = 1 if ((n >> b) & 1) == 0 else 0
        return FlowFlag(str(z), "concrete_true" if z == 1 else "concrete_false")
    if v.kind in {"symbolic", "expression"}:
        return FlowFlag(f"1 if bit {bit} of {v.text} is 0 else 0", "runtime")
    return FlowFlag("unknown", "unknown")


def z_from_compare(a: FlowValue, op: str) -> FlowFlag:
    av = concrete_int(a)
    if av is not None and is_num(op):
        ov = parse_int(op) & 0xFF
        z = 1 if (av & 0xFF) == ov else 0
        return FlowFlag(str(z), "concrete_true" if z == 1 else "concrete_false")
    if a.kind in {"symbolic", "expression"} or not is_num(op):
        return FlowFlag(f"1 if A({a.text}) == {op} else 0", "runtime")
    return FlowFlag("unknown", "unknown")


def branch_condition(flag: FlowFlag, cond: str) -> str:
    want_true = cond in {"z", "c"}
    if flag.kind in {"concrete_true", "concrete_false"}:
        flag_is_true = flag.text == "1"
        taken = flag_is_true == want_true
        return "always taken" if taken else "falls through"
    if flag.kind == "runtime":
        return "runtime-dependent"
    return "unknown"


def flow_one(s: FlowState, instr: str) -> str:
    raw, k = instr.strip(), canonical(instr)
    if is_label(raw):
        return f"{raw}: label only; state unchanged"

    m = re.fullmatch(r"ldha,\[(.+)\]", k)
    if m:
        target, note = ldh_addr(m.group(1))
        v = FlowValue(target, "symbolic")
        s.setv("a", v)
        s.notes.append(f"A loaded from {target}; {note}; runtime value")
        return f"{raw}: A <- {target} (symbolic runtime value); flags unchanged"

    m = re.fullmatch(r"ldh\[(.+)\],a", k)
    if m:
        target, note = ldh_addr(m.group(1))
        s.notes.append(f"{target} written from A={s.get('a')}; {note}")
        return f"{raw}: {target} <- A({s.get('a')}); flags unchanged; registers unchanged"

    m = re.fullmatch(r"ld([abcdehl]),\[(.+)\]", k)
    if m:
        r, src = m.groups()
        v = value_from_memory(src)
        s.setv(r, v)
        return f"{raw}: {r.upper()} <- {v.text} (symbolic runtime value); flags unchanged"

    m = re.fullmatch(r"ld\[(.+)\],a", k)
    if m:
        dst = f"[{m.group(1)}]"
        s.notes.append(f"{dst} written from A={s.get('a')}")
        return f"{raw}: {dst} <- A({s.get('a')}); flags unchanged; registers unchanged"

    m = re.fullmatch(r"ld([abcdehl]),([abcdehl])", k)
    if m:
        d, src = m.groups()
        s.setv(d, s.getv(src))
        return f"{raw}: {d.upper()} <- {src.upper()}({s.get(d)}); flags unchanged"

    m = re.fullmatch(r"ld([abcdehl]),(.+)", k)
    if m and not m.group(2).startswith("["):
        r, v = m.groups()
        s.setv(r, value_from_token(v))
        return f"{raw}: {r.upper()} <- {s.get(r)} ({s.getv(r).kind}); flags unchanged"

    if k == "anda":
        a = s.getv("a")
        s.z = z_from_value_test(a)
        s.last_test = f"A({a.text}) == 0"
        return f"{raw}: A unchanged({a.text}); Z={s.z.text} ({s.z.kind})"

    if k == "ora":
        a = s.getv("a")
        s.z = z_from_value_test(a)
        s.last_test = f"A({a.text}) == 0"
        return f"{raw}: A unchanged({a.text}); Z={s.z.text} ({s.z.kind})"

    if k == "xora":
        s.setv("a", FlowValue("$00", "concrete"))
        s.z = FlowFlag("1", "concrete_true")
        s.last_test = "A cleared by XOR A"
        return f"{raw}: A <- $00 (concrete); Z=1"

    m = re.fullmatch(r"xora,?(.+)", k)
    if m:
        op = m.group(1)
        before = s.getv("a")
        if before.kind == "concrete" and is_num(op):
            new = (parse_int(before.text) ^ parse_int(op)) & 0xFF
            s.setv("a", FlowValue(fmt_hex(new, 2), "concrete"))
        else:
            s.setv("a", FlowValue(f"({before.text} XOR {op})", "expression"))
        s.z = z_from_value_test(s.getv("a"))
        s.last_test = f"A({s.get('a')}) == 0"
        return f"{raw}: A <- {s.get('a')} ({s.getv('a').kind}); Z={s.z.text} ({s.z.kind})"

    m = re.fullmatch(r"bit(.+),([abcdehl])", k)
    if m:
        bit, r = m.groups()
        rv = s.getv(r)
        s.z = z_from_bit_test(rv, bit)
        s.last_test = f"bit {bit} of {r.upper()}({rv.text})"
        return f"{raw}: tests bit {bit} of {r.upper()}({rv.text}); {r.upper()} unchanged; A={s.get('a')}; Z={s.z.text} ({s.z.kind})"

    m = re.fullmatch(r"cp(?:a,)?(.+)", k)
    if m:
        op = m.group(1)
        av = s.getv("a")
        s.z = z_from_compare(av, op)
        s.last_test = f"A({av.text}) == {op}"
        return f"{raw}: compare A({av.text}) with {op}; A unchanged; Z={s.z.text} ({s.z.kind})"

    if k == "inc[hl]":
        s.z = FlowFlag("depends on [HL]+1 result", "runtime")
        s.last_test = "[HL]+1 == 0"
        return f"{raw}: [HL] <- [HL]+1; Z depends on memory result (runtime)"
    if k == "dec[hl]":
        s.z = FlowFlag("depends on [HL]-1 result", "runtime")
        s.last_test = "[HL]-1 == 0"
        return f"{raw}: [HL] <- [HL]-1; Z depends on memory result (runtime)"

    m = re.fullmatch(r"(inc|dec)([abcdehl])", k)
    if m:
        op, r = m.groups()
        before = s.getv(r)
        if before.kind == "concrete":
            delta = 1 if op == "inc" else -1
            new = (parse_int(before.text) + delta) & 0xFF
            s.setv(r, FlowValue(fmt_hex(new, 2), "concrete"))
        else:
            sign = "+1" if op == "inc" else "-1"
            s.setv(r, FlowValue(f"({before.text}{sign})", "expression"))
        s.z = z_from_value_test(s.getv(r))
        s.last_test = f"{r.upper()}({s.get(r)}) == 0"
        return f"{raw}: {r.upper()} <- {s.get(r)} ({s.getv(r).kind}); Z={s.z.text} ({s.z.kind})"

    if k == "pushaf":
        s.stack.append((s.getv("a"), s.z))
        return f"{raw}: push AF; saved A={s.get('a')} ({s.getv('a').kind}), Z={s.z.text} ({s.z.kind})"

    if k == "popaf":
        if not s.stack:
            s.setv("a", FlowValue("unknown_after_pop", "unknown"))
            s.z = FlowFlag("unknown_after_pop", "unknown")
            return f"{raw}: pop AF; stack source unknown -> A/Z unknown"
        a, z = s.stack.pop()
        s.setv("a", a)
        s.z = z
        return f"{raw}: pop AF; restored A={a.text} ({a.kind}), Z={z.text} ({z.kind})"

    m = re.fullmatch(r"jr(nz|z|nc|c),(.+)", k)
    if m:
        cond, target = m.groups()
        flag = s.z if cond in {"z", "nz"} else s.c
        status = branch_condition(flag, cond)
        meaning = {"z":"Z==1", "nz":"Z==0", "c":"C==1", "nc":"C==0"}[cond]
        return f"{raw}: condition {meaning}; status={status}; target={target}; flag={flag.text} ({flag.kind}); last_test={s.last_test}"

    if re.fullmatch(r"jr.+", k):
        return f"{raw}: unconditional jump; flow continues linearly unless snippet stops"

    m = re.fullmatch(r"ret(nz|z|nc|c)?", k)
    if m:
        cond = m.group(1)
        if cond is None:
            return f"{raw}: unconditional return"
        flag = s.z if cond in {"z", "nz"} else s.c
        status = branch_condition(flag, cond)
        meaning = {"z":"Z==1", "nz":"Z==0", "c":"C==1", "nc":"C==0"}[cond]
        return f"{raw}: condition {meaning}; status={status}; flag={flag.text} ({flag.kind}); last_test={s.last_test}"

    if k.startswith("call"):
        return f"{raw}: call; callee side effects unknown without convention"
    return f"{raw}: not modeled; state assumed unchanged"


def cmd_flow(args: argparse.Namespace) -> int:
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else args.instructions
    if raw is None:
        raise SystemExit("Provide instructions or --file")
    s = FlowState()
    for r in "abcdehl":
        v = getattr(args, r)
        if v is not None:
            s.setv(r, value_from_token(v))
    print("symbolic flow")
    print("initial:")
    print(s.summary())
    print()
    for i, line in enumerate(split_lines(raw), 1):
        print(f"{i}. {flow_one(s, line)}")
        if args.show_state:
            print(f"   state: {s.summary()}")
    print("\nfinal:")
    print(s.summary())
    if s.notes:
        print("\nnotes:")
        for n in s.notes:
            print(f"- {n}")
    return 0


# -----------------------------
# hwstruct
# -----------------------------

STRUCTS = {
    "oam": {
        "name": "Object Attribute Memory sprite entry",
        "size": 4,
        "range": "$FE00-$FE9F",
        "count": 40,
        "fields": [
            (0, "Y position", "Stored Y; on-screen Y is stored value minus 16."),
            (1, "X position", "Stored X; on-screen X is stored value minus 8."),
            (2, "Tile index", "Object tile number. In 8x16 OBJ mode, bit 0 is ignored."),
            (3, "Attributes", "Priority, flips, palette/bank flags; exact bits differ by DMG/CGB feature."),
        ],
    }
}


def cmd_hwstruct(args: argparse.Namespace) -> int:
    aliases = {"obj":"oam", "sprite":"oam", "sprite_entry":"oam", "oam_entry":"oam"}
    key = aliases.get(args.struct.lower(), args.struct.lower())
    if key not in STRUCTS:
        print("known_structs:")
        for k, s in STRUCTS.items(): print(f"- {k}: {s['name']}")
        raise SystemExit(f"unknown hardware struct: {args.struct}")
    s = STRUCTS[key]
    print(f"struct: {key} - {s['name']}")
    print(f"size:   {s['size']} bytes")
    print(f"range:  {s['range']}")
    print(f"count:  {s['count']}")
    if args.offset is None:
        print("fields:")
        for off, name, meaning in s["fields"]:
            print(f"- +{off}: {name} — {meaning}")
        return 0
    off = parse_int(args.offset)
    if 0xFE00 <= off <= 0xFE9F:
        entry = (off - 0xFE00) // s["size"]
        field_off = (off - 0xFE00) % s["size"]
        print(f"absolute_address: {fmt_hex(off,4)}")
        print(f"entry_index:      {entry}")
        print(f"field_offset:     +{field_off}")
    else:
        field_off = off
        print(f"field_offset: +{field_off}")
    for foff, name, meaning in s["fields"]:
        if foff == field_off:
            print(f"field:   +{foff} {name}")
            print(f"meaning: {meaning}")
            return 0
    raise SystemExit(f"no field at offset +{field_off} for {key}")




# -----------------------------
# line / scan
# -----------------------------

def load_snippet_text(args) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if getattr(args, "text", None):
        return args.text
    raise SystemExit("Provide snippet text or --file")


def strip_inline_comment(line: str) -> str:
    return line.split(";", 1)[0].rstrip()


def numbered_source_lines(text: str) -> list[tuple[int, str, str]]:
    rows = []
    for idx, raw in enumerate(text.splitlines(), 1):
        code = strip_inline_comment(raw).strip()
        rows.append((idx, raw.rstrip("\n"), code))
    return rows


def cmd_line(args: argparse.Namespace) -> int:
    text = load_snippet_text(args)
    rows = numbered_source_lines(text)

    if args.find:
        needle = args.find.lower()
        matches = [row for row in rows if needle in row[1].lower()]
        if not matches:
            print(f"no matches for: {args.find}")
            return 0
        wanted = set()
        for line_no, _, _ in matches:
            start = max(1, line_no - args.context)
            end = min(len(rows), line_no + args.context)
            wanted.update(range(start, end + 1))
        rows = [row for row in rows if row[0] in wanted]

    width = len(str(rows[-1][0] if rows else 0))
    for line_no, raw, _ in rows:
        print(f"{line_no:>{width}}: {raw}")
    return 0


def parse_label_from_code(code: str) -> str | None:
    c = code.strip()
    if not c:
        return None
    m = re.match(r"^([.$A-Za-z_][\w.$]*)(::|:)\s*$", c)
    return m.group(1) if m else None


def parse_branch_target(code: str) -> tuple[str, str] | None:
    c = code.strip()
    if not c:
        return None

    m = re.match(r"^(jr|jp|call)\s+(?:(?:z|nz|c|nc)\s*,\s*)?([.$A-Za-z_][\w.$]*)", c, re.I)
    if m:
        return m.group(1).lower(), m.group(2)

    m = re.match(r"^(ret)\s+(z|nz|c|nc)\b", c, re.I)
    if m:
        return m.group(1).lower(), m.group(2).lower()

    m = re.match(r"^(rst)\s+(\$[0-9A-Fa-f]+|0x[0-9A-Fa-f]+|\d+)", c, re.I)
    if m:
        return m.group(1).lower(), m.group(2)

    return None


def extract_symbols_from_code(code: str) -> set[str]:
    cleaned = re.sub(r"'.*?'", " ", code)
    tokens = set(re.findall(r"\b[A-Za-z_][\w.$]*\b|[.][A-Za-z_][\w.$]*", cleaned))
    mnemonics = {
        "ld", "ldh", "ldi", "ldd", "jr", "jp", "call", "ret", "rst", "and", "or", "xor",
        "cp", "bit", "inc", "dec", "push", "pop", "add", "adc", "sub", "sbc", "sla",
        "rl", "rr", "rla", "rra", "nop", "di", "ei", "halt", "stop"
    }
    regs = {"a", "b", "c", "d", "e", "h", "l", "af", "bc", "de", "hl", "sp", "pc"}
    return {t for t in tokens if t.lower() not in mnemonics and t.lower() not in regs}


def previous_code_line(rows: list[tuple[int, str, str]], line_no: int) -> tuple[int, str, str] | None:
    for row in reversed(rows[:line_no - 1]):
        if row[2]:
            return row
    return None


def cmd_scan(args: argparse.Namespace) -> int:
    text = load_snippet_text(args)
    rows = numbered_source_lines(text)

    labels: dict[str, int] = {}
    symbols: dict[str, list[int]] = {}
    refs: list[tuple[int, str, str, str, int | None, str | None]] = []

    for line_no, raw, code in rows:
        label = parse_label_from_code(code)
        if label:
            labels[label] = line_no
        for sym in extract_symbols_from_code(code):
            symbols.setdefault(sym, []).append(line_no)

    for line_no, raw, code in rows:
        branch = parse_branch_target(code)
        if not branch:
            continue
        mnemonic, target = branch
        target_line = labels.get(target)
        prev = previous_code_line(rows, line_no)
        prev_code = prev[2] if prev else None
        refs.append((line_no, mnemonic, target, code, target_line, prev_code))

    if args.symbol:
        sym = args.symbol
        print(f"symbol: {sym}")
        if sym in labels:
            print(f"local_definition_line: {labels[sym]}")
        else:
            print("local_definition_line: not found in provided snippet")
        used = symbols.get(sym, [])
        print(f"local_reference_count: {len(used)}")
        if used:
            print("local_references:")
            for n in used:
                print(f"- line {n}: {rows[n-1][1]}")
        print("resolution_scope: snippet-local only")
        print("project_lookup: not implemented here; external definitions/constants/macros remain unresolved")
        return 0

    print("snippet_scan")
    print(f"line_count: {len(rows)}")

    print("\nlabels:")
    if labels:
        for name, line in labels.items():
            print(f"- {name}: line {line}")
    else:
        print("- none found")

    print("\nbranches_and_calls:")
    if refs:
        for line_no, mnemonic, target, code, target_line, prev_code in refs:
            target_desc = f"line {target_line}" if target_line is not None else "external/unresolved"
            print(f"- line {line_no}: {code}")
            print(f"  target: {target} ({target_desc})")
            print(f"  previous_code_line: {prev_code or 'none'}")
    else:
        print("- none found")

    print("\nlikely_symbols:")
    for sym in sorted(symbols):
        if sym in labels:
            continue
        print(f"- {sym}: {len(symbols[sym])} local reference(s)")

    print("\nresolution_scope: snippet-local only; external definitions/constants/macros require project search")
    return 0

# -----------------------------
# Parser
# -----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GRAIL deterministic helper tools")
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("num", help="Number/base/bit helper")
    q.add_argument("value"); q.add_argument("--bits", action="store_true"); q.add_argument("--test-bit", type=int); q.add_argument("--mask"); q.set_defaults(func=cmd_num)

    q = sub.add_parser("addr", help="Game Boy address classifier/converter")
    q.add_argument("address", nargs="?"); q.add_argument("--ldh"); q.add_argument("--offset"); q.add_argument("--bank"); q.add_argument("--addr"); q.set_defaults(func=cmd_addr)

    q = sub.add_parser("range", help="Count/classify repeated linear memory accesses")
    q.add_argument("start"); q.add_argument("--writes", required=True); q.add_argument("--step", type=int, default=1)
    m = q.add_mutually_exclusive_group(); m.add_argument("--post", action="store_true"); m.add_argument("--pre", action="store_true")
    q.set_defaults(func=cmd_range)

    q = sub.add_parser("hw", help="Game Boy hardware register/value decoder")
    q.add_argument("address"); q.add_argument("--value"); q.set_defaults(func=cmd_hw)

    q = sub.add_parser("hwstruct", help="Look up structured hardware memory layouts")
    q.add_argument("struct"); q.add_argument("--offset"); q.set_defaults(func=cmd_hwstruct)

    q = sub.add_parser("sm83", help="Small SM83 instruction lookup")
    q.add_argument("instruction", nargs="?"); q.add_argument("--simulate-shift-a"); q.set_defaults(func=cmd_sm83)

    q = sub.add_parser("trace", help="Trace a tiny straight-line SM83 snippet with concrete values")
    q.add_argument("instructions"); q.add_argument("--a"); q.add_argument("--b"); q.add_argument("--c"); q.add_argument("--d"); q.add_argument("--e"); q.add_argument("--hl"); q.add_argument("--de"); q.add_argument("--show-state", action="store_true"); q.set_defaults(func=cmd_trace)

    q = sub.add_parser("flow", help="Symbolically track register provenance through a short snippet")
    q.add_argument("instructions", nargs="?"); q.add_argument("--file"); q.add_argument("--a"); q.add_argument("--b"); q.add_argument("--c"); q.add_argument("--d"); q.add_argument("--e"); q.add_argument("--h"); q.add_argument("--l"); q.add_argument("--show-state", action="store_true"); q.set_defaults(func=cmd_flow)


    q = sub.add_parser("line", help="Print stable line numbers for a snippet or file")
    q.add_argument("text", nargs="?"); q.add_argument("--file"); q.add_argument("--find"); q.add_argument("--context", type=int, default=2); q.set_defaults(func=cmd_line)

    q = sub.add_parser("scan", help="Scan snippet labels, branch targets, and local symbol references")
    q.add_argument("text", nargs="?"); q.add_argument("--file"); q.add_argument("--symbol"); q.set_defaults(func=cmd_scan)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
