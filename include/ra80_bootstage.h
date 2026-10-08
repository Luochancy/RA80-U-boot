/* SPDX-License-Identifier: GPL-2.0+ */
#ifndef __RA80_BOOTSTAGE_H
#define __RA80_BOOTSTAGE_H
/* One owner per boundary. Raw/early writes need no timer, FDT or logging.
 * The link profile uses a BSS latch only after main_loop is reached.
 * bit0=System yellow, bit1=System white, bit2=Internet yellow, bit3=Internet white.
 */
#define RA80_STAGE_HANDOFF 1
#define RA80_STAGE_RESET 2
#define RA80_STAGE_CRT0 3
#define RA80_STAGE_GD 4
#define RA80_STAGE_FDT 5
#define RA80_STAGE_FDT_READY 6
#define RA80_STAGE_CONSOLE 7
#define RA80_STAGE_RELOC 8
#define RA80_STAGE_RUNTIME 9
#define RA80_STAGE_CACHES_READY 10
#define RA80_STAGE_MAIN 11
#define RA80_STAGE_ETH_BOARD 12
#define RA80_STAGE_GMAC 13
#define RA80_STAGE_LINK 14
#define RA80_STAGE_HTTP 15

/* Runtime-focus profile: codes 1/2 are handoff/reset, 3..F are below.
 * Pink means both calibrated yellow and white LED channels are on. */
#define RA80_RT_CACHES 3
#define RA80_RT_MALLOC 4
#define RA80_RT_MALLOC_READY 5
#define RA80_RT_BOARD 6
#define RA80_RT_SMEM 7
#define RA80_RT_AUTH 8
#define RA80_RT_BOARD_READY 9
#define RA80_RT_NAND 10
#define RA80_RT_ENV 11
#define RA80_RT_ENV_READY 12
#define RA80_RT_LATE 13
#define RA80_RT_LATE_READY 14
#define RA80_RT_MAIN 15

/* Ordinals describe progress, not the numerical order of the raw lamp code. */
#define RA80_NET_MAIN 1
#define RA80_NET_HTTP_CALL 2
#define RA80_NET_HTTP_ENTRY 3
#define RA80_NET_NET_READY 4
#define RA80_NET_LWIP_RETURN 5
#define RA80_NET_HTTP_RETURN 6
#define RA80_NET_POLL 7
#define RA80_NET_LINK_CHECK 8
#define RA80_NET_LINK_RETURN 9
#define RA80_NET_ETH_INIT 10
#define RA80_NET_PHY_RETURN 11
#define RA80_NET_RESET 12
#define RA80_NET_RESET_RETURN 13
#define RA80_NET_ACTIVE 14

#ifdef __ASSEMBLY__
#ifdef CONFIG_IPQ5018_XIAOMI_RA80
/* Only r10-r12 are clobbered; preserve boot arguments, SP, LR and r9 (GD).
 * MOVW zero-extends: every new address must also receive MOVT. */
.macro ra80_stage_gpio low, bit, code
 movw r10, #\low
 movt r10, #0x0101
 mov r12, #((((\code) >> (\bit)) & 1) << 1)
 str r12, [r10, #4]
 movw r11, #0x2c1
 str r11, [r10]
.endm
.macro ra80_stage code
#if defined(CONFIG_RA80_RUNTIME_DIAGNOSTICS) || defined(CONFIG_RA80_LINK_DIAGNOSTICS)
 .if \code == RA80_STAGE_RESET
#endif
 ra80_stage_gpio 0x1000, 0, \code
 ra80_stage_gpio 0x3000, 1, \code
 ra80_stage_gpio 0x4000, 2, \code
 ra80_stage_gpio 0x6000, 3, \code
 dsb sy
#if defined(CONFIG_RA80_RUNTIME_DIAGNOSTICS) || defined(CONFIG_RA80_LINK_DIAGNOSTICS)
 .endif
#endif
.endm
#else
.macro ra80_stage code
.endm
#endif
#else
#ifdef CONFIG_IPQ5018_XIAOMI_RA80
#include <asm/io.h>
int ra80_ram_test_active(void);
static inline void ra80_stage_gpio_write(unsigned long addr, unsigned int on)
{
 writel(on ? 2 : 0, (void *) (addr + 4));
 writel(0x2c1, (void *)addr);
}
static inline void ra80_stage_raw(unsigned int code)
{
 ra80_stage_gpio_write(0x01011000, code & 1);
 ra80_stage_gpio_write(0x01013000, code & 2);
 ra80_stage_gpio_write(0x01014000, code & 4);
 ra80_stage_gpio_write(0x01016000, code & 8);
 asm volatile("dsb sy" : : : "memory");
}
#ifdef CONFIG_RA80_LINK_DIAGNOSTICS
extern unsigned int ra80_link_furthest;
#endif
static inline void ra80_net_stage(unsigned int ordinal, unsigned int code)
{
#ifdef CONFIG_RA80_LINK_DIAGNOSTICS
 if (ordinal <= ra80_link_furthest)
  return;
 ra80_link_furthest = ordinal;
 ra80_stage_raw(code);
#else
 (void)ordinal;
 (void)code;
#endif
}
static inline void ra80_bootstage(unsigned int code)
{
#ifdef CONFIG_RA80_LINK_DIAGNOSTICS
 if (code == RA80_STAGE_MAIN)
  ra80_net_stage(RA80_NET_MAIN, 11);
 else if (code == RA80_STAGE_LINK)
  ra80_net_stage(RA80_NET_HTTP_CALL, 14);
 else if (code == RA80_STAGE_HTTP)
  ra80_net_stage(RA80_NET_ACTIVE, 15);
#elif !defined(CONFIG_RA80_RUNTIME_DIAGNOSTICS)
 ra80_stage_raw(code);
#else
 (void)code;
#endif
}
static inline void ra80_runtime_stage(unsigned int code)
{
#ifdef CONFIG_RA80_RUNTIME_DIAGNOSTICS
 ra80_stage_raw(code);
#else
 (void)code;
#endif
}
#else
static inline void ra80_net_stage(unsigned int ordinal, unsigned int code) { (void)ordinal; (void)code; }
static inline int ra80_ram_test_active(void) { return 0; }
static inline void ra80_bootstage(unsigned int code) { (void)code; }
static inline void ra80_runtime_stage(unsigned int code) { (void)code; }
#endif
#endif
#endif
