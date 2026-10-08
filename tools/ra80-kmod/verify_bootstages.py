#!/usr/bin/env python3
"""Validate the emitted ARM stage stores and RA80 reserved-RAM layout."""
import re
import struct
import sys
import zlib
from pathlib import Path

def verify_source():
    root = Path(__file__).resolve().parents[2]
    header = root / 'include/ra80_bootstage.h'
    if not header.exists():
        return
    definitions = dict(re.findall(r'^#define (RA80_STAGE_\w+) (\d+)$', header.read_text(), re.M))
    assert sorted(map(int, definitions.values())) == list(range(1, 16))
    owners = []
    paths = ['arch/arm/cpu/armv7/start.S', 'arch/arm/lib/crt0.S',
             'lib/fdtdec.c', 'common/board_f.c', 'common/board_r.c',
             'common/main.c', 'board/qca/arm/ipq5018/ipq5018.c',
             'drivers/net/ipq5018/ipq5018_gmac.c', 'net/httpd.c']
    for path in paths:
        source = (root/path).read_text()
        owners.extend(re.findall(r'(?:ra80_bootstage\(\s*|ra80_stage\s+)(RA80_STAGE_\w+)', source))
        assert 'ra80_entry_pulses' not in source
        assert 'ra80_debug_led_code' not in source
    assert sorted(owners) == sorted(set(definitions) - {'RA80_STAGE_HANDOFF'}), owners
    runtime_definitions = dict(re.findall(r'^#define (RA80_RT_\w+) (\d+)$', header.read_text(), re.M))
    assert sorted(map(int, runtime_definitions.values())) == list(range(3, 16))
    runtime_owners = []
    for path in ['common/board_r.c', 'common/main.c', 'board/qca/arm/common/board_init.c']:
        runtime_owners.extend(re.findall(r'ra80_runtime_stage\(\s*(RA80_RT_\w+)', (root/path).read_text()))
    assert sorted(runtime_owners) == sorted(runtime_definitions), runtime_owners
    module = (root/'tools/ra80-kmod/ra80_ramboot_full.c').read_text()
    assert re.findall(r'ra80_handoff_led\(([^)]*)\);', module[module.index('static int __init ra80_ramboot_full_init'):]) == ['1']
    assert re.search(r'#define RA80_MAX_PAYLOAD_LEN\s+0x000e0000UL', module)
    driver = (root/'drivers/mtd/nand/qpic_nand.c').read_text()
    assert driver.count('if (ra80_ram_test_active())') == 2
    environment = (root/'common/env_common.c').read_text()
    assert re.findall(r'if \(!ra80_ram_test_active\(\)\)\s+saveenv\(\);', environment).__len__() == 2
    main = (root/'common/main.c').read_text()
    assert re.search(r'return ra80_ram_test_mode \|\|\s+ra80_ramboot_magic == RA80_RAMBOOT_MAGIC_ARMED;', main)
    cfg = (root/'include/configs/ipq5018.h').read_text()
    assert '#ifndef CONFIG_IPQ5018_XIAOMI_RA80\n#define CONFIG_QSPI_SERIAL_TRAINING\n#endif' in cfg
    print('PASS: RAM marker protects early and late NAND writes; no automatic env save')
    print('PASS: each U-Boot boundary has one stage owner; one fixed Linux handoff code')

verify_source()
if sys.argv[1:] == ['--source-only']:
    sys.exit(0)

BASE, LIMIT = 0x4A920000, 0x4AA00000
blob = Path(sys.argv[1]).read_bytes()
linkmap = Path(sys.argv[2]).read_text()

def symbol(name):
    values = re.findall(r"^\s*(0x[0-9a-fA-F]+)\s+" + re.escape(name) + r"\s*$", linkmap, re.M)
    assert values, "missing map symbol: " + name
    assert len(set(values)) == 1, "ambiguous map symbol: " + name
    return int(values[0], 16)

