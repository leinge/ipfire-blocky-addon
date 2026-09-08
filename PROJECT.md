# Blocky add-on for IPFire

Project research and proposed direction, captured on **2026-09-08**.

## Executive summary

The smallest safe first version is an IPFire add-on that installs Blocky as an
independent, disabled-by-default service. It should:

- package the official, statically linked Blocky binary for `x86_64` and
  `aarch64`;
- run it as a dedicated, unprivileged `blocky` user, adding only
  `CAP_NET_BIND_SERVICE` if privileged-port support is deliberately retained;
- install an IPFire initscript, Pakfire lifecycle scripts, a backup include,
  the Apache 2.0 license, and a deliberately minimal configuration;
- listen only on `127.0.0.1:1053` in the supplied configuration;
- use IPFire's resolver at `127.0.0.1:53` as its initial upstream;
- leave Blocky's HTTP endpoint disabled and query logging off; and
- make no changes to IPFire's resolver, DHCP, Web UI, or firewall.

This is intentionally useful as an evaluation package rather than silently
changing a firewall's DNS behavior. An administrator can test it with
`dig @127.0.0.1 -p 1053 example.org`, then choose an integration topology.

The reason for that caution is important: current IPFire already runs Knot
Resolver on all interfaces on port 53. Installing a default Blocky
configuration and auto-starting it would create an immediate port conflict.
Replacing or inserting Blocky into IPFire's DNS path also has consequences for
IPFire's DNS Firewall, Safe Search, DHCP hostname resolution, local overrides,
conditional forwarding, and client identity inside Blocky.

There is also a packaging-policy decision to settle. Repackaging upstream's
static release binaries is pragmatic and works with today's IPFire toolchain.
Building Blocky v0.35.0 from source does not: Blocky requires Go 1.26.2, while
the current IPFire build recipe provides Go 1.20.4. Before proposing the add-on
upstream, ask IPFire maintainers whether official upstream binaries are
acceptable or whether they require an in-tree source build and vendored Go
dependencies.

## Goals and non-goals

### Initial goals

- Produce a normal IPFire `.ipfire` add-on archive named `blocky`.
- Preserve Pakfire install, update, uninstall, backup, service, and boot-toggle
  conventions.
- Supply safe defaults that coexist with an unmodified IPFire installation.
- Keep the package easy to inspect, reproduce, update, and test.
- Establish a base on which deeper DNS integration can be designed later.

### Initial non-goals

- Do not replace Knot Resolver or take over port 53 automatically.
- Do not patch IPFire's generated Knot Resolver configuration.
- Do not expose Blocky's HTTP API, Prometheus metrics, DoH, or profiling
  endpoints to a LAN or the internet.
- Do not modify firewall rules, DHCP integration, or the IPFire Web UI.
- Do not promise client-specific policies when another resolver is forwarding
  all requests from localhost.
- Do not create a third-party package repository as part of the first package.

## Research baseline

These findings are version-sensitive:

| Component | Baseline inspected | Relevant fact |
| --- | --- | --- |
| IPFire | `ipfire-2.x` master at `f4f4c04a`, 2026-08-08 | Development tree reports Core Update 204; Core Update 203 is the current stable release. |
| IPFire stable | IPFire 2.29 Core Update 203, 2026-07-20 | Knot Resolver replaced Unbound and owns the standard DNS service. |
| Blocky | v0.35.0, released 2026-09-05 | Latest release at research time. |
| Blocky source | tag commit `45a242ff`; main inspected at `fe8e3a66` | v0.35.0 requires Go 1.26.2. |

The official documentation contains some older Unbound-era pages. Where it
conflicts with Core Update 203 or the current source tree, the release notes
and current source tree are the stronger evidence.

## What Blocky needs at runtime

