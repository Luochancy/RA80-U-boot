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

## Follow-up: confirmed stop at general stage A

The user confirmed only the white channels of both lamps are on (mixed channels
look pink). In the d48f4be profile this is stage A, emitted after enable_caches
returns and before initr_reloc_global_data/malloc/DM/board/storage/environment.
It is not evidence that board_eth_init or main_loop has been reached. The Windows
unreachable reply is from the PC 192.168.1.2, not the router.

Source review also rules out a concrete UART TX wait or secondary CPU restart
loop in the IPQ5018 implementation: these hooks resolve to empty weak defaults.
SMEM configuration, board authentication SCM, NAND/environment reads and runtime
allocation/DM remain distinct possible stopping points; none is declared the
unique cause without finer observations.

CONFIG_RA80_RUNTIME_DIAGNOSTICS enables a separate fixed-code profile. The
already-observed early path holds code2. Codes3..F uniquely bracket cache return,
malloc, DM, GIC, SMEM, auth SCM, board ready, NAND, env, late board and main entry.
This profile preserves the actual startup calls; it does not bypass a suspected
failure or change PHY/VLAN settings. General network markers are suppressed in
this build so they cannot overwrite/reuse runtime codes. F means main entry only.
The binary gate expects one verified ARM reset block for this profile, while the
general profile retains four blocks. Both profiles check RAM bounds and gzip
placement before BSS, and every stage definition has one source owner.

## RAM 路径的额外写保护

审查发现 QPIC serial training 会查找0:TRAINING、擦除块并写入校准数据；旧构建含training_block_64，不能仅凭模块没有MTD导入就宣称整条U-Boot路径不会写闪存。此发现不证明用户之前实际发生了擦写：分区缺失、初始化提前停止都可能使它未执行。

RA80目标现已从编译期禁用CONFIG_QSPI_SERIAL_TRAINING，并固定反馈时钟/200MHz输入的保守配置。验证脚本要求链接图无training_block_64且payload无0:TRAINING字符串。

env_import的坏CRC/解密失败原先会自动saveenv。RAM标记现从运行期初始化之前生效，禁止这两条自动保存路径，并在qpic_nand_write_page和qpic_nand_blk_erase排队硬件操作之前拒绝RAM模式写/擦请求。main_loop消费标记后模式继续锁存。正常非RAM启动仍可手动保存环境；RA80自动训练对所有RA80构建均禁用。

## 26d78f5 实机双白：存储初始化区间阻塞

用户确认26d78f5模块仍停在A（两灯仅白珠亮）。这一版A位于initr_nand入口，且早于puts("NAND: ")；B位于initr_env入口。因此确证范围是这两个入口之间，尚未走到board_eth_init/ipq_gmac_init/HTTP。不能把A解释为网络已启动，也不能确定是UART输出、QPIC/BAM初始化还是NAND探测中的具体指令。

RAM网络模式现直接在initr_nand最前面返回，不发起QPIC/BAM/NAND初始化；initr_env只建立默认RAM环境；get_eth_mac_address从RAM模式生成本地管理临时单播MAC，对set_ethmac_addr与GMAC的两次调用均生效，避免回头读取ART。board_late_init跳过闪存分区与保护处理，保留SoC变量和网络相关准备。HTTP about信息仅在nand_info.size/writesize非零时读芯片，跳过初始化后其BSS值为0。网页升级及命令继续拦截。

此改动解决RAM测试对NAND初始化成功的依赖；冷启动NAND驱动仍需独立验证。BAM等待存在外层循环重置超时起点的问题，但没有硬件日志证明本次停在该循环，故本次不修改共享BAM驱动或猜测重置寄存器。

本版关闭CONFIG_RA80_RUNTIME_DIAGNOSTICS，完整码表恢复：B=main_loop、C=board_eth_init、D=GMAC、E=网卡注册返回并开始HTTP、F=HTTP轮询观察到eth_is_active。F仍不证明ARP/ICMP/HTTP收发正常。

## b6b61b8 实机停 E：灯序与链路路径复核

用户确认最终1粉、2白。与其led_test校准一致：GPIO17=System黄、19=System白、20=Internet黄、22=Internet白。B=11(1011b)点17/19/22，E=14(1110b)点19/20/22。写寄存器顺序先System两珠再Internet两珠；不能按bit0是Internet推断颜色。最终E证明主循环中eth_initialize已返回、即将运行httpd；F仅在failsafe_httpd_poll观察到eth_is_active后设置。HTTP起始分支对RA80不调用传统led_on/off，未进入上传时不会被上传闪灯覆盖。

审查发现可独立修复的缺陷：ipq_mac_reset无上限等待DMA SRST自清；返回失败无法驱动设备轮换。现在10000次10us读回失败返回-ETIMEDOUT，并由ipq_eth_init传播，后续MAC/DMA配置不执行。switch link读取用uint16截断MDIO返回的-ETIMEDOUT，可能产生假的LINK_UP位；现在保留int并拒绝负值和0xffff。

HTTP初次eth_init失败后只有链路变化检测会触发后续尝试；链路稳定但初次初始化失败可能长停E。RAM测试现在每次失败完成至少1秒后重试，轮换成功时同步net_ethaddr和lwIP hwaddr。其它启动模式保持原重试方式。固定灯码定义未改，不借诊断闪烁重用码。

CI使用真实函数源体配假MMIO/MDIO测试：复位永久置位必须返回且不能启动DMA、健康/边界复位成功、无链路不发起复位、MDIO负错误和全1值不算链路。没有实机寄存器日志，不能认定当前E必定来自某一个缺陷。
