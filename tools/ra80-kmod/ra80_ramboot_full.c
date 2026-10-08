/*
 * ra80_ramboot_full.c - guarded one-shot RAM-only U-Boot handoff for RA80 V1
 *
 * The module validates the exact stock kernel fingerprint, backs up the stock
 * U-Boot RAM window, stages and byte-verifies the new U-Boot, arms its RAM-only
 * Webfailsafe marker, disables the KPSS watchdog, stops the secondary CPU and
 * jumps to the staged image.  No NAND, MTD, UBI, or APPSBL operation exists.
 * Every failure before watchdog disable restores the stock RAM byte-for-byte.
 */

#include <linux/delay.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/types.h>
#include <linux/vmalloc.h>

#include "ra80_payload.inc"

#define RA80_UBOOT_PHYS                 0x4a920000UL
#define RA80_WATCHDOG_CTRL_PHYS         0x0b017008UL
#define RA80_MIN_PAYLOAD_LEN            (64UL * 1024UL)
#define RA80_MAX_PAYLOAD_LEN            (2UL * 1024UL * 1024UL)
#define RA80_STOCK_VECTOR0              0xea0000b8U
#define RA80_VECTOR_LITERAL             0xe59ff014U
#define RA80_EXPECTED_SOFT_RESTART      0x81219980UL
#define RA80_EXPECTED_RAW_RESTART       0x81219958UL
#define RA80_EXPECTED_SMP_STOP          0x8121d0a4UL
#define RA80_SOFT_RESTART_WORD0         0xe59f3028U
#define RA80_RAW_RESTART_WORD0          0xe92d4010U
#define RA80_SMP_STOP_WORD0             0xe59f3098U
#define RA80_EXPECTED_WATCHDOG_CTRL     0x00000001U
#define FNV1A_OFFSET                    0x811c9dc5U
#define FNV1A_PRIME                     0x01000193U

extern unsigned long kallsyms_lookup_name(const char *name);

typedef void (*ra80_smp_stop_fn_t)(void);
typedef void (*ra80_raw_restart_fn_t)(unsigned long, bool);

static bool led_test;
module_param(led_test, bool, 0444);
MODULE_PARM_DESC(led_test, "Reversible raw GPIO LED calibration only; no payload or handoff");

static bool execute;
module_param(execute, bool, 0444);
MODULE_PARM_DESC(execute, "Must be 1 to perform the guarded RAM-only handoff");

static unsigned int delay_ms = 3000;
module_param(delay_ms, uint, 0444);
MODULE_PARM_DESC(delay_ms, "Final pre-handoff delay in milliseconds (1000..10000)");

static void __iomem *ra80_uboot_map;
static void __iomem *ra80_watchdog_map;
static void __iomem *ra80_led_map;
static const unsigned int ra80_led_gpio[4] = { 17, 19, 20, 22 };
static u32 ra80_led_saved_cfg[4], ra80_led_saved_io[4];
static bool ra80_led_saved;

static void ra80_handoff_led(unsigned int code)
{
	unsigned int i;
	for (i = 0; i < 4; i++) {
		u8 __iomem *p = (u8 __iomem *)ra80_led_map +
				ra80_led_gpio[i] * 0x1000;
		writel((code & (1U << i)) ? 2 : 0, p + 4);
		writel(0x2c1, p); /* GPIO, 8mA, output enabled, pull down. */
	}
	mb();
}

static u8 *ra80_stock_backup;
static u32 ra80_stock_fnv1a;
static bool ra80_payload_written;

static u32 fnv1a_buffer(const u8 *buffer, size_t length)
{
	u32 hash = FNV1A_OFFSET;
	size_t i;

	for (i = 0; i < length; i++) {
		hash ^= buffer[i];
		hash *= FNV1A_PRIME;
	}

	return hash;
}

static u32 fnv1a_io(const u8 __iomem *buffer, size_t length)
{
	u32 hash = FNV1A_OFFSET;
	size_t i;

	for (i = 0; i < length; i++) {
		hash ^= readb(buffer + i);
		hash *= FNV1A_PRIME;
	}

	return hash;
}

static u32 payload_u32(size_t offset)
{
	return (u32)ra80_payload[offset] |
	       ((u32)ra80_payload[offset + 1] << 8) |
	       ((u32)ra80_payload[offset + 2] << 16) |
	       ((u32)ra80_payload[offset + 3] << 24);
}

static bool stock_vector_matches(void)
{
	u8 __iomem *p = (u8 __iomem *)ra80_uboot_map;

	return readl(p + 0x00) == RA80_STOCK_VECTOR0 &&
	       readl(p + 0x04) == RA80_VECTOR_LITERAL &&
	       readl(p + 0x08) == RA80_VECTOR_LITERAL &&
	       readl(p + 0x0c) == RA80_VECTOR_LITERAL;
}

