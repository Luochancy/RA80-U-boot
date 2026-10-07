/*
 * ra80_probe.c - Xiaomi RA80 / IPQ5018 read-only U-Boot RAM probe
 *
 * Deliberately READ-ONLY:
 *  - does not write the U-Boot reserved region
 *  - does not stop CPUs
 *  - does not invoke restart functions
 *  - does not touch NAND/MTD
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/kallsyms.h>

#define RA80_UBOOT_PHYS  0x4a920000UL
#define RA80_PROBE_LEN   0x1000UL

static void __iomem *ra80_uboot_map;

static int __init ra80_probe_init(void)
{
    unsigned long soft_restart_addr;
    unsigned long raw_soft_restart_addr;
    unsigned long smp_send_stop_addr;
    u32 w0, w1, w2, w3;
    u8 __iomem *p;

    pr_info("ra80_probe: loading (READ-ONLY probe)\n");
    pr_info("ra80_probe: target phys=0x%08lx len=0x%lx\n",
            RA80_UBOOT_PHYS, RA80_PROBE_LEN);

    soft_restart_addr = kallsyms_lookup_name("soft_restart");
    raw_soft_restart_addr = kallsyms_lookup_name("_soft_restart");
    smp_send_stop_addr = kallsyms_lookup_name("smp_send_stop");

    pr_info("ra80_probe: soft_restart  = 0x%08lx\n", soft_restart_addr);
    pr_info("ra80_probe: _soft_restart = 0x%08lx\n", raw_soft_restart_addr);
    pr_info("ra80_probe: smp_send_stop = 0x%08lx\n", smp_send_stop_addr);

    if (!soft_restart_addr || !raw_soft_restart_addr || !smp_send_stop_addr) {
        pr_err("ra80_probe: one or more required symbols were not resolved\n");
        return -ENOENT;
    }

    ra80_uboot_map = ioremap(RA80_UBOOT_PHYS, RA80_PROBE_LEN);
    if (!ra80_uboot_map) {
        pr_err("ra80_probe: ioremap failed\n");
        return -ENOMEM;
    }

    p = (u8 __iomem *)ra80_uboot_map;
    w0 = readl(p + 0x00);
    w1 = readl(p + 0x04);
    w2 = readl(p + 0x08);
    w3 = readl(p + 0x0c);

    pr_info("ra80_probe: U-Boot words @ 0x4a920000:\n");
    pr_info("ra80_probe:   +0x00 = 0x%08x\n", w0);
    pr_info("ra80_probe:   +0x04 = 0x%08x\n", w1);
    pr_info("ra80_probe:   +0x08 = 0x%08x\n", w2);
    pr_info("ra80_probe:   +0x0c = 0x%08x\n", w3);

    if (w0 == 0xEA0000B8 &&
        w1 == 0xE59FF014 &&
        w2 == 0xE59FF014 &&
        w3 == 0xE59FF014)
        pr_info("ra80_probe: stock APPSBL signature matches expected bytes\n");
    else
        pr_warn("ra80_probe: stock APPSBL signature differs from expected bytes\n");

    pr_info("ra80_probe: probe complete; no memory was modified\n");
    return 0;
}

static void __exit ra80_probe_exit(void)
{
    if (ra80_uboot_map) {
        iounmap(ra80_uboot_map);
        ra80_uboot_map = NULL;
    }

    pr_info("ra80_probe: unloaded\n");
}

module_init(ra80_probe_init);
module_exit(ra80_probe_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Luochancy / OpenAI-assisted RA80 research");
MODULE_DESCRIPTION("Read-only Xiaomi RA80 IPQ5018 U-Boot reserved-memory probe");
MODULE_VERSION("0.1");
