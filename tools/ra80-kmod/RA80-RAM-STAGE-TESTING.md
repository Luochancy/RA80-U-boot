# RA80 V1 RAM-only LED diagnostic stage

This artifact targets Xiaomi RA80 V1 / IPQ5018 stock Linux 4.4.60. The stage
module is built by the matching QSDK 11.4 / GCC 5.5 SDK. It contains the U-Boot
payload built from the same Git commit.

## Safety boundary

`ra80_stage_ethdiag.ko` only replaces the reserved U-Boot copy at physical
address `0x4a920000` in RAM. It refuses to load unless the observed stock vector
is `EA0000B8 E59FF014 E59FF014 E59FF014`, keeps a full backup, verifies every
payload byte, rolls back immediately on a mismatch, and restores stock RAM when
removed. It has no restart function, no watchdog control, and no NAND/MTD path.

Do not flash the bundled `.mbn` to APPSBL or APPSBL_1. It is included so the
module payload can be independently hashed and inspected.

## LED stage code

The two physical LEDs are dual-colour. Each code is shown as
`system LED / network LED`:

| Code | Visible colours | Meaning |
| --- | --- | --- |
| `1` | yellow / off | LED and FDT setup reached |
| `2` | blue / off | Reset detected |
| `3` | white / off | Reset held for three seconds |
| `4` | off / yellow | `board_eth_init()` entered |
| `5` | yellow / yellow | Ethernet clocks and resets completed |
| `6` | blue / yellow | external MDIO GPIO configured |
| `7` | white / yellow | GPIO26 switch reset pulse completed |
| `8` | off / blue | board description parsed; GMAC driver entered |
| `9` | yellow / blue | both MDIO buses registered |
| `A` | blue / blue | GMAC0 registered; final persistent `A` means HTTP ready |
| `B` | white / blue | QCA8337 initialization starting |
| `C` | off / white | QCA8337 initialization returned |
| `D` | yellow / white | GMAC1 registered or real link start beginning |
| `E` | blue / white | Ethernet initialization failed |
| `F` | white / white | at least one Ethernet device is active |

The front panel has 1 WAN and 3 LAN jacks. The stock Linux device tree still
enumerates QCA8337 PHY addresses 0 through 4; the U-Boot switch count deliberately
matches that stock MDIO topology rather than the number of visible jacks.

## First load: stage only

Copy only `ra80_stage_ethdiag.ko` to `/tmp`, then verify its SHA-256 against
`inspection.txt`. On the router, verify the stock vector before loading:

```sh
devmem 0x4a920000 32
```

It must print `0xEA0000B8`. Then load the module:

```sh
insmod /tmp/ra80_stage_ethdiag.ko
dmesg | grep 'ra80_stage_ethdiag:' | tail -30
devmem 0x4a920000 32
```

Stop after this first load. A successful stage prints `STAGE VERIFIED`, and the
first word changes to the value recorded in `inspection.txt`. Do not load an old
trigger module: its payload length/hash guard belongs to a different U-Boot.

To abort safely without rebooting:

```sh
rmmod ra80_stage_ethdiag
dmesg | grep 'ra80_stage_ethdiag:' | tail -10
devmem 0x4a920000 32
```

The log must say `stock RAM restored and verified`, and the first word must be
`0xEA0000B8` again.