static int verify_payload(void)
{
	u8 __iomem *p = (u8 __iomem *)ra80_uboot_map;
	u32 hash = FNV1A_OFFSET;
	size_t i;

	for (i = 0; i < RA80_PAYLOAD_LEN; i++) {
		u8 actual = readb(p + i);

		if (actual != ra80_payload[i]) {
			pr_err("ra80_ramboot_full: verify mismatch at 0x%zx expected=%02x actual=%02x\n",
			       i, ra80_payload[i], actual);
			return -EIO;
		}
		hash ^= actual;
		hash *= FNV1A_PRIME;
	}

	if (hash != RA80_PAYLOAD_FNV1A) {
		pr_err("ra80_ramboot_full: verify hash mismatch expected=%08x actual=%08x\n",
		       RA80_PAYLOAD_FNV1A, hash);
		return -EIO;
	}

	return 0;
}

static int restore_stock(void)
{
	u32 restored_hash;

	if (!ra80_uboot_map || !ra80_stock_backup || !ra80_payload_written)
		return 0;

	memcpy_toio(ra80_uboot_map, ra80_stock_backup, RA80_PAYLOAD_LEN);
	wmb();
	restored_hash = fnv1a_io((u8 __iomem *)ra80_uboot_map,
				  RA80_PAYLOAD_LEN);
	if (restored_hash != ra80_stock_fnv1a || !stock_vector_matches()) {
		pr_emerg("ra80_ramboot_full: STOCK RESTORE FAILED hash=%08x expected=%08x\n",
			 restored_hash, ra80_stock_fnv1a);
		return -EIO;
	}

	ra80_payload_written = false;
	pr_info("ra80_ramboot_full: stock RAM restored and verified fnv1a=%08x\n",
		restored_hash);
	return 0;
}

static void release_resources(void)
{
	if (ra80_led_map) {
		unsigned int i;
		if (ra80_led_saved)
			for (i = 0; i < 4; i++) {
				u8 __iomem *p = (u8 __iomem *)ra80_led_map +
						ra80_led_gpio[i] * 0x1000;
				writel(ra80_led_saved_io[i], p + 4);
				writel(ra80_led_saved_cfg[i], p);
			}
		mb();
		iounmap(ra80_led_map);
		ra80_led_map = NULL;
		ra80_led_saved = false;
	}
	if (ra80_watchdog_map) {
		iounmap(ra80_watchdog_map);
		ra80_watchdog_map = NULL;
	}
	if (ra80_uboot_map) {
		iounmap(ra80_uboot_map);
		ra80_uboot_map = NULL;
	}
	vfree(ra80_stock_backup);
	ra80_stock_backup = NULL;
}

static int fail_with_rollback(int error)
{
	if (restore_stock())
		pr_emerg("ra80_ramboot_full: automatic rollback verification failed\n");
	release_resources();
	return error;
}

/* Calibration writes only four LED GPIOs and restores both registers.
 * Raw values deliberately avoid assuming colour, wiring order or polarity. */
static int ra80_led_calibrate(void)
{
	static const unsigned int codes[] = { 0, 15, 1, 2, 4, 8 };
	unsigned int i;
	ra80_led_map = ioremap(0x01000000UL, 0x17000);
	if (!ra80_led_map)
		return -ENOMEM;
	for (i = 0; i < 4; i++) {
		u8 __iomem *p = (u8 __iomem *)ra80_led_map +
				ra80_led_gpio[i] * 0x1000;
		ra80_led_saved_cfg[i] = readl(p);
		ra80_led_saved_io[i] = readl(p + 4);
	}
	ra80_led_saved = true;
	pr_info("ra80_ramboot_full: LED TEST ONLY; no payload writes, watchdog changes or jump\n");
	for (i = 0; i < ARRAY_SIZE(codes); i++) {
		pr_info("ra80_ramboot_full: LED TEST raw code=%x GPIO17/19/20/22 hold=4000ms\n",
			codes[i]);
		ra80_handoff_led(codes[i]);
		msleep(4000);
	}
	release_resources();
	pr_info("ra80_ramboot_full: LED TEST registers restored\n");
	return 0;
}

