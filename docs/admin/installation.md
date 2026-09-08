# Installation and package building

## Supported baseline

- IPFire 2.29 Core Update 203 for appliance testing, using the pinned
  `ipfire-2.x` development baseline recorded in `packaging/ipfire/IPFIRE_BASELINE`
- `x86_64` or `aarch64`
- Blocky v0.35.0 official static release artifact

The add-on deliberately uses upstream static artifacts because Blocky v0.35.0
requires Go 1.26.2 while the researched IPFire tree provides Go 1.20.4.
Checksums are pinned in `packaging/ipfire/lfs/blocky`.

## Building with IPFire

Start with a clean, fully prepared IPFire checkout and complete the baseline
build required by the IPFire add-on documentation. Then stage this project's
overlay:

```sh
make check IPFIRE_TREE=/path/to/ipfire-2.x
tools/stage-ipfire-overlay /path/to/ipfire-2.x
```

The staging command copies files into their expected `ipfire-2.x` paths and
registers `blocky` in `make.sh` and `blockyctrl` in the misc-progs build. It
refuses to run if the checkout differs from the recorded baseline or the
registration patch does not cleanly apply.

Run IPFire's normal clean build and inspect the generated
`blocky-0.35.0-1.ipfire` package. The curated rootfile is
`config/rootfiles/packages/blocky`.

## Installation behavior

A fresh package installation:

- creates a locked `blocky` system account;
- installs Blocky, the native management page, controller, schema, provider
  catalog, service, backup include, and lifecycle files;
- installs its boot link in `rc3.d/off`;
- registers a marked callback in `/etc/sysconfig/firewall.local` without
  replacing other content;
- generates an inert loopback configuration; and
- does not start Blocky or add active firewall policy.

An unofficial `.ipfire` file is not automatically trusted or distributed by
Pakfire. Follow IPFire's documented manual add-on testing process on a
disposable appliance before using the package on a production firewall.

Uninstall runs the same recovery path before package removal, takes the normal
add-on configuration backup, and removes the root-only generated
last-known-good snapshot. The locked `blocky` account is retained to avoid UID
reuse against any administrator-retained files.

## Post-install checks

1. Confirm **Services > Blocky** is present.
2. Confirm the service is stopped and boot-disabled.
3. Run `/usr/local/bin/blockyctrl validate` from the appliance if desired.
4. Inspect `/etc/blocky/config.yml`; it must contain only the generated
   loopback listener on `127.0.0.1:1053` initially.
5. Confirm IPFire's Knot Resolver still answers clients on port 53.
