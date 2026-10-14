# RAM upload follow-up

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
