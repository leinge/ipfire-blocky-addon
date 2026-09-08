# SPEC-0002: CI-built IPFire packages and GitHub Releases

| Field | Value |
| --- | --- |
| Status | Ready for implementation |
| Created | 2026-09-08 |
| Predecessor | [`SPEC-0001`](docs/internal/specs/0001-initial-ipfire-blocky-addon.md) |
| Target package | Blocky v0.35.0, IPFire package release 1 |
| Supported architectures | `x86_64`, `aarch64` |
| Distribution target | GitHub Actions artifacts and GitHub Releases |
| Release classification | Unofficial IPFire test add-on; not an official Pakfire feed |
| Runner decision | Hosted runner for fast checks; dedicated trusted `x86_64` self-hosted runner for full builds |
| Internal register | [`docs/internal/specs/README.md`](docs/internal/specs/README.md) |

## 1. Purpose

Automate the expensive IPFire package build so an operator can download a
verified architecture-specific `.ipfire` file instead of preparing a complete
IPFire build environment locally.

The automation must retain the provenance and safety properties of SPEC-0001:
the package is built by IPFire's native build system from the pinned IPFire and
Blocky inputs, is tested before publication, and is clearly identified as an
unofficial package that is not signed by or distributed through IPFire's
Pakfire repository.

The design separates fast feedback from trusted release execution:

1. ordinary pull requests and pushes run quick, unprivileged checks on
   GitHub-hosted runners;
2. trusted release commits run full IPFire builds for `x86_64` and `aarch64`
   on a dedicated self-hosted builder;
3. successful builds produce architecture-qualified artifacts, checksums,
   machine-readable provenance, and GitHub artifact attestations; and
4. a protected publication step creates a draft GitHub Release which a
   maintainer publishes as a pre-release after reviewing the evidence.

CI publication reduces build friction. It does not replace appliance testing,
manual installation, or the future work needed for an official signed Pakfire
distribution channel.

## 2. Goals and scope

### 2.1 In scope

- A required fast-check workflow for pull requests and pushes to `main`.
- A trusted release-build workflow triggered by an explicit release tag or a
  manually dispatched dry run.
- Full native IPFire package builds for `x86_64` and `aarch64` using the exact
  baseline in `packaging/ipfire/IPFIRE_BASELINE`.
- Reuse of the repository's overlay staging, unit/static checks, real Blocky
  validation, and IPFire LFS packaging rather than a second package assembler.
- A documented, dedicated `x86_64` self-hosted runner capable of cross-building
  `aarch64` with IPFire's `--target=aarch64` path and QEMU/binfmt support.
- Persistent source/toolchain/compiler caches on that trusted builder, with
  cache separation by architecture and pinned IPFire baseline.
- Actions workflow artifacts for manual dry runs and failed publication
  investigations.
- A draft GitHub Release containing both architecture-qualified packages,
  checksums, a build manifest, release notes, and build-provenance attestations.
- Validation that the release tag, Blocky version, IPFire package release, and
  package metadata agree.
- Safe rerun behavior which never silently replaces a published asset.
- Documentation for maintainers provisioning the runner, producing a release,
  reviewing results, publishing a pre-release, promoting it after appliance
  testing, and verifying artifacts.
- Updated installation documentation which starts from downloading a release
  asset and still documents IPFire's manual unofficial-package procedure.

### 2.2 Out of scope

- An official or third-party Pakfire repository, Pakfire index, or Pakfire
  signing key.
- Claiming that GitHub provenance is an IPFire package signature.
- Automatic installation or upgrade on an IPFire appliance.
- Running untrusted pull-request code on a self-hosted runner.
- Automatically publishing a stable production release solely because a build
  completed.
- Provisioning paid GitHub larger runners or physical/virtual runner
  infrastructure from this repository.
- Fully automated GREEN/BLUE appliance tests; the SPEC-0001 appliance matrix
  remains a manual promotion gate.
- Building Blocky from Go source; the package continues to consume the pinned
  official static Blocky release artifacts.
- Automatically discovering or updating to new Blocky or IPFire versions.
- Supporting `riscv64` or IPv6 enforcement.
- General-purpose CI for an arbitrary, unpinned IPFire branch.

## 3. Constraints and decisions

### 3.1 Why full builds use a self-hosted runner

IPFire's documented clean build takes multiple hours and needs substantial
disk space. Standard GitHub-hosted jobs have bounded execution time and disk,
so they are suitable for the repository's fast checks but are not the reliable
release path.

