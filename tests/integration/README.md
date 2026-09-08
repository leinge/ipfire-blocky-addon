# Appliance integration matrix

These tests require disposable IPFire `x86_64` and `aarch64` appliances plus
client systems attached to GREEN and BLUE. They are release gates because a
source-overlay checkout cannot faithfully emulate IPFire's firewall, Pakfire,
boot, and backup behavior.

For each architecture:

1. build and install `blocky-0.35.0-1.ipfire` from the pinned IPFire baseline;
2. verify the fresh install is stopped, boot-disabled, and has no `BLOCKY_*`
   jumps in the packet path;
3. validate/start Blocky, select GREEN, and prove TCP/UDP queries to both the
   IPFire address and an external port-53 destination retain the client IP;
4. repeat independently for BLUE and confirm RED/unselected traffic is never
   accepted by package rules;
5. enable bypass prevention and test TCP/UDP 53, TCP/UDP 853, selected provider
   domains, dedicated TCP/UDP 443 targets, explicit exceptions, and ordinary
   HTTPS/QUIC destinations;
6. kill Blocky and force restart/validation failures, confirming enforcement
   remains installed and client DNS fails closed;
7. exercise firewall reload, RED reconnect, and reboot reconstruction;
8. run `/usr/sbin/blocky-recovery` without network access and verify persisted
   policy is off, Knot answers, and user configuration remains;
9. exercise backup/restore, update success, update rollback, and uninstall;
10. confirm unrelated `/etc/sysconfig/firewall.local` bytes survive all package
    lifecycle operations.

Local preflight uses the real pinned binary and the IPFire overlay:

```sh
make check IPFIRE_TREE=/path/to/ipfire-2.x BLOCKY_BIN=/path/to/blocky
```
