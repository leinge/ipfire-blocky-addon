# SPEC-0001: Initial IPFire Blocky add-on

| Field | Value |
| --- | --- |
| Status | Ready for implementation |
| Created | 2026-09-08 |
| Target | IPFire 2.29 / Core Update 203 and current `ipfire-2.x` packaging conventions |
| Blocky baseline | v0.35.0 |
| Supported architectures | `x86_64`, `aarch64` |
| Product owner decisions | Native five-area UI; full Blocky configuration; GREEN/BLUE interception; ports 53/853 and known-DoH bypass controls; fail closed |
| Research background | [`PROJECT.md`](PROJECT.md) |
| Internal register | [`docs/internal/specs/README.md`](docs/internal/specs/README.md) |

## 1. Purpose

Build an installable IPFire add-on that packages Blocky and gives an IPFire
administrator a native Web UI for configuring and operating it. The initial
version must support both an inert evaluation mode and an explicitly enabled,
network-wide enforcement mode for GREEN and BLUE.

The Web UI has five primary areas:

1. service enablement and status;
2. the full Blocky v0.35.0 configuration surface;
3. GREEN/BLUE zone selection;
4. transparent routing of conventional DNS from selected zones through
   Blocky; and
5. opt-in prevention of DNS bypass using direct DNS, DoT/DoQ, and a known-DoH
   provider catalog.

Knot Resolver remains installed and continues listening on IPFire's port 53.
Blocky listens on port 1053 and, by default, uses Knot at `127.0.0.1:53` as its
upstream. Network-wide use is implemented with firewall interception instead
of modifying Knot's generated configuration.

Enforcement is deliberately **fail closed**. Once a selected zone is routed
through Blocky or has DNS-bypass prevention enabled, a Blocky failure must not
silently return that zone to unfiltered Knot or external DNS. DNS remains
unavailable until Blocky recovers or a root administrator invokes the explicit
emergency recovery action.

## 2. Scope

### 2.1 In scope

- A Pakfire-compatible `blocky` add-on for `x86_64` and `aarch64`.
- Official Blocky v0.35.0 static release binaries, pinned by checksum.
- A native IPFire Perl CGI page and add-on menu entry.
- A version-pinned, schema-driven editor covering every supported,
  non-deprecated Blocky v0.35.0 configuration property.
- Import, validation, canonical storage, generation, backup, restore, and
  export of Blocky configuration.
- A dedicated unprivileged `blocky` service account and IPFire initscript.
- GREEN and BLUE listener/zone selection, including installations without a
  BLUE zone.
- Transparent interception of TCP and UDP port 53 from selected zones.
- Optional bypass prevention for TCP/UDP 53, TCP/UDP 853, known DoH endpoint
  domains, and known dedicated DoH destination addresses.
- Package-owned, persistent firewall chains which survive an IPFire firewall
  reload and reboot.
- Transactional apply and rollback behavior.
- Fail-closed operation after enforcement has been activated.
- A local root-only emergency command that removes enforcement and returns
  clients to IPFire's standard Knot path.
- Status, health, actionable errors, and security warnings in the UI.
- Pakfire install, update, uninstall, and IPFire backup/restore integration.
- Tests and administrator documentation for all supported modes.

### 2.2 Out of scope

- Replacing, stopping, reconfiguring, or patching Knot Resolver.
- Editing IPFire's generated Knot configuration.
- Reimplementing IPFire DNS Firewall or DHCP configuration.
- Advertising a DNS port other than 53 through DHCP; DHCP has no standard DNS
  server port field.
- Automatically exposing Blocky's HTTP, HTTPS, DoH, DoT, metrics, API, or
  profiling listeners through IPFire's firewall.
- Guaranteed detection of arbitrary DoH over shared HTTPS infrastructure.
- TLS interception, SNI inspection, application identification, or blocking
  all VPN/tunnel-based DNS bypass.
- IPv6 firewall enforcement on IPFire 2.x where no supported IPv6 zone
  firewall path exists. Blocky's IPv6-related configuration remains editable,
  but v1 makes no network-wide IPv6 enforcement claim.
- `riscv64`, because neither the selected Blocky release artifacts nor the
  current IPFire Go setup provide the required supported path.
- A third-party Pakfire repository or signing infrastructure.
- Building Blocky from source with IPFire's current Go 1.20.4 toolchain.
- A separate Blocky HTTP dashboard. The management UI is the IPFire Web UI.

## 3. Product behavior

### 3.1 Fresh installation

A fresh installation must be inert and must not change DNS behavior:

- the service is stopped and disabled at boot;
- no Blocky firewall chains or jumps enforce traffic policy;
- GREEN and BLUE are unselected;
- transparent routing is off;
- DNS-bypass prevention is off;
- Blocky's DNS listener is only `127.0.0.1:1053`;
- its default upstream is Knot at `127.0.0.1:53`;
- its HTTP, HTTPS, TLS, API, metrics, statistics, and query-log outputs are off;
  and
- no remote lists are configured or downloaded.

This default configuration must validate with the packaged Blocky binary.

### 3.2 Activation workflow

The intended administrator flow is:

1. Open **Services > Blocky**.
2. Configure Blocky features, upstreams, lists, clients, and any optional
   listeners.