The full build runner must be a dedicated, non-production Linux machine or VM
with, at minimum:

- an `x86_64` host supported by the pinned IPFire build instructions;
- four CPU cores, 16 GiB RAM, and 100 GiB free local storage;
- Git, the current IPFire build prerequisites, ccache, QEMU user emulation,
  and enabled binfmt handlers for `aarch64`;
- permission for the runner account to perform the privileged namespace,
  mount, and build operations required by `make.sh`;
- outbound HTTPS access to GitHub and IPFire source/toolchain services; and
- no access to production secrets or internal networks unrelated to the build.

The documented sizing is an operational floor for this project, not an
upstream IPFire guarantee. Maintainers may increase it without changing this
specification.

The runner receives the labels `self-hosted`, `linux`, `x64`, and
`ipfire-release`. Release jobs must require the complete label set.

### 3.2 Version and tag contract

The authoritative package values remain in `packaging/ipfire/lfs/blocky`:

- `VER` is the upstream Blocky version;
- `PAK_VER` is the IPFire packaging release; and
- `SUP_ARCH` declares the supported architecture set.

Release tags use this exact format:

```text
blocky-v<VER>-ipfire<PAK_VER>
```

For the current package the tag is:

```text
blocky-v0.35.0-ipfire1
```

A release workflow must parse the recipe through a repository-owned metadata
tool and reject malformed, duplicated, or unexpected values. It must reject a
tag that does not exactly match the parsed metadata. `SUP_ARCH` must resolve to
exactly `aarch64 x86_64` for SPEC-0002.

The tag must point to a commit reachable from the protected `main` branch. The
workflow must build the tag commit, not a mutable branch head.

### 3.3 Release asset naming

IPFire emits the same filename for each target architecture. GitHub Release
assets must therefore be renamed at the distribution boundary without
changing the package contents:

```text
blocky-<VER>-<PAK_VER>-x86_64.ipfire
blocky-<VER>-<PAK_VER>-aarch64.ipfire
SHA256SUMS
build-manifest.json
```

For example:

```text
blocky-0.35.0-1-x86_64.ipfire
blocky-0.35.0-1-aarch64.ipfire
```

Each build job must first find exactly one canonical
`blocky-<VER>-<PAK_VER>.ipfire` output under that target's IPFire package
directory, validate it, and only then copy it to the architecture-qualified
release name.

### 3.4 Publication states

- A manual dry run uploads workflow artifacts and never creates or mutates a
  GitHub Release.
- A matching release tag may create or resume a **draft** GitHub Release only
  after both architecture builds succeed.
- Publication of that draft requires approval through a protected GitHub
  environment and produces a visible **pre-release**.
- Promotion from pre-release to stable requires completion of the applicable
  SPEC-0001 appliance matrix on both architectures and remains an explicit
  maintainer action.
- A published release and its assets are immutable from the workflow's point
  of view. Rerunning a job may verify them but must not replace, delete, or
  silently change them.

GitHub Actions artifacts are temporary diagnostic/build outputs. GitHub
Release assets are the durable operator download surface.

## 4. Workflow architecture

### 4.1 Fast checks: `.github/workflows/checks.yml`

The fast workflow runs on pull requests and pushes to `main` using a standard
GitHub-hosted Ubuntu runner. It has `contents: read` permission and no secrets.

It must:

1. check out the exact repository commit without persisting credentials;
2. install only explicitly required test packages;
3. clone or fetch the exact IPFire baseline commit into a temporary path;
4. run `make check IPFIRE_TREE=<pinned-tree>`;
5. download both Blocky release archives through the pinned recipe URLs;
6. verify their recorded BLAKE2b-512 checksums before extraction;
7. verify archive contents, embedded version, static linkage, and ELF target
   architecture;
8. execute `tools/validate-with-blocky` with the `x86_64` binary; and
9. fail on any dirty generated repository state, checksum drift, unexpected
   archive content, or overlay mismatch.

The workflow should split independent checks into a small matrix only where it
improves feedback. It must remain materially faster than a full IPFire build.

### 4.2 Release orchestration: `.github/workflows/build-release.yml`

The release workflow supports:

- `workflow_dispatch` with a required `dry_run` boolean which defaults to
  `true`; and
- tag pushes matching `blocky-v*-ipfire*`.

It contains these logical jobs:

1. **Metadata:** run on a hosted runner, validate the trigger, tag, main-branch
   reachability, baseline commit, package metadata, and supported architecture
   set. Emit only validated outputs.
