# RA80 RAM-only startup-path review

Baseline: xiaomi-ra80 506331c4e6d345b40a3b3cad4a3b79a67ba46320.
Evidence: stock RA80-V1 DTB, successful reversible stage/restore log, calibrated
GPIO17/19/20/22, and the user's counted-entry observations with no network access.

## What the evidence proves

The module relocation error was resolved in the matching QSDK GCC5.5 module ABI;
successful RAM staging/restore does not prove an executable U-Boot has initialized.
The latest counted-entry sequence proves reset, parameter return and CPU setup
were reached before _main. It does not prove FDT, DRAM, caches or Ethernet ran.
PC carrier remaining up does not prove packets can reach the CPU.
Actions run 37815421283 established a definite memory-layout failure in the
reviewed configuration: __bss_end exceeds 0x4aa00000. CRT0 clears BSS before
board_init_f, so this crosses the stock U-Boot reservation even before Ethernet.
The exact prior tested payload (506331c, SHA256
527f8ef25677338c32784da2210b14382b1d27feb8ef6b8ea45988fa42e48bc5)
also contains the CRT0 LDR/LDR/MOV/CMP/STRLO/ADDLO/BLO clearing loop, with literal
BSS start/end 0x4a97eb3c / 0x4aa376c4. It clears 0x376c4 bytes beyond the
U-Boot reservation into the stock SBL region, before board_init_f. This directly
establishes the defect in the user's tested binary, not just a new source build.
It is a plausible contributor to the observed partial boot; hardware confirmation
after the correction is still required. Whether access protection faults at the
boundary is not established by the available logs.

## Definite defects corrected

The generic lwIP options reserve a 512 KiB static heap plus 64 packet buffers
and 512 TCP segments. Combined with the image and other BSS, the RA80 layout
fails the stock reserved-window check. RA80 now uses a 128 KiB heap, 16 packet
buffers, 128 TCP segments and 8-MSS windows, retaining the larger defaults for
other targets. CI must prove the entire BSS/page-table/copied-DTB fits.
The old lwIP configuration explicitly disables ICMP, and its trimmed source
omits the ICMP implementation. Thus ping is not a valid success criterion for
that old HTTP stack. The missing upstream ICMP sources/headers are restored and
enabled only for RA80, making ping useful when ARP and the data path work.
This ICMP defect alone does not explain an unreachable HTTP page.

The earlier assembly lost the high GPIO address bits after MOVW at subsequent
pins. 506331c restored MOVT for every address. This patch keeps independent
MOVW/MOVT pairs and verifies the actual emitted stores, not only source strings.
Repeated colour codes, counted pulse loops and later LED initialization destroyed
stage identity. They are replaced by unique forward boundaries with no diagnostic
delays. LED initialization preserves the current stage.
Payload bounds previously allowed 2 MiB from 0x4a920000; only 0xe0000 bytes remain
before the stock reserved U-Boot region ends at 0x4aa00000. Both modules and the
generator now enforce that limit; CI additionally checks BSS/page-table/control-DTB.
Armed RAM tests now bypass preboot, automatic TFTP update, boot delay and autoboot.
HTTP startup failure halts with the last stage instead of entering ordinary boot.
The diagnostic mode survives marker consumption and rejects HTTP upgrades and
web terminal commands. Normal unarmed boot keeps its previous control flow.

## Paths reviewed

Linux module: embedded payload hash, stock vectors, kernel symbol/first-word
fingerprints, watchdog fingerprint, backup, write/readback, marker, SMP stop and
raw restart. The existing raw restart mechanism is preserved; instruction-word
fingerprints are not proof of the entire kernel implementation or IRQ/DMA quiescence.
U-Boot: reset/save_boot_params/cpu_init_cp15/_main, initial stack/GD, BSS clearing,
board_init_f, SMEM/control-FDT decompression and selection, DRAM/layout reservation,
non-relocating CRT0 transition, board_init_r/cache/malloc/storage/environment,
main_loop, board_eth_init, GMAC/MDIO/PHY/switch setup, HTTP/lwIP poll and eth_init.
This is a review of the complete relevant startup path, not every unrelated
architecture and flash command in the U-Boot repository.

## Memory and DTB checks

Stock memory is 0x40000000..0x50000000 (256 MiB). U-Boot reserved region is
0x4a800000..0x4aa00000, followed by SBL, SMEM and TZ reservations.
The target uses CONFIG_IPQ_NO_RELOC. Main image starts at 0x4a920000.
The gzip combined-control-DTB scratch region begins at 0x4a8e0000, with the
temporary decompressor allocation below it; these are phase-dependent regions,
not by themselves evidence of simultaneous memory corruption.
reserve_mmu aligns after BSS and uses a 16 KiB ARM32 page table; copied FDT follows.
CI evaluates the actual link map and compressed FDT rather than guessed sizes.

Stock GPIO mux/reset and MDIO topology: MDIO0=0x88000/PHY7,
MDIO1=0x90000/PHY0..4, external MDIO GPIO36/37, switch reset GPIO26.
Stock external-switch CPU/LAN/WAN bitmaps are 0x40/0x0e/0x30.
Physical topology is 3 LAN + 1 WAN; switch bitmaps do not directly count chassis jacks.

## Remaining candidates, not confirmed causes

Stages 4..A distinguish BSS/FDT/early runtime from Ethernet failure. C/D identify
board clocks/mux/reset versus MDIO/PHY/switch/GMAC registration. E identifies
device start/link/HTTP initialization. F proves the driver reported active, not
successful ARP or DMA packet transfer.
QCA8337's programmed CPU-port6 membership includes ports1..4 and separates port5.
This can explain interface-specific reachability, but cannot explain a halt before
Ethernet. Do not infer that all physical ports are enabled solely from ethrotate.
Switch reset timing, inherited peripheral/DMA state and GMAC link/DMA behavior
remain candidates if E/F is reached. No speculative VLAN/PLL/PHY change is made
without locating the failing phase.

## Validation and practical limits

Actions builds real U-Boot and stock-kernel modules, rejects R_ARM_REL32, requires
.core.plt/.init.plt and GCC5.5 metadata, and checks forbidden flash imports.
verify_bootstages.py decodes four straight-line ARM blocks (2/3/4/8), verifies
every GPIO configuration/output store and entry branch, and validates actual
payload/BSS/page-table/control-FDT bounds. Source stage ownership is checked too.
Static verification cannot demonstrate physical RAM boot or network reachability.
A fixed final code from one hardware test is needed to identify the current halt.
