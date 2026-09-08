# Enforcement and emergency recovery

## Fail-closed behavior

After routing is successfully enabled for GREEN or BLUE, the add-on does not
remove its DNS interception rules merely because Blocky stops or becomes
unhealthy. Clients in an enforced zone therefore lose DNS rather than silently
bypassing filtering through Knot or an external resolver.

Firewall policy is reconstructed from a root-owned manifest after IPFire
firewall reloads, RED reconnects, and reboot. Bypass policy is applied only to
forwarded selected-zone traffic; it does not block Blocky's or Knot's own
upstream requests.

The Web UI prevents an ordinary service stop or boot-disable while enforcement
is configured. Directly stopping the init service or killing the process still
leaves enforcement in place by design.

## Normal disable sequence

Use the Web UI to:

1. disable bypass prevention for each zone;
2. apply;
3. disable transparent routing for each zone;
4. apply and verify client DNS through Knot; and
5. stop or boot-disable Blocky if desired.

## Emergency local-console recovery

If Blocky cannot be recovered and clients have no DNS, sign in locally or over
an already-established administrative shell as root and run:

```sh
/usr/sbin/blocky-recovery
```

The command clears the persisted routing/bypass choices, removes only the
add-on's firewall jumps/chains/IP sets, regenerates the non-enforcing runtime
state, and verifies that Knot answers on `127.0.0.1:53`. It does not delete the
user's Blocky feature configuration or list definitions. Reboot does not
re-enable enforcement after this recovery.

If the command reports that Knot did not answer, enforcement has still been
removed; diagnose the built-in resolver before relying on DNS.

## Known DoH limitations

Provider IPs can change and addresses shared with other services cannot be
safely blocked. The package therefore uses only reviewed dedicated destination
networks and shows the exact catalog selection in the UI. Generic DoH over
unknown HTTPS, VPNs, proxies, and tunnels is not reliably identifiable without
traffic inspection and remains outside this add-on's guarantee.