2. **Build:** run a two-entry architecture matrix on the dedicated self-hosted
   runner with `max-parallel: 1`. Each entry constructs one clean target build,
   validates it, and uploads one architecture-qualified workflow artifact.
3. **Assemble:** run on a hosted runner, download both build artifacts, verify
   their recorded evidence, generate deterministic checksums and the combined
   manifest, and attest the release subjects.
4. **Release:** for a tag build only, enter the protected release environment
   and create or safely resume the draft GitHub Release.

Only one full release workflow may use the builder at a time. Concurrency must
be repository-wide for release builds, and a later invocation must not cancel
an active build after it has begun.

### 4.3 Full architecture build

For each architecture, the build job must:

1. allocate a new, explicitly scoped working directory;
2. check out the add-on at the validated tag commit;
3. clone the official `ipfire-2.x` repository and check out exactly the commit
   in `packaging/ipfire/IPFIRE_BASELINE`;
4. verify the IPFire checkout is clean and the expected commit is checked out;
5. run the repository fast checks and overlay applicability check;
6. stage the overlay with `tools/stage-ipfire-overlay`;
7. invoke IPFire's official source download and prebuilt-toolchain steps for
   the target architecture;
8. run a full clean `./make.sh --target=<arch> build` through IPFire's native
   build system;
9. locate exactly one expected `.ipfire` package and `meta-blocky` file;
10. validate package structure, metadata, rootfile, lifecycle scripts, payload,
    Blocky version, static linkage, and ELF architecture;
11. validate representative inert and enforced generated configurations with
    the packaged binary, using the configured QEMU execution path for
    `aarch64` when necessary;
12. produce a per-architecture evidence document and cryptographic digests;
13. upload only the package and evidence needed by the assemble job; and
14. clean the scoped workspace even when the build fails, while retaining only
    approved source/toolchain/ccache directories.

The build must not create the `.ipfire` archive with an independent tar
command. The release subject must be the output of the LFS `dist: @$(PAK)`
path in the pinned IPFire build system.

### 4.4 Cache model

The self-hosted runner may persist:

- the IPFire download cache;
- architecture-specific official IPFire toolchains; and
- architecture- and baseline-specific ccache directories.

Cache keys and directories must include the architecture and full pinned
IPFire commit. An `x86_64` compiler cache must never be shared with `aarch64`.
The checked-out source tree, build root, images, package output, credentials,
and pending release assets must not persist as trusted input to the next run.

Every cached source object is revalidated by the IPFire recipe checksum path.
Changing `IPFIRE_BASELINE`, `VER`, an upstream object checksum, or the target
architecture must cause the relevant cache namespace to change or be
revalidated before use.

### 4.5 Build manifest

`build-manifest.json` is canonical JSON with stable key ordering and contains:

- a schema version;
- release tag and add-on Git commit;
- full IPFire baseline commit;
- Blocky `VER`, package `PAK_VER`, and supported architectures;
- upstream archive filename, URL, and pinned BLAKE2b-512 digest per
  architecture;
- final release asset filename, byte size, SHA-256, and BLAKE2b-512 digest per
  architecture;
- package metadata fields and internal canonical package filename;
- workflow name, GitHub run identifier and attempt, and build timestamp;
- runner OS and target architecture, without hostnames, internal paths, IP
  addresses, credentials, or infrastructure identifiers; and
- the result of each required validation gate.

The manifest format must be documented and covered by tests. Values derived
from Git tags or workflow inputs must be serialized as data and never
interpolated into executable shell fragments.

### 4.6 Checksums and attestations

`SHA256SUMS` must:

- cover both architecture-qualified `.ipfire` files and
  `build-manifest.json`;
- use filenames only, never absolute paths;
- be sorted bytewise by filename; and
- be regenerated by the assemble job from downloaded build artifacts.

The workflow must use GitHub's official artifact-attestation mechanism to
attest both `.ipfire` files, the manifest, and the checksum file to the tag
commit and release workflow. Attestation permissions are enabled only for the
assemble job and only when the repository/trigger is eligible.

Release documentation must show how to verify both `SHA256SUMS` and the GitHub
attestations on a separate workstation before copying a package to IPFire.
Attestations establish GitHub build provenance; all documentation must state
that they are not Pakfire signatures.

### 4.7 Release notes

The workflow creates release notes from a repository-owned template. The notes
must include:

- Blocky version, IPFire package release, target IPFire baseline, and both
  architectures;