static int __init ra80_ramboot_full_init(void)
{
	u8 __iomem *p;
	unsigned long soft_restart;
	unsigned long raw_restart;
	unsigned long smp_stop;
	ra80_smp_stop_fn_t stop_secondary;
	ra80_raw_restart_fn_t jump_to_ram;
	u32 payload_hash;
	u32 watchdog_value;
	u32 armed_hash;
	unsigned int remaining;
	int ret;

	if (led_test) {
		if (execute)
			return -EINVAL;
		return ra80_led_calibrate();
	}

	pr_emerg("ra80_ramboot_full: guarded FULL RAM HANDOFF requested\n");
	pr_emerg("ra80_ramboot_full: RAM ONLY; NO NAND/MTD/APPSBL writes\n");
	pr_info("ra80_ramboot_full: payload commit=%s len=%u sha256=%s\n",
		RA80_PAYLOAD_SOURCE_COMMIT, RA80_PAYLOAD_LEN,
		RA80_PAYLOAD_SHA256);

	if (!execute) {
		pr_err("ra80_ramboot_full: refusing without execute=1\n");
		return -EPERM;
	}
	if (delay_ms < 1000 || delay_ms > 10000) {
		pr_err("ra80_ramboot_full: delay_ms must be 1000..10000\n");
		return -EINVAL;
	}
	if (RA80_PAYLOAD_LEN < RA80_MIN_PAYLOAD_LEN ||
	    RA80_PAYLOAD_LEN > RA80_MAX_PAYLOAD_LEN ||
	    RA80_RAMBOOT_MAGIC_OFFSET + sizeof(u32) > RA80_PAYLOAD_LEN) {
		pr_err("ra80_ramboot_full: payload length/marker bounds invalid\n");
		return -EINVAL;
	}
	if ((payload_u32(0) & 0xff000000U) != 0xea000000U ||
	    payload_u32(4) != RA80_VECTOR_LITERAL ||
	    payload_u32(8) != RA80_VECTOR_LITERAL ||
	    payload_u32(12) != RA80_VECTOR_LITERAL ||
	    payload_u32(RA80_RAMBOOT_MAGIC_OFFSET) != RA80_RAMBOOT_MAGIC_GUARD) {
		pr_err("ra80_ramboot_full: embedded vectors or RAM marker guard invalid\n");
		return -EINVAL;
	}
	payload_hash = fnv1a_buffer(ra80_payload, RA80_PAYLOAD_LEN);
	if (payload_hash != RA80_PAYLOAD_FNV1A) {
		pr_err("ra80_ramboot_full: embedded payload hash mismatch expected=%08x actual=%08x\n",
		       RA80_PAYLOAD_FNV1A, payload_hash);
		return -EINVAL;
	}

	soft_restart = kallsyms_lookup_name("soft_restart");
	raw_restart = kallsyms_lookup_name("_soft_restart");
	smp_stop = kallsyms_lookup_name("smp_send_stop");
	if (soft_restart != RA80_EXPECTED_SOFT_RESTART ||
	    raw_restart != RA80_EXPECTED_RAW_RESTART ||
	    smp_stop != RA80_EXPECTED_SMP_STOP ||
	    *(volatile u32 *)soft_restart != RA80_SOFT_RESTART_WORD0 ||
	    *(volatile u32 *)raw_restart != RA80_RAW_RESTART_WORD0 ||
	    *(volatile u32 *)smp_stop != RA80_SMP_STOP_WORD0) {
		pr_err("ra80_ramboot_full: kernel fingerprint mismatch soft=%08lx/%08x raw=%08lx/%08x smp=%08lx/%08x\n",
		       soft_restart, soft_restart ? *(volatile u32 *)soft_restart : 0,
		       raw_restart, raw_restart ? *(volatile u32 *)raw_restart : 0,
		       smp_stop, smp_stop ? *(volatile u32 *)smp_stop : 0);
		return -EPERM;
	}

	ra80_watchdog_map = ioremap(RA80_WATCHDOG_CTRL_PHYS, sizeof(u32));
	if (!ra80_watchdog_map)
		return -ENOMEM;
	watchdog_value = readl(ra80_watchdog_map);
	if (watchdog_value != RA80_EXPECTED_WATCHDOG_CTRL) {
		pr_err("ra80_ramboot_full: watchdog fingerprint mismatch expected=%08x actual=%08x\n",
		       RA80_EXPECTED_WATCHDOG_CTRL, watchdog_value);
		release_resources();
		return -EPERM;
	}

	ra80_stock_backup = vmalloc(RA80_PAYLOAD_LEN);
	if (!ra80_stock_backup) {
		release_resources();
		return -ENOMEM;
	}
	ra80_uboot_map = ioremap(RA80_UBOOT_PHYS, RA80_PAYLOAD_LEN);
	if (!ra80_uboot_map) {
		release_resources();
		return -ENOMEM;
	}
	p = (u8 __iomem *)ra80_uboot_map;
	if (!stock_vector_matches()) {
		pr_err("ra80_ramboot_full: refusing non-stock RAM vectors %08x %08x %08x %08x\n",
		       readl(p), readl(p + 4), readl(p + 8), readl(p + 12));
		release_resources();
		return -EPERM;
	}

	memcpy_fromio(ra80_stock_backup, ra80_uboot_map, RA80_PAYLOAD_LEN);
	ra80_stock_fnv1a = fnv1a_buffer(ra80_stock_backup, RA80_PAYLOAD_LEN);
	pr_info("ra80_ramboot_full: stock backup complete fnv1a=%08x\n",
		ra80_stock_fnv1a);

	memcpy_toio(ra80_uboot_map, ra80_payload, RA80_PAYLOAD_LEN);
	wmb();
	ra80_payload_written = true;
	ret = verify_payload();
	if (ret)
		return fail_with_rollback(ret);

	writel(RA80_RAMBOOT_MAGIC_ARMED,
	       p + RA80_RAMBOOT_MAGIC_OFFSET);
	wmb();
	if (readl(p + RA80_RAMBOOT_MAGIC_OFFSET) != RA80_RAMBOOT_MAGIC_ARMED) {
		pr_err("ra80_ramboot_full: failed to arm RAM-only Webfailsafe marker\n");
		return fail_with_rollback(-EIO);
	}
	armed_hash = fnv1a_io(p, RA80_PAYLOAD_LEN);
	pr_emerg("ra80_ramboot_full: STAGE VERIFIED AND ARMED first=%08x marker_offset=0x%x fnv1a=%08x\n",
		 readl(p), RA80_RAMBOOT_MAGIC_OFFSET, armed_hash);
	pr_emerg("ra80_ramboot_full: PREFLIGHT PASS soft=%08lx raw=%08lx smp=%08lx watchdog=%08x\n",
		 soft_restart, raw_restart, smp_stop, watchdog_value);

	/* Save only the four LED registers; never touch Reset/Mesh/switch reset. */
	ra80_led_map = ioremap(0x01000000UL, 0x17000);
	if (!ra80_led_map)
		return fail_with_rollback(-ENOMEM);
	{
		unsigned int i;
		for (i = 0; i < 4; i++) {
			u8 __iomem *led = (u8 __iomem *)ra80_led_map +
					 ra80_led_gpio[i] * 0x1000;
			ra80_led_saved_cfg[i] = readl(led);
			ra80_led_saved_io[i] = readl(led + 4);
		}
		ra80_led_saved = true;
	}
	/* Separate Linux preparation from the U-Boot reset entry visually. */
	ra80_handoff_led(0);
	msleep(500);
	ra80_handoff_led(4); /* system off, network yellow */
	msleep(1000);
	ra80_handoff_led(8); /* system off, network blue */
	pr_emerg("ra80_ramboot_full: LED DIAG Linux countdown network blue\n");
	remaining = delay_ms;
	while (remaining > 0) {
		unsigned int slice = remaining > 1000 ? 1000 : remaining;

		pr_emerg("ra80_ramboot_full: handoff in %u ms\n", remaining);
		msleep(slice);
		remaining -= slice;
	}

	/* This is the last recoverable operation. */
	writel(0, ra80_watchdog_map);
	mb();
	if (readl(ra80_watchdog_map) != 0) {
		pr_err("ra80_ramboot_full: watchdog disable verification failed; rolling back\n");
		writel(RA80_EXPECTED_WATCHDOG_CTRL, ra80_watchdog_map);
		mb();
		if (readl(ra80_watchdog_map) != RA80_EXPECTED_WATCHDOG_CTRL)
			pr_emerg("ra80_ramboot_full: watchdog restore verification failed\n");
		return fail_with_rollback(-EIO);
	}

	stop_secondary = (ra80_smp_stop_fn_t)smp_stop;
	jump_to_ram = (ra80_raw_restart_fn_t)raw_restart;
	pr_emerg("ra80_ramboot_full: HANDOFF NOW entry=%08lx watchdog=0\n",
		 RA80_UBOOT_PHYS);
	ra80_handoff_led(0xc); /* system off, network white: before SMP stop */
	stop_secondary();
	ra80_handoff_led(0x2); /* system blue only: SMP stop returned, raw restart next */
	writel(0, ra80_watchdog_map);
	mb();
	jump_to_ram(RA80_UBOOT_PHYS, true);

	/* A successful handoff never returns.  Keep the stopped system inert if it does. */
	pr_emerg("ra80_ramboot_full: FATAL: raw restart returned; power-cycle required\n");
	for (;;)
		cpu_relax();
}

static void __exit ra80_ramboot_full_exit(void)
{
	/* The module never finishes loading on the successful one-shot path. */
	restore_stock();
	release_resources();
}

module_init(ra80_ramboot_full_init);
module_exit(ra80_ramboot_full_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Luochancy / OpenAI-assisted RA80 research");
MODULE_DESCRIPTION("Guarded one-shot RAM-only Xiaomi RA80 U-Boot handoff");
MODULE_VERSION("1.0");