assert b'training_block_64' not in linkmap.encode(), 'NAND training data compiled into RA80'
assert b'0:TRAINING' not in blob, 'NAND training partition path compiled into RA80'
print('PASS: automatic NAND serial-training code/data absent from payload')
assert len(blob) <= LIMIT - BASE, "payload exceeds reserved window"
assert symbol('_start') == BASE
assert symbol('__bss_start') >= BASE
bss_end = symbol('__bss_end')
print("linked_bss_start=%08x linked_bss_end=%08x reserved_end=%08x" % (symbol("__bss_start"), bss_end, LIMIT), flush=True)
assert bss_end <= LIMIT, "BSS exceeds reserved window"
pgtable = (bss_end + 0xFFFF) & ~0xFFFF
# This target has no ARMv7 LPAE: reserve_mmu uses a 16 KiB table.
config = Path(sys.argv[3] if len(sys.argv) > 3 else '.config').read_text()
assert 'CONFIG_ARMV7_LPAE=y' not in config
dtb_base = pgtable + 0x4000 + 4

# Validate the exact linked gzip member and combined table, not a guessed FDT.
gzip_begin = symbol('__dtb_blob_begin') - BASE
gzip_end = symbol('__dtb_blob_end') - BASE
assert 0 <= gzip_begin < gzip_end <= len(blob)
assert BASE + gzip_end <= symbol('__bss_start'), 'compressed FDT would be erased by BSS clearing'
combined = zlib.decompress(blob[gzip_begin:gzip_end], 16 + zlib.MAX_WBITS)
assert len(combined) <= 0x40000
count = struct.unpack_from('<I', combined)[0]
assert count == 1, 'RA80 target must contain one control DTB'
machid, address = struct.unpack_from('<II', combined, 4)
fdt_offset = address - 0x4A8E0000
assert 12 <= fdt_offset < len(combined)
magic, size = struct.unpack_from('>II', combined, fdt_offset)
assert magic == 0xD00DFEED
assert fdt_offset + size <= len(combined)
copy_size = len(combined) - fdt_offset
assert dtb_base + copy_size <= LIMIT, 'page table / copied control DTB exceeds reserved RAM'

# General profile emits stages 2,3,4,8; runtime focus emits only reset 2.
# Stackless blocks must contain no branch,
# delay, SP/GD/argument clobber or out-of-range store in any block.
signature = struct.pack('<II', 0xE301A000, 0xE340A101)
positions = [i for i in range(0, len(blob)-100, 4) if blob[i:i+8] == signature]
codes = []
for offset in positions:
    words = struct.unpack_from('<25I', blob, offset)
    code = 0
    for bit, low in enumerate((0x1000, 0x3000, 0x4000, 0x6000)):
        movw, movt, output, store_out, config_value, store_cfg = words[bit*6:bit*6+6]
        expected_movw = 0xE300A000 | ((low & 0xF000) << 4) | (low & 0xFFF)
        assert movw == expected_movw and movt == 0xE340A101
        assert output in (0xE3A0C000, 0xE3A0C002)
        assert store_out == 0xE58AC004
        assert config_value == 0xE300B2C1 and store_cfg == 0xE58AB000
        code |= ((output & 2) >> 1) << bit
    assert words[-1] == 0xF57FF04F, 'missing DSB SY'
    codes.append(code)
expected_codes = [2] if 'CONFIG_RA80_RUNTIME_DIAGNOSTICS=y' in config else [2, 3, 4, 8]
assert sorted(codes) == expected_codes, codes
reset_word = struct.unpack_from('<I', blob)[0]
assert reset_word >> 24 == 0xEA
reset_offset = 8 + ((reset_word & 0xFFFFFF) << 2)
assert reset_offset == positions[codes.index(2)]

print('PASS: %d straight-line ARM blocks; stage codes %s; all %d TLMM stores verified' % (len(codes), codes, len(codes)*8))
print('PASS: no stage delay loops or calls; boot arguments, SP, LR and GD untouched')
print('payload_end=%08x bss_end=%08x pgtable=%08x dtb_base=%08x dtb_end=%08x' %
      (BASE + len(blob), bss_end, pgtable, dtb_base, dtb_base + copy_size))
print('control_dtb_machid=%08x control_dtb_size=%d reserved_end=%08x' % (machid, size, LIMIT))