- links to the source commit and predecessor specification;
- the exact asset-to-appliance architecture mapping;
- checksum and attestation verification commands;
- a prominent statement that the package is unofficial and not trusted by the
  official Pakfire feed;
- a link to the manual installation instructions;
- the inert fresh-install behavior;
- the fail-closed warning and emergency recovery command;
- known IPv4 and best-effort DoH limitations; and
- the appliance-test status required before stable promotion.

Release notes and asset filenames are generated only from validated metadata.
A tag or commit message is untrusted text and must not be evaluated as code or
used as an unchecked filesystem path.

## 5. Security and trust boundaries

### 5.1 Untrusted contribution boundary

- `pull_request` jobs run only on GitHub-hosted runners with no repository or
  environment secrets.
- No workflow triggered by `pull_request`, including a fork, may select the
  `ipfire-release` runner labels.
- The project must not use `pull_request_target` to check out and execute pull
  request code.
- Full builds execute only a protected `main` commit or a release tag proven
  reachable from protected `main`.
- Manual dispatch builds the selected commit from the default branch and
  defaults to non-publishing dry-run behavior.

### 5.2 Workflow integrity

- Third-party and GitHub-maintained Actions are pinned to full commit SHAs.
- Workflow permissions default to read-only and are elevated per job only for
  artifact attestation or release creation.
- Checkout credentials are not persisted in build workspaces.
- Publication uses the repository-scoped `GITHUB_TOKEN`; no long-lived release
  or signing token is stored on the self-hosted runner.
- Release publication requires a protected GitHub environment with reviewer
  approval.
- The self-hosted runner is dedicated to this repository's trusted release
  workflow and is not a general organization runner.
- All temporary deletion targets are created by the current run beneath a
  validated runner-owned build root; cleanup must never target a workspace
  root, home directory, unresolved variable, or shared cache root.

### 5.3 Artifact immutability and reruns

- A release asset filename maps to exactly one digest.
- If a draft release already has an asset with the expected name and identical
  digest, a rerun may reuse it.
- If the digest differs, the workflow fails and requires maintainer review.
- The workflow refuses to alter any non-draft release.
- The same tag cannot be used to publish new package bytes. Any change requires
  a new `PAK_VER` and tag.

## 6. Operator and maintainer experience

### 6.1 Operator download flow

The installation guide must make CI releases the primary test-package path:

1. open the tagged GitHub Release;
2. choose the asset matching `uname -m` on the appliance;
3. download both the asset and `SHA256SUMS` on a workstation;
4. verify the checksum and GitHub attestation;
5. transfer the package to a disposable IPFire appliance; and
6. follow the existing manual lifecycle and acceptance instructions.

Local full-build instructions remain available for independent reproduction.

### 6.2 Maintainer release flow

The maintainer documentation must cover:

1. updating and reviewing version/checksum metadata in a normal pull request;
2. merging only after fast checks pass;
3. running a dry-run full build from `main`;
4. reviewing both package artifacts and evidence;
5. creating the exact release tag;
6. approving protected draft-release creation;
7. publishing the draft as a pre-release;
8. executing and recording the SPEC-0001 appliance matrix; and
9. promoting the existing immutable assets to stable without rebuilding them.

The release procedure must not require a maintainer to SSH into the build
runner during a successful run.

## 7. Repository layout

The implementation should add this structure:

```text
.github/
  workflows/
    checks.yml
    build-release.yml
  release.yml                    GitHub generated-release-note policy, if used
docs/
  admin/
    installation.md              release download and verification flow
  internal/
    release-manifest.md          manifest schema and examples
    release-runner.md            runner provisioning and maintenance
    release-process.md           maintainer dry-run/tag/publish/promotion flow
    specs/
      0001-initial-ipfire-blocky-addon.md
      README.md
packaging/
  ipfire/                        unchanged source of package truth
tools/
  release-metadata               validate and emit trusted recipe metadata
  validate-release-package       inspect one built architecture package
  assemble-release               create manifest/checksums from evidence
tests/
  release/                       metadata, package-fixture, manifest, and safety tests
spec.md                          active SPEC-0002
```

Exact helper implementation languages may follow existing project conventions.
Release logic with non-trivial parsing or validation belongs in tested helper
programs rather than long inline workflow shell blocks.

## 8. Implementation plan

### Step 1: Preserve the specification history

- Archive implemented SPEC-0001 under `docs/internal/specs/`.
- Register SPEC-0002 as the active ready specification.
- Keep archive links and statuses mechanically checkable.

### Step 2: Add release metadata tooling

