# RAM upload follow-up

## Sustained receive follow-up (2026-10-15)

An ACK-batched complete upload on d48db31 subsequently finished after 466.69s
and returned HTTP 422. Thus there is also a post-receive FIT rejection, not
just the short client timeout. The exact same candidate passes fdt_check_header
and both node lookups when executed in the delivered ARM binaries under
emulation (header=0, images=0x60, configurations=0xd4c4ac). No kernel started.

The stock DTB marks 0x4b000000..0x4c400000 as Q6 code/data, overlapping the
generic HTTP upload address. A chainload from stock Linux has not established
that Q6 is stopped, so that address cannot be treated as an unused staging
buffer. RAM-only uploads now go directly to RAM_BOOT_ADDR 0x44000000, bounded
by SDRAM, BOOTM_LEN and the 0x4a800000 reservation. RAM do_http_upgrade validates
and boots from that same address without copying through Q6 memory. Normal
flash-mode upload/copy behavior is preserved. The address overlap is certain;
whether a coprocessor overwrite caused this observed 422 is not yet proven.
Completion diagnostics now print received length, in-memory FIT magic/size,
header-check return value, and a separate node-lookup failure. The status
endpoint also reports the staging address. These changes do not stop Q6 or
claim a hardware DMA sandbox. Kernel FIT hashes remain required by bootm.

Hardware version d48db31 accepts a 40-byte invalid FIT immediately (HTTP 422),
but the 13,944,692-byte candidate times out. Even curl --limit-rate 256k reports
only 2,817,899 bytes submitted to the PC socket after 90 seconds. This number
is not the receiver's accepted-byte count. The old "verifying" status was set
at POST entry, before the body completed.

Direct bounded invalid-body probes against that same hardware returned 422
for 65,536 and 262,144 bytes. A 12-second 1-MiB probe recorded 222,270 bytes
retransmitted, 114 duplicate ACKs and six retransmission timeout episodes.
Its sender window remained nonzero (about 8.7--11.6 KiB). This establishes
ongoing reception with substantial packet loss/retransmission, rather than
proving a permanently stuck zero window or a kernel boot failure.

The old RA80 configuration inherited just four DMA receive buffers, while its
TCP window permits eight full-size segments. The main polling loop also
scanned up to 64 PHY addresses every 100 ms, including nonexistent devices
with up to three MDIO transactions each. Both can starve reception. RA80 now
has 32 receive buffers, checks only MDIO0:7 and MDIO1:0..4 at a one-second
interval, and defers link monitoring/DMA reinitialization while a RAM upload
owns the connection. Other IPQ5018 boards retain their original scan.
The performance effect still requires comparison on the real hardware.

RAM uploads now have normal TCP priority, like multipart uploads. The lwIP
error callback no longer accesses an already-freed PCB during cleanup.
GET /ramboot_status reports actual received/total bytes, elapsed time since
the last receive, current receive window and the compiled RX-buffer count.
The last counters survive disconnects. /upgrade_status distinguishes
receiving, upload_rejected and upload_aborted from verifying; terminal logs
record the first body chunk, each MiB and completion/abort. LED codes stay
steady. The new production-function regression exercises both the RA80 scan
and the unchanged generic IPQ5018 scan with absent, failing and latched-low
PHYs. CI must validate the increased BSS against the stock reservation before
producing any module. All previous RAM/NAND guards remain required.

For a controlled comparison, close other Web tabs and repeat the same curl
upload without changing the image. If it fails, read /ramboot_status and
/webterm/data?since=0; do not infer body completion from curl's size_upload.

The user reported the browser message "大小不匹配" with the verified 13,944,692
byte AX3000 initramfs. Both that image and the older 16,051,344 byte image have
FDT totalsize equal to file length. The old UI used the same size-error label
for any failed POST or network exception; the message did not establish a
size error. No useful terminal log was available because disable-console also
suppressed the Web capture call. The exact hardware failure was not isolated.

RAM mode now accepts a bounded binary POST /ramboot with a single valid
Content-Length and application/octet-stream. It accumulates a bounded header
across packets, copies only file bytes, checks exact length and FIT metadata,
and reports malformed, oversize and FIT errors separately. The Web form uses
the File directly, avoiding the old multipart parser's packet assumptions.
Normal mode retains the existing multipart path. Other RAM upload/setting
POSTs are rejected; Web terminal commands still allow only exact reset.

Only the upload connection's full response ACK arms RAM boot. Other HTTP
connections and partial ACKs cannot arm it. Its ownership is retained until
the reply is acknowledged or the connection is closed. Truncated/disconnected
uploads do not boot. This also addresses a global completion-flag race in the
old flow. If bootm returns, the browser reports a RAM boot failure explicitly.

RAM puts/putc now capture to the existing Web buffer while bypassing UART and
stdio. Console behavior outside active RA80 RAM mode is preserved.

The regression suite compiles actual production functions with host libfdt,
tests every two-packet split, bytewise transfers, malformed/overflowing length,
extra/truncated bytes, FIT length mismatch, connection ACK ownership, console
routing, and actual browser request/error behavior. Hardware calls are mocked.
These tests do not prove a real Linux handoff or working Linux Ethernet.

Keep using the reviewed initramfs .itb in memory boot mode. The steady LED
codes, kernel DTB NAND/MMC/Wi-Fi disable policy, and NAND/APPSBL write guards
remain in force. The module's new MD5 must be taken from its build artifact.
After loading this build, hard-refresh the Web page (Ctrl+F5) to replace old
cached scripts, then retry the same firmware. Report the full new error text
or the terminal log if bootm returns. Do not change to flash/update modes.