3. Select GREEN and, if present, BLUE under **Zones**.
4. Save and validate the configuration.
5. Enable and start Blocky.
6. Confirm the local health check succeeds.
7. Opt selected zones into transparent DNS routing.
8. Optionally enable DNS-bypass prevention and select known DoH providers.
9. Apply the changes and acknowledge the fail-closed warning.
10. Test from a client in every selected zone.

The system must never install interception rules before a first successful
Blocky start and health check. After enforcement is successfully committed,
the rules remain in place during later restarts, crashes, failed health checks,
and firewall reloads.

### 3.3 UI area 1: Service and status

The overview must show:

- installed Blocky and add-on package versions;
- process state, boot-enabled state, PID, and effective runtime user;
- configuration validation state and last successful apply time;
- DNS health result for `healthcheck.blocky` on `127.0.0.1:1053`;
- selected zones and whether routing/bypass enforcement is active;
- a prominent **ENFORCEMENT ACTIVE / DNS FAILS CLOSED** indication;
- a critical alert when enforcement is active but Blocky is unhealthy;
- the most recent bounded validation, service, or firewall error; and
- controls for validate, start, stop, restart, enable at boot, and disable at
  boot.

The UI must refuse an ordinary stop or boot-disable operation while routing or
bypass enforcement is active. It must direct the administrator to disable
enforcement first. A process may still fail or be stopped from a root shell;
in that case firewall policy remains fail closed.

Starting and boot-enabling are separate concepts. The UI may offer a combined
"Enable and start" convenience action, but status must report both states
accurately.

### 3.4 UI area 2: Full Blocky configuration

"Full Blocky feature set" means every supported, non-deprecated property in
the schema shipped with Blocky v0.35.0 is editable, resettable, validated, and
round-trippable. The UI must not maintain a manually incomplete list of fields.
It must render from a vendored copy of the exact release's
`docs/config.schema.json`, supplemented by a small package-owned UI descriptor
for ordering, widgets, sensitive values, and integration-owned fields.

The guided editor must group the schema into understandable sections:

| Section | Blocky configuration covered |
| --- | --- |
| Upstreams | `upstreams`, initialization strategy, groups, selection strategy, timeouts, QUIC, user agent, `connectIPVersion`, `bootstrapDns` |
| Local DNS | `customDNS`, `conditional`, `hostsFile` |
| Blocking | deny/allow list groups, inline/local/remote sources, client assignments, schedules, block response and TTL, list loading/download/cache behavior |
| Clients | `clientLookup`, static client names, reverse lookup behavior |
| Cache and shared state | `caching`, `redis` including Sentinel settings |
| Logging and telemetry | `log`, `queryLog`, ignore rules, retention, output types, `prometheus`, `statistics` |
| Listeners and TLS | HTTP/HTTPS/TLS listeners, DoH path, certificate/key, minimum TLS, free-bind, proxy protocol, `http3` |
| Resolver policy | `fqdnOnly`, `filtering`, `ede`, `specialUseDomains`, `rebindingProtection`, `rateLimit`, `ecs`, `dnssec`, `dns64` |

Requirements for the configuration editor:

- Dynamic maps and arrays must support add, edit, delete, and reorder where
  order is meaningful.
- Durations, ports, IP addresses, CIDRs, URLs, domain patterns, weekdays,
  enumerations, certificate paths, and numeric ranges must receive appropriate
  controls and validation hints.
- Arbitrary mapping keys required by upstream groups, domain mappings, clients,
  and list groups must be supported safely.
- Multiline content must support zone files and inline list sources.
- Secrets such as Redis and database credentials must use masked controls,
  must not be written to logs, and a blank unchanged field must preserve the
  existing secret.
- The UI must provide an advanced canonical JSON editor. JSON is valid YAML and
  has been verified with Blocky v0.35.0. Changes in guided and advanced modes
  operate on the same in-memory document.
- The UI may import YAML or JSON. YAML import must use a safe loader, reject
  custom object tags and duplicate keys, normalize the result to JSON, and
  warn that comments/formatting are not preserved.
- Export is redacted by default. Exporting secrets requires a separate explicit
  acknowledgement and must set download headers that prevent caching.
- Deprecated v0.35.0 compatibility aliases may be accepted during import and
  migrated, but they are not displayed as normal editable fields.
- Unknown properties must cause a clear validation error rather than being
  silently discarded.
- Client-side schema checks improve usability but are never the trust boundary.
  The candidate must also pass privileged structural checks and
  `blocky --config <candidate> validate` on the appliance.
- A failed validation must leave the active model, generated configuration,
  service, and firewall rules unchanged.

`ports.dns` is integration-owned. Its complete capability is represented by
the Zones and Routing areas, and the generated value is always port 1053 on
loopback plus the selected IPFire zone addresses. It is shown read-only in the
schema editor. All other current listener fields remain editable, but receive
strong exposure warnings and never cause automatic firewall openings.

The package reserves configuration names beginning with `_ipfire_blocky_` for
generated enforcement overlays. User configuration must not define names with
that prefix.

### 3.5 UI area 3: GREEN/BLUE zones

The Zones area must:

- always show GREEN using current IPFire interface, address, network, and mask
  settings;
