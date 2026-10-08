# ICMP source provenance

Files core/ipv4/icmp.c, include/lwip/icmp.h and include/lwip/prot/icmp.h
are unmodified copies from the official lwIP mirror, commit `d08f4773edd0182b7910fc8f046eed82ffcd67c9`:
https://github.com/lwip-tcpip/lwip/tree/d08f4773edd0182b7910fc8f046eed82ffcd67c9/src

The existing init.h matches this upstream snapshot exactly (2.2.2 development).
The local ip4.c differs only in optional header guards/line ending from the
snapshot. Original BSD copyright/license notices are retained in each file.
ICMP is enabled and linked only for CONFIG_IPQ5018_XIAOMI_RA80.