- Parse `IPFIRE_BASELINE` and the Blocky LFS recipe without executing
  repository-derived values as shell code.
- Validate versions, release number, architecture set, expected tag, upstream
  objects, and asset names.
- Emit a bounded machine-readable metadata document for workflows.
- Add positive, malformed, duplicate, injection, and mismatch tests.

### Step 3: Add and require fast CI

- Implement the hosted checks workflow with minimal permissions.
- Exercise existing tests, the exact pinned IPFire overlay, upstream checksums,
  both ELF architectures, and real `x86_64` Blocky validation.
- Pin every Action dependency by full commit SHA.
- Document the required branch-protection check name.

### Step 4: Add package and manifest validation

- Inspect the outer `.ipfire` archive, nested payload, rootfile, lifecycle
  scripts, `meta-blocky`, Blocky binary, and configuration fixtures.
- Reject missing, duplicate, unexpected, symlinked, wrongly owned/mode-marked,
  dynamically linked, or wrong-architecture payloads as applicable.
- Generate per-architecture evidence and combined manifest fixtures.
- Test deterministic checksum/manifest assembly and safe filenames.

### Step 5: Add the trusted full-build workflow

- Implement metadata, serialized architecture build, assemble, and release
  jobs.
- Add scoped workspaces, architecture/baseline cache separation, concurrency,
  cleanup traps, timeouts, and artifact retention.
- Support dry runs without release permissions or mutation.
- Upload useful bounded logs/evidence on failure without exposing secrets or
  runner identifiers.

### Step 6: Add provenance and draft release publication

- Generate architecture-qualified assets, `SHA256SUMS`, and
  `build-manifest.json`.
- Produce GitHub artifact attestations with job-scoped permissions.
- Create or safely resume a draft release for a valid tag.
- Enforce digest equality and refuse published-release mutation.
- Generate the required security, compatibility, verification, and recovery
  notes from a repository-owned template.

### Step 7: Document and validate operations

- Document the dedicated runner contract and bootstrap checks.
- Update installation docs to lead with release download and verification.
- Document dry-run, tagging, approval, publication, appliance testing, stable
  promotion, reruns, cache maintenance, and runner retirement.
- Run fast CI in GitHub, then run at least one dry-run full build for each
  architecture before enabling tagged publication.

## 9. Verification requirements

### 9.1 Fast workflow

- Runs on pull requests from the same repository and forks without secrets.
- Never schedules a self-hosted runner.
- Passes existing unit/static checks on a valid tree.
- Detects an incorrect IPFire baseline, overlay conflict, Blocky checksum,
  binary version, linkage type, and ELF architecture.
- Has read-only repository permissions and leaves no generated changes.

### 9.2 Metadata and trigger validation

- Correctly derives `0.35.0`, package release `1`, both architectures, and tag
  `blocky-v0.35.0-ipfire1` from the current repository.
- Rejects mismatched tags, unsupported architectures, duplicate assignments,
  malformed versions, unexpected recipe structure, unsafe filenames, and
  shell/meta-character injection fixtures.
- Rejects release tags not reachable from protected `main`.
- Manual dispatch defaults to dry-run and cannot publish merely through a
  crafted input.

### 9.3 Full builds

- A clean `x86_64` build produces exactly one valid architecture-qualified
  release package.
- A clean `aarch64` build produces exactly one valid architecture-qualified
  release package.
- Both packages originate from the pinned IPFire LFS packaging path.
- Package metadata reports `blocky`, version `0.35.0`, release `1`, and service
  `blocky`.
- The nested Blocky binary is v0.35.0, statically linked, and matches the target
  architecture.
- The curated rootfile and actual payload agree.
- Representative inert and enforced configurations pass Blocky's validator.
- A failed architecture build prevents assemble and release jobs.

### 9.4 Assembly and provenance

- The combined manifest has the documented schema, stable serialization, no
  sensitive runner data, and correct package/upstream digests.
- `SHA256SUMS` verifies both packages and the manifest and is bytewise sorted.
- Each published subject has a verifiable GitHub artifact attestation tied to
  the expected repository, workflow, tag commit, and run.
- Renaming the outer asset does not change its internal package payload or
  metadata.

### 9.5 Release lifecycle

- Dry-run execution creates no GitHub tag or Release and uploads temporary
  architecture artifacts for inspection.
- A valid tag creates a draft containing exactly the required assets and
  required notes.