- show BLUE only when IPFire reports it configured;
- never show RED or ORANGE as selectable in v1;
- permit GREEN and BLUE to be selected independently;
- show the generated Blocky listener for each selection;
- update the generated listener addresses if IPFire's zone address changes;
- always retain `127.0.0.1:1053` for health and local testing; and
- explain that selection permits Blocky to serve that zone but does not itself
  redirect port 53 traffic.

Removing a zone while it has routing or bypass prevention enabled must be
rejected until those policies are disabled for the zone.

### 3.6 UI area 4: Transparent DNS routing

For each selected zone, an administrator may enable **Force conventional DNS
through Blocky**. The control applies to both TCP and UDP port 53 regardless of
the destination address chosen by a client.

When enabled:

- packets arriving from the selected zone on TCP/UDP destination port 53 are
  redirected to Blocky on local port 1053;
- Blocky sees the original client source address;
- Blocky's own upstream traffic is not intercepted because it originates from
  the IPFire host rather than a forwarded zone client;
- direct queries to the IPFire address and attempts to use external resolvers
  follow the same Blocky path; and
- Knot remains available to Blocky at `127.0.0.1:53`.

Rules must match the current IPFire zone interface rather than trusting only a
source CIDR. RED traffic must never match. Routing can be active without the
optional port-853/known-DoH bypass policy.

### 3.7 UI area 5: DNS-bypass prevention

DNS-bypass prevention is opt-in and configured per selected zone. It may be
enabled only when transparent routing is enabled for that zone.

When enabled, the package must:

- retain transparent interception of all TCP/UDP port 53;
- reject any defensive fall-through forwarded TCP/UDP port-53 traffic;
- reject forwarded TCP and UDP port 853, covering conventional DoT and DoQ;
- block configured known DoH endpoint domains through a package-managed Blocky
  denylist group;
- reject TCP and UDP port 443 to configured known, dedicated DoH destination
  addresses using a package-owned IP set; and
- support package catalog entries, administrator-added endpoint domains/CIDRs,
  provider deselection, and explicit destination exceptions.

The v1 provider catalog must include at least Cloudflare, Google, Quad9,
AdGuard, and NextDNS where maintainable endpoint domains or dedicated resolver
addresses can be sourced. Every entry must include a stable ID, display name,
source/provenance note, domain list, IPv4 networks, optional future IPv6
networks, and a shared-hosting risk flag.

Catalog data ships with the add-on and changes only through a package update;
the appliance must not download unsigned firewall policy. The implementation
must prefer provider-published endpoint information. It must not include a
shared CDN address merely because a DoH hostname currently resolves there.

Known-DoH enforcement is explicitly best effort:

- generic HTTPS cannot reliably be classified as DoH without inspecting
  encrypted application traffic;
- endpoint IPs change;
- clients may use unknown providers, hard-coded addresses, VPNs, proxies, or
  tunnels; and
- blocking shared addresses can disrupt unrelated HTTPS.

The UI must display those limitations before activation. It must provide a
provider test view showing the exact domain and network rules to be applied.
Unrelated TCP/UDP 443 traffic must not be broadly blocked.

To add the managed domain group without changing user intent, the generated
configuration overlays a denylist named `_ipfire_blocky_doh_bypass` and adds
that group to a `clientGroupsBlock` CIDR entry for each enforced zone. Blocky
collects matching CIDR and client-name groups together, so user-defined client
groups continue to apply. The overlay is generated only in the runtime file;
it is not written into the user's canonical Blocky document.

## 4. Functional requirements

### 4.1 Packaging

- **PKG-001:** The package name is `blocky`, with `PROG = blocky` and
  `SERVICES = blocky` in its IPFire LFS recipe.
- **PKG-002:** `SUP_ARCH` is exactly `aarch64 x86_64` for v1.
- **PKG-003:** The recipe pins Blocky v0.35.0 architecture-specific official
  release archives and BLAKE2b-512 checksums recorded in `PROJECT.md`.
- **PKG-004:** The binary architecture, embedded version, static linkage,
  archive layout, upstream checksum, and Apache 2.0 license are verified during
  release preparation.
- **PKG-005:** The package installs the binary, license, configuration assets,
  schema, UI descriptor, DoH provider catalog, CGI/UI assets, language file,
  initscript, privileged controller, firewall helper, menu entry, backup
  include, and lifecycle scripts.
- **PKG-006:** No Blocky runtime library dependency is introduced. Any
  configuration-import dependency already provided by IPFire, such as
  `python3-yaml`, must be verified on target images or declared explicitly.
- **PKG-007:** The package rootfile contains every owned file and no generated
  runtime state.

### 4.2 Web UI and management

- **UI-001:** The page is an authenticated native IPFire CGI available from
  the Services menu.
- **UI-002:** It follows current IPFire header, navigation, box, status, error,
  color, and language conventions.
- **UI-003:** All mutations use POST, bounded request bodies, server-side
  validation, output escaping, and the platform's anti-CSRF mechanism where
  available.
- **UI-004:** No user-controlled value is interpolated into a shell command.
- **UI-005:** Privileged actions are a fixed allowlist implemented through a
  small setuid controller following IPFire's `*ctrl` convention. The CGI cannot
  supply arbitrary executable paths or command fragments.
- **UI-006:** UI JavaScript and styles are packaged locally; no CDN dependency
  is allowed.
