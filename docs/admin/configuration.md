# Configuring Blocky on IPFire

The Web UI is under **Services > Blocky** and has five areas.

## 1. Service

This page reports process, boot, loopback health, selected-zone, routing, and
bypass status. Starting and enabling at boot are separate operations. Blocky
cannot be stopped or boot-disabled through the page while enforcement is
active.

## 2. Configuration

The guided editor is generated from the Blocky v0.35.0 JSON Schema and covers
upstreams, local records, blocking groups and schedules, clients, cache/Redis,
logging, telemetry, optional listeners, TLS, and resolver policy. Dynamic maps
and arrays can be added and reordered. The advanced editor changes the same
canonical JSON document; JSON is valid YAML and is used to generate
`/etc/blocky/config.yml`.

YAML and JSON imports are normalized. Comments and formatting are not retained.
Normal exports redact passwords and database credentials. Secret-bearing
exports require a separate warning and must be stored securely.

IPFire's add-on backup includes the canonical settings and `/etc/blocky`.
Place TLS keys/certificates that should follow this backup under `/etc/blocky`
with `root:blocky` ownership and mode `0640` or stricter. Query logs, database
files, certificates, and keys configured elsewhere are not included; back them
up separately. Caches, generated firewall state, and logs are deliberately
excluded.

The DNS listener is managed by the IPFire integration and is read-only in the
generic editor. Optional Blocky HTTP/HTTPS/TLS listeners are not automatically
opened in IPFire's firewall. Bind them narrowly and add explicit firewall policy
only after reviewing the API, metrics, DoH, and profiling surfaces they expose.

## 3. Zones

GREEN is always shown. BLUE appears only when configured in IPFire. Selecting a
zone makes Blocky listen on that zone's current address at port 1053 in addition
to loopback. It does not yet redirect client traffic. RED and ORANGE cannot be
selected.

## 4. Routing

**Force conventional DNS through Blocky** redirects TCP and UDP port 53 from a
selected zone to Blocky port 1053, regardless of the DNS destination chosen by
the device. The original client source address is retained, so Blocky client
groups can distinguish devices.

The default Blocky upstream remains IPFire's Knot Resolver at
`127.0.0.1:53`. Local output is not captured by the zone interception rule, so
that path cannot loop.

## 5. Bypass prevention

Bypass prevention requires routing. For an enabled zone it:

- intercepts or defensively rejects direct TCP/UDP 53;
- rejects TCP/UDP 853 for DoT and DoQ;
- injects selected known DoH domains into a reserved Blocky denylist group; and
- rejects TCP/UDP 443 only to selected reviewed DoH destination networks.

The bundled catalog includes Cloudflare, Google, Quad9, AdGuard, and NextDNS.
Custom domains/networks and explicit exceptions can be added. Catalog entries
are updated only with the add-on package and never from unsigned runtime data.

This is best-effort prevention. Unknown providers, shared HTTPS endpoints,
VPNs, proxies, and tunnels can bypass it. Broad HTTPS blocking is intentionally
not attempted because it would disrupt unrelated services.

## Applying changes

Saving performs server-side structural checks, generates a candidate runtime
file, invokes Blocky's own validator as the `blocky` user, atomically commits
the result, starts/restarts when necessary, verifies first activation health,
and finally reconciles firewall policy. A failure restores the previous
configuration; existing fail-closed policy stays active. Before a validated
candidate commits, the current documents are retained as one root-only
last-known-good snapshot in `/var/lib/blocky/last-known-good`.
