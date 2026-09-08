# IPFire Blocky add-on

This project packages [Blocky](https://github.com/0xERR0R/blocky) as a native
IPFire add-on with an IPFire Web UI, GREEN/BLUE DNS interception, optional DNS
bypass prevention, and explicit fail-closed enforcement.

The current implementation targets Blocky v0.35.0 and IPFire 2.29 Core Update
203 conventions on `x86_64` and `aarch64`. Installing the package is inert:
Blocky is stopped, boot-disabled, loopback-only on port 1053, and has no
firewall policy until an administrator opts in.

## Repository map

- [`PROJECT.md`](PROJECT.md) contains the research and design background.
- [`spec.md`](spec.md) is the active implementation specification.
- [`packaging/ipfire`](packaging/ipfire) is an overlay for `ipfire-2.x`.
- [`docs/admin`](docs/admin) contains operator documentation.
- [`tests`](tests) exercises configuration, firewall, schema, and packaging
  invariants.

## Local checks

```sh
make check \
  IPFIRE_TREE=/path/to/ipfire-2.x \
  BLOCKY_BIN=/path/to/blocky-v0.35.0
```

`IPFIRE_TREE` verifies the pinned overlay and patch application;
`BLOCKY_BIN` validates representative inert and fully enforced generated
configurations with the real pinned binary. Either optional input may be
omitted for the platform-independent unit/static checks.

To stage the overlay and its small registration patch into a clean checkout:

```sh
tools/stage-ipfire-overlay /path/to/ipfire-2.x
```

The resulting checkout must then be built through IPFire's normal full build
workflow. This repository does not publish or sign a Pakfire feed.

## Security model

The management page runs as IPFire's unprivileged CGI account. It hands a
bounded, fixed candidate file to a narrow allowlisted setuid controller. A
root-owned manager validates and atomically generates the runtime configuration
and reconciles package-owned firewall chains. Blocky itself runs as a locked
`blocky` user.

Once routing is active, enforcement fails closed. Read
[`docs/admin/enforcement-and-recovery.md`](docs/admin/enforcement-and-recovery.md)
before enabling it.