- **UI-007:** Core labels, warnings, errors, and help text use IPFire's add-on
  language mechanism. English is mandatory for v1; schema field descriptions
  may use the pinned upstream English text.
- **UI-008:** The editor remains usable without relying solely on color and
  associates controls and errors with accessible labels.

### 4.3 Configuration management

- **CFG-001:** The canonical user model and integration settings are stored
  separately.
- **CFG-002:** The runtime `/etc/blocky/config.yml` is generated, begins with a
  do-not-edit comment, and contains deterministic pretty-printed JSON, which is
  valid YAML.
- **CFG-003:** Generation overlays integration-owned DNS listeners and managed
  DoH blocking without mutating the canonical user model.
- **CFG-004:** `upstreams.groups.default` must exist and contain at least one
  resolver before apply.
- **CFG-005:** Apply is serialized with a lock and uses same-filesystem atomic
  replacement.
- **CFG-006:** A candidate is size-limited, opened without following symlinks,
  parsed safely, structurally checked, rendered to a temporary root-owned file,
  and validated by the packaged Blocky binary as the `blocky` user.
- **CFG-007:** Successful configuration and integration changes create a
  bounded last-known-good snapshot before commit.
- **CFG-008:** If a restart with a new configuration fails, the controller
  restores the previous generated configuration and attempts to restart the
  previous state. Enforcement rules remain active throughout.
- **CFG-009:** Comments and formatting from imported YAML need not round-trip;
  semantic values must.
- **CFG-010:** Sensitive values never appear in process arguments, CGI errors,
  syslog, health output, or redacted exports.

### 4.4 Service

- **SVC-001:** Blocky runs as a locked `blocky` system user with no interactive
  shell and no writable configuration directory.
- **SVC-002:** The init script implements start, stop, restart, status, and a
  truthful unsupported/restart-based reload behavior. It never treats
  `SIGUSR1` as configuration reload.
- **SVC-003:** Start validates the active configuration before launching and
  uses IPFire's standard process helpers.
- **SVC-004:** Stop sends `SIGTERM` and allows Blocky's graceful shutdown
  interval before escalating.
- **SVC-005:** DNS health is checked on loopback using
  `healthcheck.blocky:1053` without depending on an external upstream answer.
- **SVC-006:** The service does not need `CAP_NET_BIND_SERVICE` for managed DNS
  port 1053. If an administrator configures another Blocky listener below 1024,
  the UI must reject it unless a separately reviewed capability policy exists;
  v1 does not grant that capability by default.
- **SVC-007:** Normal service stop/disable through the Web UI is blocked while
  enforcement is active.

### 4.5 Firewall and enforcement

- **FW-001:** All package rules live in uniquely named package chains and
  package-owned IP sets. The helper modifies only those resources and its own
  jump rules.
- **FW-002:** The initial chain names fit iptables chain-length limits; use a
  stable namespace such as `BLOCKY_PRE`, `BLOCKY_IN`, and `BLOCKY_FWD`.
- **FW-003:** Jumps are inserted idempotently into IPFire's
  `CUSTOMPREROUTING`, `CUSTOMINPUT`, and `CUSTOMFORWARD` chains at a documented
  priority.
- **FW-004:** Firewall operations use `iptables --wait`; IP sets are populated
  into a temporary set and atomically swapped.
- **FW-005:** The package registers one clearly marked, idempotent invocation
  in `/etc/sysconfig/firewall.local` so its rules are restored after IPFire
  firewall reloads. Existing user content is preserved byte-for-byte outside
  the package's begin/end markers.
- **FW-006:** Install refuses to alter an ambiguous or malformed existing
  package marker. Update never duplicates it. Uninstall removes only the
  package marker after removing package rules.
- **FW-007:** Routing rules match selected GREEN/BLUE ingress interfaces and
  both TCP/UDP port 53, redirecting to 1053.
- **FW-008:** Selected-zone access to the generated 1053 listeners is allowed;
  RED and unselected zones are not opened.
- **FW-009:** Bypass rules match only selected enforced zone traffic in the
  forwarding path. They do not block Blocky's or Knot's locally generated
  upstream traffic.
- **FW-010:** RED can never become a source zone through UI data, imported
  settings, crafted CGI input, or direct controller invocation.
- **FW-011:** Rule apply is idempotent and restores the exact desired state
  after repeated apply, firewall reload, RED reconnect, and reboot.
- **FW-012:** Once active, route and bypass rules remain installed when Blocky
  is stopped, crashes, fails health checks, or cannot restart. This is the
  required fail-closed behavior.
- **FW-013:** A first activation orders operations as validate -> start ->
  health check -> firewall commit. A failure before firewall commit leaves the
  previous policy unchanged.
- **FW-014:** A normal policy disable removes bypass rules first, removes
  routing last, verifies Knot answers on port 53, and then permits service stop.
- **FW-015:** Current v1 enforcement targets IPFire's supported IPv4 zone
  firewall. The UI must not state that IPv6 or arbitrary encrypted tunnels are
  covered.

### 4.6 Fail-closed recovery

- **REC-001:** The UI prominently documents that a Blocky failure causes DNS
  loss for enforced zones.
- **REC-002:** A root-only local-console command can atomically disable all
  Blocky enforcement, remove the package chains/jumps/IP sets, persist routing
  and bypass settings as off, and verify Knot on port 53.
