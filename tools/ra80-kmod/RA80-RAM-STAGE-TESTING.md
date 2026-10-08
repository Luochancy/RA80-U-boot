# RA80 counted-entry RAM-only test

This version replaces the ambiguous early steady colours with counted pulses.
Upload only ra80_ramboot_full.ko; its matching U-Boot payload is embedded.
Never write NAND/APPSBL or upload firmware through the HTTP page.

User-calibrated LEDs are active high: GPIO17 lamp 2 System yellow; GPIO19
lamp 2 System white; GPIO20 lamp 1 Internet yellow; GPIO22 lamp 1 Internet white.
Both channels on can appear mixed white/yellow. The chassis has 4 LAN + 1 WAN.

## Test

Power-cycle to stock Linux first. Verify the module SHA256 against inspection.txt
on the computer (Get-FileHash on Windows). Keep stock SSH networking until handoff.

```sh
devmem 0x4a920000 32
sync
insmod /tmp/ra80_ramboot_full.ko execute=1
```

The initial RAM vector must be EA0000B8. Record a video from before insmod.
Linux only drives lamp 1: all off, yellow, white countdown, both Internet
channels before SMP stop, Internet yellow after SMP stop. Lamp 2 stays off.

New U-Boot assembly uses only lamp 2, with lamp 1 off:
- one yellow pulse, then yellow hold: reset entry reached;
- two white pulses, then white hold: save_boot_params returned;
- three yellow pulses, then yellow hold: CPU setup completed, before _main.

Pulse dwell is a bounded busy loop, not calibrated seconds. Record counts
rather than inferring stages from a single final colour. Later LED setup,
auto-Webfailsafe and Ethernet stages can overwrite these colours.

For the armed RAM test only, main_loop clears ethact/ethprime and enables
ethrotate=yes before eth_initialize. It does not save the environment.
The legacy Ethernet start routine already tries the next registered device
if device init fails; this is not a promise that every jack is functional.

After SSH disconnects set the PC to 192.168.1.2/24, gateway/DNS blank,
disable Wi-Fi/VPN, wait up to 60 seconds and test all four LAN ports then WAN.
Ping 192.168.1.1 and open http://192.168.1.1/ if reachable. Do not upload.
Report pulse counts, final lamp 1 / lamp 2 colours, and connectivity.
Power-cycle after observations to restore stock.

If insmod returns an error, do not retry. Capture:
```sh
dmesg | grep 'ra80_ramboot_full:' | tail -50
devmem 0x4a920000 32
```

The module retains led_test=1 calibration mode, which cannot be combined with
execute=1. This only drives the four LEDs, restores their registers, and
does not stage a payload or change the watchdog. It is not needed again
because the wiring was already calibrated on this unit.
