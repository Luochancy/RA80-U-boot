# RA80 V1 complete RAM-only U-Boot test

This bundle targets Xiaomi RA80 V1 / IPQ5018 stock Linux 4.4.60. Both kernel
modules are built by the matching QSDK 11.4 / GCC 5.5 SDK, and both contain the
U-Boot payload built from the same Git commit.

## Safety boundary

`ra80_ramboot_full.ko` is a one-shot RAM handoff. It accepts only the measured
stock APPSBL vectors, exact stock-kernel function addresses and instruction
fingerprints, and watchdog value `1`. It backs up the full overwritten RAM
window, verifies every payload byte, writes a one-word Webfailsafe marker only
inside that RAM copy, then disables the watchdog, stops the secondary CPU, and
jumps to physical address `0x4a920000`.

Every error before watchdog disable restores the original RAM byte-for-byte.
The module has no NAND, MTD, UBI, flash, or APPSBL call path. Power cycling
returns to Xiaomi's original boot chain. Never flash the bundled flat `.bin`
file to APPSBL or APPSBL_1.

`ra80_stage_ethdiag.ko` remains the reversible, non-jumping diagnostic module.
It is included for inspection and rollback tests, but it is not needed for the
complete one-shot test below.

## Automatic Webfailsafe entry

The normal U-Boot image contains a guard word. The full module changes that
word only in the staged RAM copy. U-Boot consumes it once and automatically
starts Webfailsafe, so the complete test does not require holding Reset while
stock Linux is running. A normal or flashed image keeps the original
button-controlled behavior.

## LED stage code

The two physical LEDs are dual-colour. Each code is shown as
`system LED / network LED`:

| Code | Visible colours | Meaning |
| --- | --- | --- |
| `1` | yellow / off | LED and FDT setup reached |
| `2` | blue / off | RAM-only auto-Webfailsafe marker accepted |
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

The front panel has 1 WAN and 3 LAN jacks. The stock Linux device tree exposes
QCA8337 PHY addresses 0 through 4; the U-Boot switch count intentionally follows
that MDIO topology.

## Complete one-shot test

1. Extract the Actions artifact and verify the SHA-256 for
   `ra80_ramboot_full.ko` against `inspection.txt`.
2. Copy only `ra80_ramboot_full.ko` to `/tmp` on the router.
3. Connect a computer by Ethernet, initially to LAN 1. Set it to
   `192.168.1.2/24`, with gateway and DNS blank. Disable Wi-Fi and VPN.
4. On the router, make sure no old stage module is loaded and confirm the stock
   vector:

   ```sh
   rmmod ra80_stage_ethdiag 2>/dev/null
   devmem 0x4a920000 32
   sha256sum /tmp/ra80_ramboot_full.ko
   ```

   The vector must be `0xEA0000B8`, and the module hash must exactly match
   `inspection.txt`. If either check differs, stop and power-cycle.

5. Start the complete RAM-only handoff:

   ```sh
   sync
   insmod /tmp/ra80_ramboot_full.ko execute=1
   ```

   Do not press Reset. A successful handoff disconnects SSH after the guarded
   three-second delay and automatically starts Webfailsafe.

6. Wait up to 30 seconds. Record the final steady LED colours, then test:

   ```sh
   ping 192.168.1.1
   ```

   Open `http://192.168.1.1/` if ping succeeds. If there is no link, try the
   other two LAN jacks and then WAN without power cycling, recording the LED
   code for each result.

7. Do not upload or flash anything from the Webfailsafe page during this test.
   When observations are complete, power-cycle the router. Xiaomi stock Linux
   should boot normally because NAND/APPSBL was never modified.

If `insmod` returns instead of dropping SSH, do not retry. Save:

```sh
dmesg | grep 'ra80_ramboot_full:' | tail -50
devmem 0x4a920000 32
```

On every pre-handoff failure the log should report the reason and, if staging
had begun, `stock RAM restored and verified`; the vector should be
`0xEA0000B8`.