- **REC-003:** The recovery action must be callable without the Web UI, DNS, or
  network connectivity and must print what it changed.
- **REC-004:** Recovery never deletes the user's Blocky configuration or lists.
- **REC-005:** Reboot must not silently re-enable enforcement after the
  recovery action unless the administrator enables it again.
- **REC-006:** The recovery command and the consequences of `addonctrl blocky
  stop` while enforced are included in install/admin documentation.

### 4.7 Backup, update, and uninstall

- **LIFE-001:** IPFire backup includes canonical user configuration,
  integration settings, custom DoH entries/exceptions, and TLS material kept
  under the package's documented configuration root.
- **LIFE-002:** Ephemeral caches, PID/lock files, health state, provider-derived
  IP sets, and query logs are excluded by default.
- **LIFE-003:** Query-log/database paths outside the configuration root receive
  an explicit warning that the standard add-on backup does not include them.
- **LIFE-004:** Update preserves configuration, service boot state, desired
  enforcement, custom provider data, and secrets.
- **LIFE-005:** During an enforced update, firewall rules remain fail closed.
  The new binary validates the old configuration before being started.
- **LIFE-006:** If an update cannot start Blocky, the package attempts a
  last-known-good binary/configuration rollback; if recovery fails, it leaves
  enforcement active and emits a critical local/UI error.
- **LIFE-007:** Uninstall explicitly stops Blocky, removes enforcement, verifies
  the Knot path, unregisters the firewall hook, backs up configuration through
  Pakfire conventions, and removes only package-owned files.
- **LIFE-008:** The system user is retained on uninstall unless IPFire
  maintainer policy explicitly requires removal, preventing UID reuse against
  retained files.

## 5. Architecture

### 5.1 Data path

```text
Selected GREEN/BLUE client
        |
        | TCP/UDP 53, any destination
        v
IPFire CUSTOMPREROUTING -> BLOCKY_PRE -> REDIRECT :1053
        |
        v
Blocky (original client source IP retained)
        |
        | default configuration
        v
Knot Resolver 127.0.0.1:53 -> configured IPFire upstream DNS
```

When bypass prevention is active, `BLOCKY_FWD` rejects forwarded port 853 and
known DoH destinations on port 443. A generated Blocky denylist additionally
blocks known provider domains for clients in the selected zone CIDRs.

### 5.2 Control plane components

| Component | Responsibility | Privilege |
| --- | --- | --- |
| `blocky.cgi` | Render the five areas, accept bounded POST actions, write an unprivileged candidate, display status/errors | IPFire CGI user (`nobody`) |
| Packaged schema UI JavaScript | Render nested v0.35.0 schema fields, maintain guided/advanced views, perform client-side validation | Browser, authenticated WUI session |
| `blockyctrl` | Allowlisted setuid entry point for validate/apply/service/firewall/recovery/status actions | Raises only for fixed operations |
| Root-owned management helper | Parse candidate/settings, enforce invariants, generate configuration, validate, transact files, control service and firewall | Root, never directly writable by CGI user |
| `blocky` initscript | Start, stop, restart, and report service using IPFire helpers | Root control; daemon drops to `blocky` |
| Firewall helper | Own `BLOCKY_*` chains, DoH IP set, and desired-state reconciliation | Root |
| Blocky binary | Serve and filter DNS | `blocky` user |
| Knot Resolver | Default Blocky upstream and existing IPFire DNS integration | Existing `knot-resolver` user |

The privileged controller must be small and auditable. Complex parsing belongs
in a root-owned non-setuid helper invoked with constant command paths and
allowlisted action names. User strings are transferred through fixed files,
not command-line fragments.

### 5.3 Configuration ownership and merge

The add-on maintains three layers:

1. **Canonical user Blocky document:** every schema-backed Blocky value the
   administrator selected.
2. **IPFire integration settings:** service intent, selected zones, per-zone
   routing, bypass toggles, provider choices, custom endpoints, and exceptions.
3. **Generated runtime document:** a deterministic merge of the canonical
   document with protected `ports.dns` and `_ipfire_blocky_*` overlays.

The canonical and integration documents are the backup source of truth. The
runtime file is reproducible and must never be parsed back as authoritative
state. This avoids leaking generated enforcement entries into the user's
configuration or losing them when the user edits Blocky features.

Proposed appliance paths:

```text
/usr/bin/blocky
/usr/local/bin/blockyctrl
/usr/lib/blocky/blocky-manager
/usr/lib/blocky/blocky-firewall
/usr/share/blocky/config.schema.json
/usr/share/blocky/ui-descriptor.json
/usr/share/blocky/doh-providers.json
/usr/share/licenses/blocky/LICENSE
/srv/web/ipfire/cgi-bin/blocky.cgi
/srv/web/ipfire/html/include/blocky.js
/var/ipfire/menu.d/EX-blocky.menu
/var/ipfire/addon-lang/blocky.en.pl
/var/ipfire/blocky/config.json
/var/ipfire/blocky/settings.json
/var/ipfire/blocky/doh-custom.json
/var/ipfire/blocky/pending/candidate.json
/var/ipfire/blocky/status.json
/var/ipfire/backup/addons/includes/blocky
/etc/blocky/config.yml
/etc/rc.d/init.d/blocky
/var/cache/blocky/lists/
/var/lib/blocky/
/var/log/blocky/
/run/blocky/
```

