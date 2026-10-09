# RA80 RAM-only startup-path review

## RAM initramfs and Web reset enabled after hardware HTTP success

The user confirmed F and functioning HTTP pages for d54a758, then explicitly
requested enabling memory boot and Web reset. RAM mode now allows only the
INITRAMFS upload type and the exact reset command. Both dispatch directly to
do_bootm/do_reset without entering Hush (the direct RAM network entry bypasses
CLI initialization). Flash update types and arbitrary terminal commands remain
blocked. Upload header/size/RAM-bound/FIT-node checks precede RAM copying.
Returning from a kernel handoff is treated as failure, so HTTP does not execute
an automatic reset after failed RAM boot.

The original board FDT setup generated MTD partitions and invoked NAND/QPIC
fixups. RAM mode now returns through a separate checked board-tree fixup before
these calls. The Linux DTB must identify Xiaomi AX3000/RA80; memory is updated
to actual DRAM, flash-related chosen arguments removed/replaced, NAND and MMC
controllers disabled, and Wi-Fi/WCSS disabled because ART is unavailable.
Only Ethernet nvmem MAC dependencies are removed; unrelated calibration cells
are preserved. Generic Ethernet fixup still supplies the temporary MACs.
These restrictions apply to this trusted initramfs test; they do not sandbox a
malicious kernel capable of direct MMIO. No flash installation is authorized.

Candidate inspected locally: crypt0nX/openwrt-xiaomi-ax3000 release v1.0.1,
initramfs-uImage.itb SHA256
b507a7981582cfdf9f04396bf82eec5b2589d9ff60fb9b9dc3812833d8fa6322.
FIT size 16051344, ARM64 Linux 6.12.62, LZMA kernel size 16022043,
expanded kernel 26617864 bytes at entry/load 0x41000000, ending 0x42962808;
FIT copied at 0x44000000; U-Boot reserved 0x4a800000..0x4aa00000.
Configuration config@mp02.1. DTB flash controller /soc@0/spi@79b0000 was
enabled with flash root arguments; these are disabled by the RAM board fixup
after FIT verification, rather than modifying FIT bytes/hashes.
Host tests extract production gate/reset/FDT functions and use real libfdt.
Real ARM64 kernel handoff still requires hardware testing; HTTP/F alone does
not prove a kernel boot.

## Steady C follow-up (after direct RAM entry)

The user reached C with the direct-network payload. C is emitted after
ipq5018_phy_link_update returns, before testing its result; D is emitted inside
DMA reset. A steady C establishes at least one PHY update return and no observed
DMA-reset entry. It does not distinguish no cable from failed MDIO, missing PHY
callbacks, or failed external-switch initialization. The furthest-stage latch
can also hide where a later retry is currently executing.

Source defects corrected in this revision:

- Common MDIO had 1000 tight reads with no delay, despite IPQ_MDIO_DELAY=5.
  It now allows 5 us before each sample, a bounded nominal 5 ms wait plus MMIO
  overhead, accepting completion on the last sample.
- S17 switch reset and global initialization allowed only ten polls separated
  by 10 us and rejected the tenth even if ready. Both phases now accept final
  completion and allow 1000 polls separated by 1 ms. Transport errors propagate
  through paging, both halves of register access, reset, and configuration.
  Page selection receives a 5 us settling delay.
- RA80 QCA8337 setup incorrectly accessed debug addresses 0x3d and 0x0b as
  Clause 22 register numbers. They now use address/data registers 0x1d/0x1e.
  Every setup transaction is checked; PHY BMCR reset is polled for at most
  600 ms of explicit delays before link reads.
- For RA80's DT-declared external switch, an invalid first PHY ID no longer
  bypasses switch initialization altogether. This is restricted to RA80 and
  still requires successful switch transport/reset/configuration before the
  initialized flag is set. Other targets retain their original selection.
- External MDIO GPIO36/37 now use 8 mA drive with pull-up/function 1, matching
  the supplied stock DTB. GPIO26 gets 100 ms after reset deassertion before
  subsequent MDIO access.

