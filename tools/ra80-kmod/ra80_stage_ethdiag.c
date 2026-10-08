/*
 * ra80_stage_ethdiag.c - reversible RAM-only U-Boot stage for Xiaomi RA80
 *
 * Safety properties:
 *  - accepts only the observed stock APPSBL vector signature
 *  - keeps a byte-for-byte backup of every overwritten byte
 *  - verifies the complete payload after writing it
 *  - restores the stock bytes immediately if verification fails
 *  - restores the stock bytes when the module is removed
 *  - never jumps to the payload and never touches NAND/MTD
 */

#include <linux/init.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/types.h>
#include <linux/vmalloc.h>

#include "ra80_payload.inc"

#define RA80_UBOOT_PHYS       0x4a920000UL
#define RA80_MIN_PAYLOAD_LEN  (64UL * 1024UL)
#define RA80_MAX_PAYLOAD_LEN  (2UL * 1024UL * 1024UL)
#define FNV1A_OFFSET          0x811c9dc5U
#define FNV1A_PRIME           0x01000193U

#define RA80_STOCK_VECTOR0    0xea0000b8U
#define RA80_VECTOR_LITERAL   0xe59ff014U
#define RA80_WATCHDOG_CTRL_PHYS      0x0b017008UL
#define RA80_EXPECTED_SOFT_RESTART   0x81219980UL
#define RA80_EXPECTED_RAW_RESTART    0x81219958UL
#define RA80_EXPECTED_SMP_STOP       0x8121d0a4UL

extern unsigned long kallsyms_lookup_name(const char *name);

static void __iomem *ra80_uboot_map;
static u8 *ra80_stock_backup;
static u32 ra80_stock_fnv1a;
static bool ra80_staged;
static bool handoff_preflight;
module_param(handoff_preflight, bool, 0444);
MODULE_PARM_DESC(handoff_preflight,
	"Read-only kernel handoff preflight after staging; never jumps");

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
			pr_err("ra80_stage_ethdiag: verify mismatch at 0x%zx: expected=%02x actual=%02x\n",
			       i, ra80_payload[i], actual);
			return -EIO;
		}

		hash ^= actual;
		hash *= FNV1A_PRIME;
	}

	if (hash != RA80_PAYLOAD_FNV1A) {
		pr_err("ra80_stage_ethdiag: verify hash mismatch: expected=%08x actual=%08x\n",
		       RA80_PAYLOAD_FNV1A, hash);
		return -EIO;
	}

	return 0;
}

static int restore_stock(void)
{
	u32 restored_hash;

	if (!ra80_uboot_map || !ra80_stock_backup)
		return -EINVAL;

	memcpy_toio(ra80_uboot_map, ra80_stock_backup, RA80_PAYLOAD_LEN);
	wmb();
	restored_hash = fnv1a_io((u8 __iomem *)ra80_uboot_map,
				  RA80_PAYLOAD_LEN);

	if (restored_hash != ra80_stock_fnv1a || !stock_vector_matches()) {
		pr_emerg("ra80_stage_ethdiag: STOCK RESTORE VERIFICATION FAILED hash=%08x expected=%08x\n",
			 restored_hash, ra80_stock_fnv1a);
		return -EIO;
	}

	ra80_staged = false;
	pr_info("ra80_stage_ethdiag: stock RAM restored and verified fnv1a=%08x\n",
		restored_hash);
	return 0;
}

/*
 * A deliberate read-only checkpoint for the future handoff module.  It is
 * opt-in, runs only after the payload byte verification above, and has no
 * restart, CPU-stop, watchdog-write, NAND, or MTD operation.
 */
static int check_handoff_preflight(void)
{
	void __iomem *watchdog;
	unsigned long soft_restart;
	unsigned long raw_restart;
	unsigned long smp_stop;
	u32 watchdog_value;

	if (!handoff_preflight)
		return 0;

	soft_restart = kallsyms_lookup_name("soft_restart");
	raw_restart = kallsyms_lookup_name("_soft_restart");
	smp_stop = kallsyms_lookup_name("smp_send_stop");
	if (soft_restart != RA80_EXPECTED_SOFT_RESTART ||
	    raw_restart != RA80_EXPECTED_RAW_RESTART ||
	    smp_stop != RA80_EXPECTED_SMP_STOP) {
		pr_err("ra80_stage_ethdiag: PREFLIGHT symbol mismatch soft=%08lx raw=%08lx smp=%08lx\n",
		       soft_restart, raw_restart, smp_stop);
		return -EPERM;
	}

	watchdog = ioremap(RA80_WATCHDOG_CTRL_PHYS, sizeof(u32));
	if (!watchdog)
		return -ENOMEM;
	watchdog_value = readl(watchdog);
	iounmap(watchdog);

	pr_info("ra80_stage_ethdiag: PREFLIGHT PASS soft=%08lx raw=%08lx smp=%08lx watchdog=%08x\n",
		soft_restart, raw_restart, smp_stop, watchdog_value);
	pr_info("ra80_stage_ethdiag: PREFLIGHT is read-only; no jump, CPU stop, or watchdog write\n");
	return 0;
}

static void release_resources(void)
{
	if (ra80_uboot_map) {
		iounmap(ra80_uboot_map);
		ra80_uboot_map = NULL;
	}

	vfree(ra80_stock_backup);
	ra80_stock_backup = NULL;
}

