/*
 * (C) Copyright 2000
 * Wolfgang Denk, DENX Software Engineering, wd@denx.de.
 *
 * SPDX-License-Identifier:	GPL-2.0+
 */

/* #define	DEBUG	*/

#include <common.h>
#include <ra80_bootstage.h>
#include <autoboot.h>
#include <cli.h>
#include <console.h>
#include <version.h>

#ifdef CONFIG_LWIP_HTTPD
#include <asm/arch-qca-common/gpio.h>
#include <ipq_api.h>
#if defined(CONFIG_IPQ5018_XIAOMI_RA80)
#include <net.h>
#include "../net/httpd.h"
#include "../failsafe/failsafe_httpd.h"
#endif
#endif
DECLARE_GLOBAL_DATA_PTR;

#if defined(CONFIG_LWIP_HTTPD) && defined(CONFIG_IPQ5018_XIAOMI_RA80)
/*
 * A normal image carries the guard value.  The RAM-only Linux handoff module
 * changes only this word in the staged copy before jumping to U-Boot.  This
 * keeps normal/flash boots on the button-controlled path while allowing the
 * diagnostic RAM boot to enter Webfailsafe without holding Reset under Linux.
 */
#define RA80_RAMBOOT_MAGIC_GUARD 0x5241382fU
#define RA80_RAMBOOT_MAGIC_ARMED 0x52413830U
volatile unsigned int ra80_ramboot_magic = RA80_RAMBOOT_MAGIC_GUARD;
#endif

#ifdef CONFIG_IPQ5018_XIAOMI_RA80
static int ra80_ram_test_mode;
#ifdef CONFIG_RA80_LINK_DIAGNOSTICS
unsigned int ra80_link_furthest;
#endif
int ra80_ram_test_active(void)
{
	/* The initialized-data marker is valid before NAND/env initialization.
	 * Keep the mode latched after main_loop consumes that marker. */
#ifdef CONFIG_LWIP_HTTPD
	return ra80_ram_test_mode ||
		ra80_ramboot_magic == RA80_RAMBOOT_MAGIC_ARMED;
#else
	return ra80_ram_test_mode;
#endif
}
#endif

/*
 * Board-specific Platform code can reimplement show_boot_progress () if needed
 */
__weak void show_boot_progress(int val) {}

#ifndef CONFIG_REDUCE_FOOTPRINT
static void modem_init(void)
{
#ifdef CONFIG_MODEM_SUPPORT
	debug("DEBUG: main_loop:   gd->do_mdm_init=%lu\n", gd->do_mdm_init);
	if (gd->do_mdm_init) {
		char *str = getenv("mdm_cmd");

		setenv("preboot", str);  /* set or delete definition */
		mdm_init(); /* wait for modem connection */
	}
#endif  /* CONFIG_MODEM_SUPPORT */
}

static void run_preboot_environment_command(void)
{
#ifdef CONFIG_PREBOOT
	char *p;

	p = getenv("preboot");
	if (p != NULL) {
# ifdef CONFIG_AUTOBOOT_KEYED
		int prev = disable_ctrlc(1);	/* disable Control C checking */
# endif

		run_command_list(p, -1, 0);

# ifdef CONFIG_AUTOBOOT_KEYED
		disable_ctrlc(prev);	/* restore Control C checking */
# endif
	}
#endif /* CONFIG_PREBOOT */
}
#endif

#if defined(CONFIG_LWIP_HTTPD) && defined(CONFIG_IPQ5018_XIAOMI_RA80)
/* RAM diagnostics need no interactive shell or serial console. Keep networking
 * polling independently of Hush allocation, command parsing and UART waits. */
static void ra80_ram_network_loop(void)
{
	int devices;

	ra80_ramboot_magic = RA80_RAMBOOT_MAGIC_GUARD;
	gd->flags |= GD_FLG_DISABLE_CONSOLE;
	ra80_net_stage(RA80_NET_PREPARE, 3);
	setenv("ethact", NULL);
	setenv("ethprime", NULL);
	if (setenv("ethrotate", "yes") || setenv("ipaddr", "192.168.1.1") ||
	    setenv("netmask", "255.255.255.0"))
		hang();
	ra80_net_stage(RA80_NET_ENV_READY, 4);
	devices = eth_initialize();
	ra80_bootstage(RA80_STAGE_LINK);
	if (devices <= 0)
		hang();
	HttpdStart();
	if (!webfailsafe_is_running)
		hang();
	net_copy_ip(&net_httpd_ip, &net_ip);
	for (;;)
		httpd_poll();
}
#endif

/* We come here after U-Boot is initialised and ready to process commands */
void main_loop(void)
{
	const char *s = NULL;
	int ra80_ram_test = 0;
#if defined(CONFIG_LWIP_HTTPD) && defined(CONFIG_IPQ5018_XIAOMI_RA80)
	ra80_ram_test = ra80_ramboot_magic == RA80_RAMBOOT_MAGIC_ARMED;
	ra80_ram_test_mode = ra80_ram_test;
#endif
	ra80_bootstage(RA80_STAGE_MAIN);
	ra80_runtime_stage(RA80_RT_MAIN);
#if defined(CONFIG_LWIP_HTTPD) && defined(CONFIG_IPQ5018_XIAOMI_RA80)
	if (ra80_ram_test)
		ra80_ram_network_loop();
#endif

	bootstage_mark_name(BOOTSTAGE_ID_MAIN_LOOP, "main_loop");

#ifndef CONFIG_SYS_GENERIC_BOARD
	puts("Warning: Your board does not use generic board. Please read\n");
	puts("doc/README.generic-board and take action. Boards not\n");
	puts("upgraded by the late 2014 may break or be removed.\n");
#endif

#ifndef CONFIG_REDUCE_FOOTPRINT
	modem_init();
#ifdef CONFIG_VERSION_VARIABLE
	setenv("ver", version_string);  /* set version variable */
#endif /* CONFIG_VERSION_VARIABLE */
#endif

	cli_init();

#ifndef CONFIG_REDUCE_FOOTPRINT
	if (!ra80_ram_test)
		run_preboot_environment_command();
#endif

#if defined(CONFIG_UPDATE_TFTP)
	if (!ra80_ram_test)
		update_tftp(0UL, NULL, NULL);
#endif /* CONFIG_UPDATE_TFTP */

#ifdef CONFIG_LWIP_HTTPD
	btn_check_press();
#endif
#ifdef CONFIG_BOARD_DISPLAY_NAME
	const char *env_config = getenv("config_name");
	if (env_config && strlen(env_config) > 0) {
		printf("##Using 'config_name=%s' from environment variable\n", env_config);
	}
#endif
	if (!ra80_ram_test)
		s = bootdelay_process();
#ifndef CONFIG_REDUCE_FOOTPRINT
	if (!ra80_ram_test && cli_process_fdt(&s))
		cli_secure_boot_cmd(s);
#endif

#ifdef CONFIG_LWIP_HTTPD
	if (!ra80_ram_test && !webfailsafe_is_running)
#endif
	autoboot_command(s);

	cli_loop();
}