Final names may follow a stronger current IPFire convention discovered during
implementation, but ownership boundaries and responsibilities must not change.

### 5.4 Permissions

- `/etc/blocky/config.yml` and TLS/private configuration are `root:blocky`, mode
  `0640` or stricter.
- The `blocky` user may write only declared cache, state, log, and runtime
  directories.
- Canonical management documents are readable by the CGI through a restricted
  group/mode but replaceable only through the privileged transaction.
- The pending directory is the only CGI-writable package state. The controller
  opens its fixed candidate with no symlink following, verifies owner/type/mode
  and a maximum size, copies it into a root-owned temporary file, then removes
  it.
- Status returned to the CGI is sanitized and contains no secrets.
- Provider catalogs and UI schemas are root-owned and immutable to the CGI and
  daemon users.

### 5.5 Transaction and state model

| State | Service | Route rules | Bypass rules | Expected client DNS |
| --- | --- | --- | --- | --- |
| Inert | stopped/disabled | off | off | Knot behaves normally |
| Ready | healthy | off | off | Knot behaves normally; Blocky can be tested on 1053 |
| Routed | healthy | on for selected zones | off | Port 53 flows through Blocky; other encrypted DNS may bypass |
| Enforced | healthy | on | on | Blocky is the intended DNS path; known bypass paths rejected |
| Enforced-down | unhealthy/stopped | remain on | remain on | DNS fails closed for selected zones |
| Recovered | optional | off | off | Knot behaves normally; persisted enforcement is off |

An apply operation is one transaction:

1. acquire the package lock;
2. read and validate the fixed candidate and current IPFire zone state;
3. generate a root-owned candidate runtime document;
4. run Blocky validation as the daemon user;
5. snapshot the active canonical/integration/runtime documents;
6. atomically commit the new documents;
7. start/restart Blocky when needed;
8. require a successful local health check before first enforcement activation;
9. reconcile firewall rules to the new desired state; and
10. write sanitized status and release the lock.

For updates while already enforced, the firewall remains enforced during steps
3-9. If the new runtime fails, restore the last-known-good document and restart
it; never remove policy as an automatic error response.

### 5.6 Firewall persistence

The package must not overwrite `/etc/sysconfig/firewall.local`. It registers a
short block between unique comments which invokes the package firewall helper
with `start`, `stop`, or `reload`. Registration and removal use atomic file
replacement and preserve mode, ownership, and all bytes outside the markers.

The helper creates and reconciles package chains beneath IPFire's existing
custom chains. It must tolerate chains being absent after a full firewall
restart, repeated callbacks, partially populated IP sets, missing BLUE, and
stale interface/address data. Reconciliation always reads persisted desired
state and current IPFire network settings.

If IPFire maintainers provide or require a composable firewall hook directory,
implementation should use that official hook instead; the behavior and tests
in this specification remain the same.

### 5.7 DoH catalog model

The catalog is versioned data, separate from code. A provider record contains:

- stable provider ID and display name;
- authoritative/source reference and last-reviewed date;
- endpoint domain patterns;
- dedicated IPv4 CIDRs and optional IPv6 CIDRs;
- transport notes;
- whether an address may be shared with non-DNS services; and
- enabled-by-default eligibility.

Shared-hosting entries are never enabled by default and require an extra UI
warning. Custom entries and exceptions are stored separately so a package
catalog update cannot overwrite them. The firewall helper resolves no provider
hostname into a blocking IP automatically; only reviewed catalog/custom CIDRs
enter the IP set.

## 6. Repository and internal documentation structure

The implementation repository should mirror IPFire integration paths under a
clear packaging root while keeping project-only tools and docs separate:

```text
spec.md                              active implementation specification
PROJECT.md                           research and product background
docs/
  internal/
    specs/
      README.md                      specification register and lifecycle
      NNNN-short-title.md            immutable completed/superseded specs
  admin/
    installation.md
    configuration.md
    enforcement-and-recovery.md
packaging/
  ipfire/                            overlay matching ipfire-2.x paths
tests/
  unit/
  integration/
  fixtures/
tools/                               build/staging/release helpers
```

`spec.md` is the canonical active spec required by the project workflow and is
registered as SPEC-0001 in `docs/internal/specs/README.md`. When implementation
is accepted, archive its final contents as
`docs/internal/specs/0001-initial-ipfire-blocky-addon.md`, mark it Implemented
in the register, and reserve root `spec.md` for the next active spec. Archived
specifications are immutable; corrections are follow-up specs which link to
the spec they amend or supersede.

The packaging overlay must preserve the relative paths expected by
`ipfire-2.x`, including the LFS recipe, rootfile, backup include, CGI, menu,
language data, initscript, controller source/build registration, and Pakfire
lifecycle scripts. A staging/check script copies or verifies that overlay in a
pinned IPFire checkout without keeping an entire IPFire source tree in this
repository.

## 7. Implementation plan

### Step 1: Establish the repository scaffold

- Create the packaging overlay, tools, tests, admin docs, fixtures, and internal
  docs directories described above.
- Add a pinned IPFire baseline manifest and a staging verifier; do not vendor
  the full IPFire tree.
- Add formatting, static checks, and a test entry point that can run outside a
  full IPFire build where possible.