static int __init ra80_stage_ethdiag_init(void)
{
	u32 payload_hash;
	u32 payload_word0;
	u32 payload_word1;
	u32 payload_word2;
	u32 payload_word3;
	int ret;

	pr_info("ra80_stage_ethdiag: loading reversible RAM-only stage\n");
	pr_info("ra80_stage_ethdiag: NO NAND/MTD writes; NO automatic jump\n");
	pr_info("ra80_stage_ethdiag: payload commit=%s len=%u sha256=%s\n",
		RA80_PAYLOAD_SOURCE_COMMIT, RA80_PAYLOAD_LEN,
		RA80_PAYLOAD_SHA256);

	if (RA80_PAYLOAD_LEN < RA80_MIN_PAYLOAD_LEN ||
	    RA80_PAYLOAD_LEN > RA80_MAX_PAYLOAD_LEN) {
		pr_err("ra80_stage_ethdiag: refusing unexpected payload length %u\n",
		       RA80_PAYLOAD_LEN);
		return -EINVAL;
	}

	payload_word0 = (u32)ra80_payload[0] |
			((u32)ra80_payload[1] << 8) |
			((u32)ra80_payload[2] << 16) |
			((u32)ra80_payload[3] << 24);
	payload_word1 = (u32)ra80_payload[4] |
			((u32)ra80_payload[5] << 8) |
			((u32)ra80_payload[6] << 16) |
			((u32)ra80_payload[7] << 24);
	payload_word2 = (u32)ra80_payload[8] |
			((u32)ra80_payload[9] << 8) |
			((u32)ra80_payload[10] << 16) |
			((u32)ra80_payload[11] << 24);
	payload_word3 = (u32)ra80_payload[12] |
			((u32)ra80_payload[13] << 8) |
			((u32)ra80_payload[14] << 16) |
			((u32)ra80_payload[15] << 24);

	if ((payload_word0 & 0xff000000U) != 0xea000000U ||
	    payload_word1 != RA80_VECTOR_LITERAL ||
	    payload_word2 != RA80_VECTOR_LITERAL ||
	    payload_word3 != RA80_VECTOR_LITERAL) {
		pr_err("ra80_stage_ethdiag: refusing unexpected payload vectors %08x %08x %08x %08x\n",
		       payload_word0, payload_word1, payload_word2, payload_word3);
		return -EINVAL;
	}

	payload_hash = fnv1a_buffer(ra80_payload, RA80_PAYLOAD_LEN);
	if (payload_hash != RA80_PAYLOAD_FNV1A) {
		pr_err("ra80_stage_ethdiag: embedded payload hash mismatch expected=%08x actual=%08x\n",
		       RA80_PAYLOAD_FNV1A, payload_hash);
		return -EINVAL;
	}

	ra80_stock_backup = vmalloc(RA80_PAYLOAD_LEN);
	if (!ra80_stock_backup)
		return -ENOMEM;

	ra80_uboot_map = ioremap(RA80_UBOOT_PHYS, RA80_PAYLOAD_LEN);
	if (!ra80_uboot_map) {
		pr_err("ra80_stage_ethdiag: ioremap failed\n");
		release_resources();
		return -ENOMEM;
	}

	if (!stock_vector_matches()) {
		u8 __iomem *p = (u8 __iomem *)ra80_uboot_map;

		pr_err("ra80_stage_ethdiag: refusing non-stock RAM vectors %08x %08x %08x %08x\n",
		       readl(p + 0x00), readl(p + 0x04),
		       readl(p + 0x08), readl(p + 0x0c));
		release_resources();
		return -EPERM;
	}

	memcpy_fromio(ra80_stock_backup, ra80_uboot_map, RA80_PAYLOAD_LEN);
	ra80_stock_fnv1a = fnv1a_buffer(ra80_stock_backup,
					RA80_PAYLOAD_LEN);
	pr_info("ra80_stage_ethdiag: stock backup complete first=%08x fnv1a=%08x\n",
		RA80_STOCK_VECTOR0, ra80_stock_fnv1a);

	memcpy_toio(ra80_uboot_map, ra80_payload, RA80_PAYLOAD_LEN);
	wmb();

	ret = verify_payload();
	if (ret) {
		pr_err("ra80_stage_ethdiag: stage verification failed; restoring stock RAM\n");
		if (restore_stock())
			pr_emerg("ra80_stage_ethdiag: automatic rollback failed\n");
		release_resources();
		return ret;
	}

	ret = check_handoff_preflight();
	if (ret) {
		pr_err("ra80_stage_ethdiag: preflight failed; restoring stock RAM\n");
		if (restore_stock())
			pr_emerg("ra80_stage_ethdiag: automatic rollback failed\n");
		release_resources();
		return ret;
	}

	ra80_staged = true;
	pr_info("ra80_stage_ethdiag: STAGE VERIFIED first=%08x len=%u fnv1a=%08x\n",
		payload_word0, RA80_PAYLOAD_LEN, RA80_PAYLOAD_FNV1A);
	pr_info("ra80_stage_ethdiag: safe abort: rmmod ra80_stage_ethdiag\n");
	pr_info("ra80_stage_ethdiag: module does not jump or disable watchdog\n");
	return 0;
}

static void __exit ra80_stage_ethdiag_exit(void)
{
	if (ra80_staged)
		restore_stock();

	release_resources();
	pr_info("ra80_stage_ethdiag: unloaded\n");
}

module_init(ra80_stage_ethdiag_init);
module_exit(ra80_stage_ethdiag_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Luochancy / OpenAI-assisted RA80 research");
MODULE_DESCRIPTION("Reversible RAM-only Xiaomi RA80 LED-diagnostic U-Boot stage");
MODULE_VERSION("0.4");