[Blocky](https://github.com/0xERR0R/blocky) is a DNS proxy and ad blocker. A
single executable provides UDP/TCP DNS, upstream resolution, allow/block
lists, caching, optional client groups, custom DNS mappings, optional query
logging, an HTTP API, Prometheus metrics, DoH/DoT/DoQ support, and diagnostic
commands.

### Binary and configuration

- The standalone invocation is `blocky --config /path/to/config.yml`.
- The default configuration path is `./config.yml`; the package must always use
  an absolute path.
- `BLOCKY_CONFIG_FILE` can also select the configuration. `CONFIG_FILE` is a
  legacy alias.
- A configuration directory is allowed and its YAML files are merged, but a
  duplicate option is an error. One file is simpler for the first package.
- `upstreams.groups.default` is mandatory and must contain at least one
  resolver.
- The `validate` subcommand checks configuration without starting the daemon.
- Blocky handles `SIGINT` and `SIGTERM` and has a ten-second graceful shutdown
  timeout.
- `SIGUSR1` prints runtime configuration and statistics; it does **not** reload
  the configuration. Configuration changes require a restart.

### Listeners and privilege

- `ports.dns` defaults to port 53 and serves both TCP and UDP. A port without
  an address listens on every interface.
- `ports.http`, when enabled, serves more than metrics: it also hosts the REST
  API, DoH, and Go profiling endpoints such as `/debug/pprof`.
- TLS and HTTPS listeners are optional.
- An unprivileged process needs `CAP_NET_BIND_SERVICE` to bind below port 1024.
  Blocky's own installation guide recommends setting that capability on the
  binary. IPFire uses the same technique for Knot Resolver.
- Upstream release archives do not carry the capability. The package's
  install/update lifecycle must apply and verify it if port 53 is to be
  supported.

The initial port 1053 does not technically need the capability. Retaining the
capability plan makes a later administrator-selected port 53 mode possible,
but this should be reviewed under least privilege: omit it in v1 if v1 refuses
all privileged ports.

### State and observability

The normal resolver cache is in memory. Persistent state appears only when
features such as downloaded-list caching or query logging are enabled.

- Lists may come from HTTPS, local files, or inline entries. The default list
  refresh interval is four hours.
- Query logs may be sent to CSV, SQLite, databases, console, dnstap, or nowhere.
- Query data is sensitive. SQLite also uses WAL sidecar files, so copying only
  the main database is not a consistent backup strategy.
- The first package should explicitly set `queryLog.type: none` and create no
  persistent query log.
- The built-in `healthcheck` command performs a TCP DNS query. The special name
  `healthcheck.blocky` returns a successful empty response independently of the
  normal upstream chain.

### Network access

Depending on configuration, Blocky may need outbound access for:

- UDP and TCP 53 for conventional DNS;
- TCP 853 for DNS over TLS;
- UDP 853 for DNS over QUIC;
- TCP 443 for DNS over HTTPS and remote list downloads; and
- bootstrap DNS resolution for named encrypted resolvers.

IPFire's firewall gives the built-in `knot-resolver` user an explicit local
output allowance. A new `blocky` user does not inherit it. The first package
should document this and avoid silently changing firewall policy. Outbound
firewall integration needs a separate design that survives firewall reloads
and permits only the configured protocols and destinations.

## How an IPFire add-on is built

IPFire add-ons are built inside the full `ipfire-2.x` build system, not as an
independent archive assembled by this repository alone. The documented flow is:

1. Prepare the supported Linux build environment and clone the official
   `ipfire-2.x` source tree.
2. Download sources and the architecture-specific toolchain.
3. Complete a clean baseline build before changing the package set.
4. Add an LFS recipe, source/archive checksum, rootfile, initscript, backup
   include, and Pakfire lifecycle scripts.
5. Add `lfsmake2 blocky` to `buildipfire()` in `make.sh`.
6. Build once to discover installed files, curate the package rootfile, clean,
   then rebuild the final package.
7. Test installation, update, removal, backup/restore, service control, and
   boot behavior on each supported architecture.

The resulting filename is derived as
`blocky-<upstream-version>-<package-release>.ipfire`. `VER` tracks Blocky's
version. `PAK_VER` is incremented when the IPFire packaging or installed
configuration changes without an upstream version change.

### Expected IPFire source-tree changes

An upstream-style implementation will need the following changes in an IPFire
checkout:

| Path | Purpose |
| --- | --- |
| `lfs/blocky` | Version, architecture restrictions, download objects, BLAKE2 checksums, installation, and `dist: @$(PAK)`. |
| `config/rootfiles/packages/blocky` | Exact list of files owned by the add-on. |
| `src/initscripts/packages/blocky` | `start`, `stop`, `restart`, and `status`; validate before start. |
| `config/backup/includes/blocky` | Preserve `/etc/blocky`; omit caches and query logs by default. |
| `src/paks/blocky/install.sh` | Extract, restore config, ensure user/directories/ownership/capability, create runlevel links, but do not auto-start v1. |
| `src/paks/blocky/update.sh` | Preserve config/state, replace files, reapply ownership/capability, and keep the previous enable/running intent. |
| `src/paks/blocky/uninstall.sh` | Stop, back up configuration, remove owned files and links without deleting unrelated data. |
| `make.sh` | Invoke `lfsmake2 blocky` in the add-on section. |

The IPFire LFS recipe should at least define `SUMMARY`, `VER`, `THISAPP`,
`DL_FILE`/download objects, `DL_FROM`, `DIR_APP`, `TARGET`, `SUP_ARCH`, `PROG`,
`PAK_VER`, `DEPS`, and `SERVICES`. `SERVICES = blocky` makes service controls
available through IPFire's add-on UI and `addonctrl`.

The package payload should look like this:

```text
/usr/bin/blocky
/usr/share/licenses/blocky/LICENSE
/etc/blocky/config.yml
/etc/rc.d/init.d/blocky
/var/ipfire/backup/addons/includes/blocky
```

Add `/var/cache/blocky`, `/var/lib/blocky`, or `/var/log/blocky` only when a
configured feature truly needs them. If empty directories must survive package
assembly, account for that explicitly in the recipe/rootfile.

### Pakfire lifecycle details

The generic Pakfire scripts automatically extract files, restore backups, and
start services. This package needs custom scripts because it has to create a
system identity and, for the cautious first release, avoid starting a DNS
service unexpectedly.

- Create a locked system user and group named `blocky`, with no interactive
  shell and no usable home directory.
- Keep `/etc/blocky/config.yml` root-owned and not writable by the daemon.
- Give `blocky` ownership only of deliberately writable state directories.
- Apply the file capability after extraction and after every update if the
  package elects to ship it.
- Install kill links for shutdown and reboot.
- Put the start link in `/etc/rc.d/rc3.d/off/` initially. IPFire's `addonctrl`
  enables/disables services by moving the `S??blocky` link between that
  directory and `/etc/rc.d/rc3.d/`.
- Do not delete the system user on uninstall unless IPFire maintainers prefer
  that convention; leaving it avoids UID reuse against retained files.
- Make every lifecycle operation idempotent.

The update script must be tested especially carefully. It should neither
silently enable the service nor lose the administrator's configuration, and it
must not restart a previously stopped service solely because an update was
installed.

### Distribution caveat

The official add-on guide documents manual package testing, including
registering the rootfile under `/opt/pakfire/db/rootfiles/`, but its section on
sharing third-party packages is still incomplete. Pakfire's normal Web UI flow
assumes packages published and signed through IPFire's distribution process.
Building a valid `.ipfire` file is therefore not the same as making it available
in the official package feed. Treat official inclusion or a securely signed
third-party distribution channel as a later, explicit decision.

## Build-source decision

### Option A: repackage official static binaries

This is the recommended prototype path.

Benefits:

- works with IPFire's current build environment;
- adds no runtime libraries or Go runtime package;
- matches artifacts published and tested by Blocky's release automation; and
- keeps the package recipe small.

Costs and risks:

- the binary is not produced by the IPFire build system;
- upstream acceptability and reproducibility policy are unknown;
- the architecture-specific download logic is more complex than one source
  tarball; and
- provenance depends on GitHub release artifacts and pinned checksums.

The v0.35.0 assets inspected for this document are stripped, statically linked
ELF binaries with no dynamic section:

| IPFire arch | Blocky asset | Size | SHA-256 | BLAKE2b-512 for IPFire LFS |
| --- | --- | ---: | --- | --- |
| `x86_64` | `blocky_v0.35.0_Linux_x86_64.tar.gz` | 13,121,667 B | `97ae4257e4f2ea7ee4e0622fca152019eb92224d81b41b2549f064e4cef5584e` | `89945953df7466e977517288c4824d77c3ef1adaf128caebd964233dd8f40fa812813a9622e9c27e6f13839369d3ab20e61dc35c53dd6059b39f155d5d1d5449` |
| `aarch64` | `blocky_v0.35.0_Linux_arm64.tar.gz` | 11,876,578 B | `9ac70e846f7919632e340607fb73d80a1fe280c9ceb876430d2a7d79743b4aae` | `525bf8b76803af0ded29729028c5111cc39578d7d76d485efdf882d5427dc885f5eef81721fb7c41859c448921ca10b5d21217189bdb561f608b61ce857b8774` |

The asset URLs and both checksum types must remain pinned per version. Also
compare their SHA-256 values to Blocky's published checksum file in automated
release-update work.

### Option B: build Blocky from source in IPFire

This is the better long-term provenance story, but it is currently blocked:

- Blocky v0.35.0 declares Go 1.26.2.
- IPFire's `lfs/go` currently packages Go 1.20.4.
- IPFire's Go recipe maps only `x86_64` and `aarch64`; it does not currently
  provide the project's third build architecture, `riscv64`.
- Blocky's release matrix includes amd64, arm, arm64, MIPS, and MIPS64 variants,
  but no RISC-V artifact.
- Blocky does not vendor its modules in the release source. A deterministic,
  network-independent IPFire build would need an agreed dependency-staging or
  vendoring approach.

Do not hide a Go toolchain upgrade inside this add-on. It is a separate IPFire
platform change with a much larger test surface. If source builds are required,
coordinate that work with IPFire maintainers first.

### Architecture scope

Set `SUP_ARCH = aarch64 x86_64` for v1. Do not claim `riscv64` support until
both Blocky and the chosen build/artifact strategy produce and test a suitable
binary.

## IPFire DNS integration

### Current IPFire behavior

Core Update 203 replaced Unbound with Knot Resolver. The current generated
Knot configuration:

- is marked as generated and not safe for direct editing;
- listens on `0.0.0.0@53`;
- loads IPFire-generated settings, DHCP leases, response-policy zones,
  Safe Search data, forwarding rules, and upstream forwarders; and
- runs early in the boot sequence as the unprivileged `knot-resolver` user.

IPFire's DNS Firewall can apply category blocklists and custom allow/block
lists by network or host. IPFire also provides encrypted upstream DNS, Safe
Search, conditional forwarding, local overrides, DHCP lease integration, and
resolver cache behavior. These overlap substantially with Blocky. A replacement
design must say which product owns each responsibility; running both sets of
features blindly can create confusing policy order and duplicate work.

### Integration choices

| Mode | Topology | Advantages | Problems | Recommendation |
| --- | --- | --- | --- | --- |
| Safe sidecar | Client/test tool -> Blocky `127.0.0.1:1053` -> Knot `127.0.0.1:53` | No IPFire changes; useful for validation; no port conflict. | Normal clients do not use it automatically. | **v1 default.** |
| Knot in front | Clients -> Knot `:53` -> Blocky `:1053` -> external upstream | Knot keeps IPFire-facing integration and port 53. | Blocky sees Knot/localhost instead of the original client, weakening client groups and per-client logs; generated Knot config needs a durable extension; loops must be prevented. | Explore after v1. |
| Blocky in front | Clients -> Blocky `:53` -> Knot on another port | Blocky sees client IPs and can retain Knot as the IPFire-aware resolver. | Requires moving generated Knot listeners, boot ordering, firewall changes, health/failover design, and ownership of encrypted upstream policy. | Possible long-term mode, not v1. |
| Replace Knot | Clients -> Blocky `:53` -> external upstream | Simplest active topology; full Blocky client identity. | Bypasses or must recreate IPFire DNS Firewall, DHCP names, local policy, forwarding, Safe Search, and Web UI expectations. | Do not automate. Expert opt-in only, if supported at all. |

If a future front-end passes EDNS Client Subnet, Blocky has an
`ecs.useAsClient` option, but it accepts only host-length `/32` IPv4 or `/128`
IPv6 client values. That is not a substitute for a fully designed, privacy-aware
client identity path.

### Minimal safe configuration

The package should ship a syntactically valid baseline similar to:

```yaml
upstreams:
  groups:
    default:
      - 127.0.0.1

ports:
  dns: 127.0.0.1:1053

queryLog:
  type: none
```

This deliberately has no blocklists: it proves the package and service without
silently selecting a third-party policy or making list-download network
requests. Add commented examples or a separate sample file rather than active
defaults. Never configure Blocky to use itself as an upstream.

The HTTP listener should be absent, not merely firewalled. If enabled later,
bind it to `127.0.0.1` by default. No authentication mechanism is apparent in
the upstream configuration/API definition, and the listener exposes control
and diagnostic surfaces as well as metrics.

## Proposed service contract

The initscript should follow IPFire's existing service helpers and provide:

- `start`: run `blocky --config /etc/blocky/config.yml validate`, then launch
  in the background as user `blocky`; fail without replacing an already
  running process;
- `stop`: send `SIGTERM` through IPFire's process helper and allow the graceful
  shutdown window;
- `restart`: stop then start, preserving useful exit status;
- `status`: report through IPFire's standard status helper; and
- `reload`: either return a clear unsupported result or intentionally implement
  it as a restart. It must not send `SIGUSR1` and claim that configuration was
  reloaded.

Open questions to settle during implementation include stdout/stderr routing,
PID matching, file-descriptor limits under load, exact start-link ordering, and
whether the v1 high-port-only policy justifies omitting the binary capability.
Use the current `dnsdist` and `amazon-ssm-agent` add-ons as patterns, but test
Blocky's actual process behavior rather than copying their scripts verbatim.

## Security posture

- Treat configuration and query data as security-sensitive.
- Keep the daemon unprivileged and the configuration immutable to it.
- Bind only to explicitly named addresses. Never expose DNS or HTTP listeners
  on IPFire's RED interface by accident.
- Do not add broad owner-based firewall exceptions without understanding how
  IPFire's outgoing firewall chains interact with administrator policy.
- Pin downloads by cryptographic digest; never fetch `latest` during a build.
- Ship Blocky's Apache 2.0 `LICENSE` alongside the binary.
- Validate release archive contents and binary architecture before installing.
- Test that Pakfire preserves or reapplies extended attributes/capabilities.
- Avoid enabling query logging by default. Document retention and backups when
  users enable it.
- Treat remote blocklists as a supply-chain and availability dependency.

## Implementation phases

### Phase 0: maintainer alignment

1. Ask IPFire developers whether repackaged upstream static Go binaries can be
   accepted into the add-on feed.
2. Confirm the preferred install path (`/usr/bin` versus `/usr/sbin`), account
   creation convention, license-file convention, and disabled-by-default
   service behavior.
3. Confirm supported architectures and how unofficial packages should be
   distributed for testers.

### Phase 1: package-only prototype

1. Create the two-architecture LFS recipe with pinned v0.35.0 assets/checksums.
2. Install the binary, license, safe configuration, initscript, backup include,
   rootfile, and custom Pakfire scripts.
3. Register `SERVICES = blocky`, but install its start link under `rc3.d/off`
   and do not start it during package installation.
4. Validate configuration during the image build and again before service
   startup.
5. Produce and manually test both `.ipfire` packages.

### Phase 2: operational hardening

1. Test upgrade and rollback behavior, including configuration preservation and
   capabilities.
2. Decide how outbound firewall permissions should be expressed without
   weakening policy.
3. Add release-update automation that verifies upstream checksums, archive
   layout, ELF architecture, static linkage, license, and embedded version.
4. Document explicit administrator steps for list sources, logging, HTTP
   metrics, and safe listener binding.

### Phase 3: optional DNS-path integration

Prototype Knot-in-front and Blocky-in-front modes separately. Measure client
identity, DHCP/local-name behavior, DNS Firewall ordering, DNSSEC, cache
semantics, failure behavior, and Web UI expectations before selecting one. Any
mode that edits generated core configuration should be designed with IPFire
maintainers rather than patched locally.

## Verification plan

### Build/package checks

- Clean IPFire baseline build succeeds for each supported architecture.
- Download digest and archive layout are exact.
- Installed executable reports Blocky v0.35.0 and the correct architecture.
- `file` confirms the expected static ELF.
- Rootfile contains every package-owned file and no transient build output.
- Final package has correct metadata, dependencies, and `Services: blocky`.
- License and backup include are present.

### Lifecycle checks

- Fresh install does not start Blocky or claim port 53.
- `addonctrl blocky boot-status` reports disabled.
- Invalid configuration prevents startup with a useful error.
- Manual start, stop, restart, status, enable, and disable work.
- `SIGTERM` shuts the daemon down cleanly.
- Enable persists through reboot; disable prevents startup.
- Upgrade preserves configuration, enable state, and previous running/stopped
  intent.
- Uninstall stops the service, removes owned files/links, and does not damage
  IPFire DNS resolution.
- Backup and restore preserve `/etc/blocky` but not ephemeral caches/logs.

### DNS and security checks

- Both UDP and TCP queries to `127.0.0.1:1053` succeed.
- IPFire's existing port 53 remains owned by Knot and behaves unchanged.
- `healthcheck.blocky` succeeds against the configured address and port.
- No DNS/HTTP listener is reachable from GREEN, BLUE, ORANGE, or RED by default.
- The daemon runs as `blocky`, cannot edit its configuration, and can write only
  to intended state paths.
- Outbound behavior is tested with IPFire's outgoing firewall both enabled and
  disabled.
- A deliberately broken upstream cannot create a Blocky/Knot forwarding loop.
- Package update reapplies any chosen capability and does not broaden it.

## Open decisions

1. **Acceptance policy:** will IPFire accept official Blocky binaries, or is a
   source build mandatory?
2. **Capability:** omit it for strict high-port v1, or install it to support an
   administrator-selected privileged port?
3. **Service default:** confirm that disabled-by-default is acceptable for an
   add-on whose upstream default conflicts with the core resolver.
4. **Long-term topology:** should Blocky complement Knot, sit in front of it, or
   remain an expert-managed sidecar?
5. **Firewall integration:** what is the narrow, persistent IPFire-native way
   to allow configured upstream/list traffic?
6. **Logging:** should logs stay on the console/syslog, or should the package
   define log files and rotation?
7. **Updates:** who monitors Blocky security releases, validates artifacts, and
   increments `VER`/`PAK_VER`?
8. **Distribution:** official Pakfire feed, signed third-party feed, or manual
   test artifacts?

None of these prevents the package-only prototype. They do prevent responsibly
turning it into a transparent port-53 replacement.

## Primary sources

### IPFire

- [Add-on build guide](https://www.ipfire.org/docs/devel/ipfire-2-x/addon-howto)
- [LFS package template](https://www.ipfire.org/docs/devel/ipfire-2-x/lfs-template)
- [Add-on requirements](https://www.ipfire.org/docs/devel/ipfire-2-x/addon-howto/requirements)
- [Initial build environment](https://www.ipfire.org/docs/devel/ipfire-2-x/build-initial)
- [IPFire 2.x build guide](https://www.ipfire.org/docs/devel/ipfire-2-x/build-howto)
- [Pakfire user documentation](https://www.ipfire.org/docs/configuration/ipfire/pakfire)
- [Scratch build service](https://www.ipfire.org/docs/devel/scratchbuild)
- [Patch submission guide](https://www.ipfire.org/docs/devel/submit-patches)
- [Core Update 203 release notes](https://www.ipfire.org/blog/ipfire-2-29-core-update-203-released)
- [DNS Firewall](https://www.ipfire.org/docs/configuration/firewall/dns)
- [DNS settings](https://www.ipfire.org/docs/configuration/network/dns)
- [Current Knot Resolver configuration in source](https://git.ipfire.org/?p=ipfire-2.x.git;a=blob;f=config/knot-resolver/config.yaml;hb=f4f4c04af1a83d451354574321efc2474de1d1f3)
- [Current IPFire LFS framework](https://git.ipfire.org/?p=ipfire-2.x.git;a=blob;f=lfs/Config;hb=f4f4c04af1a83d451354574321efc2474de1d1f3)
- [Current Go add-on example](https://git.ipfire.org/?p=ipfire-2.x.git;a=blob;f=lfs/amazon-ssm-agent;hb=f4f4c04af1a83d451354574321efc2474de1d1f3)
- [Current DNS service add-on example](https://git.ipfire.org/?p=ipfire-2.x.git;a=blob;f=lfs/dnsdist;hb=f4f4c04af1a83d451354574321efc2474de1d1f3)
- [Current add-on service controller](https://git.ipfire.org/?p=ipfire-2.x.git;a=blob;f=src/misc-progs/addonctrl.c;hb=f4f4c04af1a83d451354574321efc2474de1d1f3)

### Blocky

- [Blocky repository](https://github.com/0xERR0R/blocky)
- [v0.35.0 release](https://github.com/0xERR0R/blocky/releases/tag/v0.35.0)
- [Standalone installation guide at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/docs/installation.md)
- [Configuration reference at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/docs/configuration.md)
- [Network configuration at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/docs/network_configuration.md)
- [Operational notes and signals at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/docs/additional_information.md)
- [Release build matrix at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/.goreleaser.yml)
- [Container build at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/Dockerfile)
- [Build Makefile at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/Makefile)
- [Go toolchain declaration at v0.35.0](https://github.com/0xERR0R/blocky/blob/v0.35.0/go.mod)
- [Apache 2.0 license](https://github.com/0xERR0R/blocky/blob/v0.35.0/LICENSE)