- Record all third-party licenses and provenance.

### Step 2: Package the Blocky release

- Implement architecture-specific v0.35.0 download objects and recorded BLAKE2
  checksums in `lfs/blocky`.
- Validate archive shape and install `/usr/bin/blocky` plus the Apache license.
- Add `SUP_ARCH`, `SERVICES`, metadata, build ordering, and curated rootfile.
- Install the inert default configuration and required directories with exact
  permissions.
- Verify the package on both target architectures.

### Step 3: Implement canonical configuration management

- Vendor the v0.35.0 JSON Schema and create a small UI descriptor.
- Define JSON formats and migrations for canonical config, integration
  settings, DoH custom data, and sanitized status.
- Implement safe YAML/JSON import, deterministic JSON-as-YAML generation,
  reserved-name checks, listener overlay, managed DoH group overlay, atomic
  writes, lock handling, last-known-good snapshots, and size limits.
- Validate fixtures covering every non-deprecated schema path against Blocky.

### Step 4: Implement service isolation and control

- Add user/group creation, directory ownership, initscript, graceful process
  control, boot links, and loopback health checking.
- Build the small allowlisted setuid controller and root-owned management
  helper.
- Implement status/error serialization without secrets.
- Implement root-only emergency enforcement removal.

### Step 5: Implement firewall integration

- Define desired-state reconciliation for package chains, jumps, and IP sets.
- Add per-zone TCP/UDP 53 interception and input allowance.
- Add per-zone fall-through 53 rejection, TCP/UDP 853 rejection, and selective
  known-DoH TCP/UDP 443 rejection.
- Add the reviewed provider catalog, custom entries, exceptions, and generated
  Blocky domain group.
- Register the marked `firewall.local` callback atomically and idempotently.
- Exercise initial activation ordering, normal disable ordering, firewall
  reload, RED reconnect, reboot, service crash, and emergency recovery.

### Step 6: Implement the native Web UI

- Add the menu entry, language data, CGI page, local assets, and schema-driven
  guided/advanced editor.
- Implement the five primary areas and cross-area dependencies.
- Add validation, diff/preview, exact firewall-rule/provider preview,
  confirmation for fail-closed activation, redacted export, import, and clear
  error handling.
- Ensure the UI cannot select RED/ORANGE, cannot stop an enforced service, and
  never renders secrets into page source or errors.

### Step 7: Implement Pakfire lifecycle and backup

- Add custom install, update, and uninstall scripts.
- Preserve configuration, provider customizations, enablement, enforcement,
  and last-known-good data as specified.
- Keep enforcement fail closed during update; implement binary/config rollback.
- Remove rules and the exact firewall hook safely during uninstall.
- Add and test the backup include and restore flow.

### Step 8: Test in IPFire environments

- Run unit tests for parsing, merging, migrations, redaction, permissions,
  provider data, firewall desired state, marker editing, and command allowlists.
- Build clean `.ipfire` packages for `x86_64` and `aarch64`.
- Use IPFire test VMs with GREEN and GREEN+BLUE topologies and separate client
  namespaces/VMs.
- Verify UDP/TCP, original client identity, list policies, encrypted bypass,
  fail-closed behavior, firewall persistence, backup/restore, upgrade,
  uninstall, and recovery.
- Conduct a security review of the CGI/setuid boundary before release.

### Step 9: Finish operator documentation and release evidence

- Document installation, the five UI areas, Blocky feature mapping, provider
  catalog limitations, failure semantics, testing commands, and emergency
  recovery.
- Publish the architecture/build matrix, exact checksums, rootfile diff, test
  evidence, and known limitations with the release artifact.
- Seek IPFire maintainer feedback on binary provenance, firewall hook usage,
  UI conventions, UID allocation, and package distribution before proposing
  official inclusion.

## 8. Verification matrix

### 8.1 Configuration/UI

- Every non-deprecated v0.35.0 schema field has a generated editable control or
  an explicitly equivalent integration control.
- A fixture exercising every schema section round-trips semantic values through
  guided edit, advanced edit, export, import, save, and reload.
- Valid advanced Blocky combinations pass; invalid types, references,
  duplicate keys, missing default upstream, malformed durations/CIDRs, unknown
  keys, and reserved names fail clearly.
- Secrets are absent from HTML, logs, errors, status JSON, process lists, and
  normal exports.
- A malformed or oversized pending file, symlink, unexpected owner, and
  concurrent apply are rejected without changing active state.

### 8.2 Service and package lifecycle

- Fresh install is inert and Knot port 53 is unchanged.
- Service start/stop/restart/status and boot enable/disable work while
  enforcement is off.
- Invalid active configuration prevents start.
- `SIGTERM` produces a graceful shutdown; a forced crash is detected in status.
- Pakfire update preserves settings and enforcement; rollback behavior is
  exercised.
- Backup/restore produces the same semantic configuration and custom provider
  policy without restoring cache/log/runtime data.
- Uninstall restores normal Knot client DNS and leaves unrelated firewall.local
  content unchanged.

### 8.3 GREEN/BLUE routing

- GREEN-only systems never display or reference a nonexistent BLUE device.
- On GREEN+BLUE systems, each zone can be selected and routed independently.
- TCP and UDP queries to the IPFire address and an arbitrary external port-53
  destination are intercepted for selected routed zones.