- A rerun with identical outputs is idempotent.
- A rerun with a conflicting digest fails without modifying the release.
- No workflow can replace or delete assets on a published release.
- Publishing is approval-gated and initially marks the release as a
  pre-release.
- Stable promotion reuses the already tested bytes and does not rebuild them.

### 9.6 Security tests

- Fork pull requests cannot reach self-hosted labels, write repository
  contents, request attestations, or access release environments.
- Workflow inputs, tags, recipe fields, archive entries, and manifest values
  are handled as untrusted data.
- Archive inspection rejects path traversal, absolute paths, duplicate paths,
  and unsafe symlink targets before extraction.
- Cleanup tests prove only current-run temporary directories are removed.
- Action dependencies are pinned and a check detects mutable action refs.
- Release and attestation permissions exist only on their owning jobs.

## 10. Success criteria

SPEC-0002 is complete only when all of the following are true:

1. Every pull request receives fast automated feedback covering existing tests,
   overlay compatibility, and pinned upstream artifacts without using a
   self-hosted runner.
2. A trusted dry run builds valid `.ipfire` packages for both `x86_64` and
   `aarch64` from clean checkouts of the pinned inputs.
3. The release workflow cannot be triggered into executing untrusted pull
   request code on the dedicated builder.
4. Release metadata and tag consistency are validated by tested
   repository-owned tooling rather than unchecked workflow interpolation.
5. Both release packages pass structure, rootfile, lifecycle, metadata,
   version, static-linkage, architecture, and Blocky-configuration validation.
6. The workflow emits architecture-qualified packages, deterministic
   `SHA256SUMS`, and a complete non-sensitive `build-manifest.json`.
7. GitHub artifact attestations for every release subject can be verified from
   a separate workstation.
8. A matching protected tag produces a reviewable draft Release only after all
   build and assembly gates pass.
9. Maintainers can publish that draft as an explicitly unofficial pre-release,
   and later promote the exact same bytes after appliance testing.
10. Reruns cannot silently mutate a published release or associate different
    bytes with an existing tag.
11. Installation documentation lets an operator select, verify, transfer, and
    manually install the correct asset without building IPFire locally.
12. Runner, cache, release, recovery, and maintainer procedures are documented
    sufficiently for a maintainer other than the implementer to operate them.

## 11. Risks and safeguards

| Risk | Required safeguard |
| --- | --- |
| Full build exceeds hosted limits | Dedicated adequately sized release runner; hosted CI performs only fast checks |
| Self-hosted runner compromise through a fork | Never schedule it from PR events; trusted main/tag reachability checks; dedicated runner |
| Cross-architecture contamination | Serialized matrix; architecture-specific build/cache directories; ELF validation |
| Stale or poisoned cached source | IPFire and Blocky checksum validation; baseline/version namespacing |
| Release tag does not match package | Tested metadata parser and exact tag contract; fail before self-hosted build |
| One architecture silently missing | Assemble job requires and validates exactly both supported assets |
| Mutable or overwritten release | Draft-only resume rules, digest equality, published-release refusal, new `PAK_VER` for changes |
| User mistakes provenance for Pakfire trust | Prominent unofficial-package wording in workflow, release notes, and install docs |
| CI success mistaken for appliance qualification | Publish first as pre-release; retain mandatory SPEC-0001 appliance promotion gate |
| Workflow command injection | Treat tags/metadata as data; validated outputs; tested helpers; minimal inline shell |
| Archive extraction vulnerability | Validate member paths/types before extraction and use isolated scoped directories |
| Credentials retained on builder | No persisted checkout credentials or signing keys; publication occurs in separate hosted job |
| Destructive cleanup damages caches or host | Run-owned validated temp roots; never recursively delete broad or unresolved paths |

## 12. Definition of ready

This specification is ready for implementation. The architecture-changing
decisions are fixed:

- fast checks run on GitHub-hosted runners;
- full packages are built on a dedicated trusted `x86_64` self-hosted runner;
- the IPFire-native build produces both `x86_64` and cross-built `aarch64`
  packages;
- manual workflow runs are non-publishing dry runs by default;
- protected matching tags create draft GitHub Releases;
- published builds begin as unofficial pre-releases;
- checksums, a build manifest, and GitHub artifact attestations accompany every
  release; and
- stable promotion requires the existing appliance integration matrix and
  reuses the same artifact bytes.

Implementation may adjust runner sizing upward, action commit pins, log
retention, or helper language without changing the design. Changing the trust
boundary, supported architectures, tag/version contract, publication states,
package build origin, or stable-promotion gate requires a follow-up
specification.