Primary reference for indirect debug addressing and page settling:
https://github.com/openwrt/openwrt/blob/master/target/linux/generic/files/drivers/net/phy/ar8216.h
https://github.com/openwrt/openwrt/blob/master/target/linux/generic/files/drivers/net/phy/ar8216.c
Its PHY initialization uses millisecond reset polling; the S17 switch-core
timeout here is a conservative bounded policy, not a claimed datasheet value.
The new test_switch_init.py extracts production functions and injects late
completion, final-sample success, permanent busy and read/write failures.
These are proven source defects; which contributed to this router's C remains
unconfirmed until the new payload is tested. Network packet delivery is not
established by host tests, LED progress or carrier alone. All NAND/RAM guards
and all sixteen physical lamp codes remain unchanged.

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

## c200032 实机仍E：将HTTP/链路区间改为单调固定码

实机仍E，只能确定main_loop网卡注册已经返回；旧E到F包含run_command派发、HttpdStart/net_init/lwIP、CLI轮询、链路更新和DMA初始化。复位上限修复通过假MMIO测试，但不能据此断言实机走到复位。

CONFIG_RA80_LINK_DIAGNOSTICS独立于运行期细分，复用早期已验证位置的颜色，保留B/E/F定义。新增每个真实调用前后边界：HttpdStart入口3、net_init返回4、lwIP返回/运行标志5、命令返回6、有效轮询7、链路检测前8/后9、驱动init入口A、PHY返回C、复位入口D/返回0。F仍只代表轮询观察网卡active。代码0全灭是明确的复位调用返回边界，不保证成功；C也不保证PHY成功。

LED原始四GPIO映射不变。early ARM只写reset2，不访问BSS；运行期锁存在BSS清零完成后使用。进度使用独立1..14序号，保留最深序号；重试不会重写同一颜色或退回之前颜色。链路检测内部调用eth_init可跳过后续浅层标记，这是保留更精确位置的预期行为。测试提取实际锁存函数，遍历全部阶段并重放所有较浅阶段，验证保持最终F与中间全灭；提取实际复位/init函数的假MMIO测试继续验证超时不启动DMA。源码门禁检查16种物理码唯一、每个阶段只有一处写入所有者；二进制门禁检查reset ARM直线块及RAM/DTB边界。

本次未添加硬件修复假设。新E持续意味着还未到HttpdStart入口，下一步应审查命令派发；新A/C/D/0分别缩小PHY与复位范围。不能继续把所有E都归为网卡未起，也不能把灯跳变视为系统完整可用。

## 0f85c5a MD5匹配、实机停B：审查并修复主循环入口

B意味着main_loop已到达，但尚未更新E。B到E包含cli_init、串口printf、环境设置和eth_initialize。源码include/configs/ipq5018.h无条件定义CONFIG_SYS_HUSH_PARSER，虽然.config不含该项，仍会编译Hush；此前仅据.config认定无Hush的推断不成立。u_boot_hush_start分配top_vars后不检查NULL就写字段，是可见故障风险，但没有实机堆状态证明这次必然是malloc失败。CONFIG_IPQ_ETH_INIT_DEFER也在配置头中启用，因此initr_net没有提前注册，本次main中的eth_initialize是首次注册，不能误称二次注册。

新RAM入口从main_loop的B后立即分支，在CLI/Hush/日志之前禁用控制台，清RAM marker但保留mode锁存，设置RAM IP与轮换环境，注册一次，直接调用HttpdStart，随后独立httpd_poll无限循环。不依赖CLI等待字符时插入的poll，也不经过run_command。正常未标记启动保留CLI、按键和自动启动路径。环境设置失败、设备数<=0或运行标志未设置只停止，不启动原厂内核或写入闪存。

board_eth_init还会在ipq_gmac_init后无条件调用board_update_caldata。控制FDT若无slot_Id，原路径打印后返回；若有slot_Id则从ART读校准数据并经SCM修改XO覆盖寄存器。之前只保护MAC读取，遗漏这条校准读取。RAM模式现在跳过调用，并在校准入口与get_eth_caldata读助手最前面再加保护；不发起ART/NAND读取或校准SCM，保留Linux建立的状态。该缺口确实存在，但B不能证明它是本次唯一故障。

新固定阶段仍保留B/E/F与C/D/0，3..7标记直接入口、环境完成、board_eth_init、ipq_gmac_init及其返回；8/9为HTTP入口/lwIP返回，A为有效网络轮询。16种物理组合唯一，序号锁存仍禁止重试倒退。没有插入延时。假网络测试提取实际RAM入口，验证控制台关闭、只注册一次、直接持续轮询，以及环境/无设备/HTTP失败不越过安全停止点。GMAC未初始化局部指针清理与设备数组边界同时修正。