- Identical traffic from an unselected zone is not affected by package rules.
- Blocky records the original client address, not IPFire's loopback address.
- Blocky's default upstream request reaches Knot without a loop.
- RED-originated traffic never reaches a generated Blocky listener through
  package rules.

### 8.4 Bypass prevention

- TCP/UDP 53 is intercepted or defensively rejected for an enforced zone.
- TCP 853 and UDP 853 are rejected for an enforced zone and unaffected for an
  unenforced zone.
- Selected provider domains receive Blocky's configured block response.
- Connections to selected dedicated DoH addresses on TCP/UDP 443 are rejected.
- A configured provider/address exception works.
- Ordinary HTTPS and QUIC to destinations outside the provider IP set continue
  to work.
- Provider catalog refresh through a package update preserves custom entries,
  exceptions, and selections.
- The UI and docs never claim that unknown/shared-host DoH or tunneled DNS is
  comprehensively blocked.

### 8.5 Fail-closed and recovery

- After enforcement activation, `SIGKILL`, startup failure, invalid replacement
  configuration, and health-check failure do not remove route/bypass rules.
- With Blocky down, selected clients cannot fall back to Knot, external port
  53, port 853, or selected known DoH endpoints.
- A firewall reload, RED reconnect, and reboot reconstruct desired enforcement.
- The Web UI shows an enforced-down critical condition when reachable.
- The documented root-console recovery command works without DNS/network/WUI,
  removes enforcement persistently, verifies Knot, and preserves Blocky config.

## 9. Success criteria

The initial version is complete only when all of the following are true:

1. Clean IPFire builds produce installable `blocky` packages for `x86_64` and
   `aarch64` from pinned v0.35.0 artifacts.
2. Fresh installation makes no DNS, service, listener, or firewall behavior
   change until the administrator opts in.
3. The native IPFire UI exposes the five agreed areas and accurately reports
   active, routed, enforced, unhealthy, and recovery states.
4. Automated schema coverage proves every supported non-deprecated Blocky
   v0.35.0 property is editable or represented by an equivalent protected
   integration control.
5. Candidate configuration is validated and applied transactionally; failed
   changes do not corrupt or partially replace the last-known-good state.
6. GREEN and BLUE can be independently routed through Blocky without changing
   Knot and without exposing the service to RED.
7. Selected-zone TCP/UDP 53 interception preserves client identity and cannot
   loop Blocky's upstream request.
8. Opt-in bypass prevention covers ports 53 and 853 plus the selected known-DoH
   catalog/custom entries, while unrelated HTTPS continues to work.
9. Enforcement survives service failure, firewall reload, RED reconnect, and
   reboot and fails closed exactly as specified.
10. Root-console recovery reliably returns clients to Knot and persists the
    disabled enforcement state.
11. Install, update, backup/restore, rollback, and uninstall pass on both target
    architectures without losing settings or altering unrelated system files.
12. The CGI, setuid controller, file permissions, secret handling, imported
    configuration, and firewall inputs pass a focused security review.
13. Administrator documentation clearly explains activation, limitations,
    fail-closed consequences, provider false-positive risk, testing, and
    emergency recovery.

## 10. Known risks and required implementation safeguards

| Risk | Required safeguard |
| --- | --- |
| DNS outage under fail-closed policy | Explicit acknowledgement, critical status, last-known-good rollback, local root recovery command, recovery documentation |
| Incorrect firewall rule affects RED or unrelated traffic | Interface-derived allowlist, hard rejection of RED/ORANGE, dedicated chains, exact integration tests |
| DoH IP false positives | Reviewed dedicated addresses only, shared-hosting flag, provider preview, exceptions, no broad port-443 block |
| Unknown DoH bypass | Accurate best-effort wording; domain and dedicated-IP layers; no false completeness claim |
| Blocky/Knot loop | Protected managed listener; loopback Knot default; test every generated upstream/listener combination |
| Schema/UI drift on Blocky update | Version-pinned schema, automated coverage, explicit migration per Blocky version |
| Privilege escalation through CGI | Fixed-file handoff, small allowlisted setuid wrapper, no shell interpolation, strict ownership/type/size checks |
| Secret disclosure | Masked fields, preserved blank values, redacted exports, sanitized status/errors, restrictive files |
| Corruption during apply/power loss | Locking, fsync where appropriate, same-filesystem atomic rename, last-known-good snapshots |
| User firewall.local damage | Marker-scoped atomic edits, ambiguity refusal, byte-preservation tests, remove only owned block |
| Binary-only package rejected upstream | Maintainer alignment before official submission; retain source-build strategy as a separate future platform effort |

## 11. Definition of ready

This specification is ready for implementation because the product choices
which alter architecture are resolved:

- the five UI areas are fixed;
- the full v0.35.0 configuration schema is in scope;
- GREEN and BLUE are the only v1 client zones;
- conventional DNS routing is transparent and uses local port 1053;
- bypass prevention includes ports 53/853 and known DoH providers;
- DoH enforcement is best effort and catalog-driven; and
- active enforcement fails closed, with explicit root-console recovery.

Implementation discoveries may refine filenames or use a newer official
IPFire hook, but changing these decisions or the success criteria requires a
follow-up specification.
