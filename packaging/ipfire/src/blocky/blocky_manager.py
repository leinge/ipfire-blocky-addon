#!/usr/bin/python3
"""Privileged configuration and firewall manager for the IPFire Blocky add-on.

The CGI never calls this module directly.  A small setuid wrapper exposes a
fixed action allowlist and clears its environment before executing this file.
Pure functions accept an explicit Layout/runner so they can be tested without
root or a live firewall.
"""

from __future__ import annotations

import copy
import datetime as dt
import fcntl
import glob
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - exercised on a broken target image
    yaml = None


MAX_CANDIDATE_BYTES = 4 * 1024 * 1024
RESERVED_PREFIX = "_ipfire_blocky_"
DOH_GROUP = f"{RESERVED_PREFIX}doh_bypass"
CLEAR_SECRET_MARKER = "__IPFIRE_BLOCKY_CLEAR_SECRET__"
HOOK_BEGIN = "# BEGIN IPFIRE BLOCKY ADD-ON"
HOOK_BEGIN_JOINED = f"{HOOK_BEGIN} (ORIGINAL HAD NO TRAILING NEWLINE)"
HOOK_END = "# END IPFIRE BLOCKY ADD-ON"
HOOK_BODY = (
    f"{HOOK_BEGIN}\n"
    'if [ -x /usr/lib/blocky/blocky-firewall ]; then\n'
    '    /usr/lib/blocky/blocky-firewall "$1"\n'
    "fi\n"
    f"{HOOK_END}\n"
)


class BlockyError(RuntimeError):
    """Expected, user-visible management failure."""


class DuplicateKeyError(BlockyError):
    """A JSON or YAML mapping contained a duplicate key."""


class Layout:
    """Filesystem layout, rooted elsewhere only for unit/integration tests."""

    def __init__(self, root: Path | str = "/") -> None:
        self.root = Path(root)

    def path(self, absolute: str) -> Path:
        return self.root / absolute.lstrip("/")

    @property
    def state_dir(self) -> Path:
        return self.path("/var/ipfire/blocky")

    @property
    def canonical_config(self) -> Path:
        return self.state_dir / "config.json"

    @property
    def settings(self) -> Path:
        return self.state_dir / "settings.json"

    @property
    def pending(self) -> Path:
        return self.state_dir / "pending/candidate.json"

    @property
    def status(self) -> Path:
        return self.state_dir / "status.json"

    @property
    def runtime_config(self) -> Path:
        return self.path("/etc/blocky/config.yml")

    @property
    def enforcement_manifest(self) -> Path:
        return self.path("/var/lib/blocky/enforcement.json")

    @property
    def last_known_good(self) -> Path:
        return self.path("/var/lib/blocky/last-known-good")

    @property
    def network_settings(self) -> Path:
        return self.path("/var/ipfire/ethernet/settings")

    @property
    def provider_catalog(self) -> Path:
        return self.path("/usr/share/blocky/doh-providers.json")

    @property
    def default_config(self) -> Path:
        return self.path("/usr/share/blocky/default-config.json")

    @property
    def default_settings(self) -> Path:
        return self.path("/usr/share/blocky/default-settings.json")

    @property
    def firewall_local(self) -> Path:
        return self.path("/etc/sysconfig/firewall.local")

    @property
    def lock(self) -> Path:
        return self.path("/run/lock/blocky-manager.lock")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate key: {key}")
        result[key] = value
    return result


def load_json_bytes(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except UnicodeDecodeError as error:
        raise BlockyError("configuration is not valid UTF-8") from error
    except json.JSONDecodeError as error:
        raise BlockyError(f"invalid JSON: {error}") from error


def load_json(
    path: Path,
    *,
    max_bytes: int = MAX_CANDIDATE_BYTES,
    expected_uid: int | None = None,
) -> Any:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise BlockyError(f"cannot open {path}: {error.strerror}") from error

    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise BlockyError(f"{path} is not a regular file")
        if expected_uid is not None and file_stat.st_uid != expected_uid:
            raise BlockyError(f"{path} has an unexpected owner")
        if file_stat.st_mode & 0o022:
            raise BlockyError(f"{path} must not be group/world writable")
        if not file_stat.st_size <= max_bytes:
            raise BlockyError(f"{path} exceeds the {max_bytes}-byte limit")
        data = b""
        while True:
            chunk = os.read(descriptor, min(65536, max_bytes + 1 - len(data)))
            if not chunk:
                break
            data += chunk
            if len(data) > max_bytes:
                raise BlockyError(f"{path} exceeds the {max_bytes}-byte limit")
    finally:
        os.close(descriptor)
    return load_json_bytes(data)


def load_yaml_or_json(text: str) -> Any:
    """Load imported YAML safely, rejecting aliases and duplicate mappings."""

    if len(text.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise BlockyError("import exceeds the 4 MiB limit")
    try:
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, DuplicateKeyError):
        pass

    if yaml is None:
        raise BlockyError("YAML import is unavailable because PyYAML is not installed")

    try:
        if any(
            isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
            for token in yaml.scan(text)
        ):
            raise BlockyError("YAML anchors and aliases are not accepted")
    except yaml.YAMLError as error:
        raise BlockyError(f"invalid YAML: {error}") from error

    class UniqueSafeLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader: Any, node: Any, deep: bool = False) -> Any:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise DuplicateKeyError(f"duplicate key: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueSafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    try:
        value = yaml.load(text, Loader=UniqueSafeLoader)
    except (yaml.YAMLError, DuplicateKeyError) as error:
        raise BlockyError(f"invalid YAML: {error}") from error
    return value


def read_ipfire_settings(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if re.fullmatch(r"[A-Z0-9_]+", key):
            values[key] = value
    return values


def zone_info(network: dict[str, str], zone: str) -> dict[str, str] | None:
    prefix = zone.upper()
    interface = network.get(f"{prefix}_DEV", "").strip()
    address = network.get(f"{prefix}_ADDRESS", "").strip()
    net_address = network.get(f"{prefix}_NETADDRESS", address).strip()
    netmask = network.get(f"{prefix}_NETMASK", "").strip()
    if not interface or not address or not netmask:
        return None
    try:
        ipaddress.IPv4Address(address)
        network_value = ipaddress.IPv4Network(f"{net_address}/{netmask}", strict=False)
    except ValueError as error:
        raise BlockyError(f"IPFire {zone.upper()} network settings are invalid: {error}") from error
    return {
        "interface": interface,
        "address": address,
        "cidr": str(network_value),
    }


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BlockyError(f"{name} must be an object")
    return value


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BlockyError(f"{name} must be an array of strings")
    return value


def _check_reserved(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise BlockyError(f"configuration key at {path or '/'} must be a string")
            if key.startswith(RESERVED_PREFIX):
                raise BlockyError(f"{path + '.' if path else ''}{key} uses a reserved name")
            _check_reserved(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_reserved(child, f"{path}[{index}]")


def validate_settings(settings: Any) -> dict[str, Any]:
    result = _require_object(settings, "settings")
    if set(result) - {"schemaVersion", "zones", "doh"}:
        raise BlockyError("settings contains unknown fields")
    if result.get("schemaVersion") != 1:
        raise BlockyError("settings.schemaVersion must be 1")
    zones = _require_object(result.get("zones"), "settings.zones")
    if set(zones) - {"green", "blue"}:
        raise BlockyError("only GREEN and BLUE zones are supported")
    for name in ("green", "blue"):
        zone = _require_object(zones.get(name), f"settings.zones.{name}")
        if set(zone) - {"selected", "route", "bypass"}:
            raise BlockyError(f"settings.zones.{name} contains unknown fields")
        for field in ("selected", "route", "bypass"):
            if not isinstance(zone.get(field), bool):
                raise BlockyError(f"settings.zones.{name}.{field} must be boolean")
        if zone["route"] and not zone["selected"]:
            raise BlockyError(f"{name.upper()} routing requires zone selection")
        if zone["bypass"] and not zone["route"]:
            raise BlockyError(f"{name.upper()} bypass prevention requires routing")
    doh = _require_object(result.get("doh"), "settings.doh")
    expected_doh = {
        "providers", "customDomains", "customIPv4", "exceptDomains", "exceptIPv4"
    }
    if set(doh) - expected_doh:
        raise BlockyError("settings.doh contains unknown fields")
    for field in (
        "providers",
        "customDomains",
        "customIPv4",
        "exceptDomains",
        "exceptIPv4",
    ):
        _string_list(doh.get(field), f"settings.doh.{field}")
    return result


def validate_user_config(config: Any) -> dict[str, Any]:
    result = _require_object(config, "config")
    _check_reserved(result)
    upstreams = _require_object(result.get("upstreams"), "upstreams")
    groups = _require_object(upstreams.get("groups"), "upstreams.groups")
    default = groups.get("default")
    if not isinstance(default, list) or not default or any(
        not isinstance(item, str) or not item.strip() for item in default
    ):
        raise BlockyError("upstreams.groups.default must contain at least one resolver")
    if "ports" in result:
        ports = _require_object(result["ports"], "ports")
        for family in ("http", "https", "tls"):
            listeners = ports.get(family, [])
            if not isinstance(listeners, list):
                listeners = [listeners]
            for listener in listeners:
                port = None
                if isinstance(listener, int) and not isinstance(listener, bool):
                    port = listener
                elif isinstance(listener, str):
                    match = re.search(r"(?:^|:)(\d+)$", listener.strip())
                    if match:
                        port = int(match.group(1))
                if port is not None and port < 1024:
                    raise BlockyError(
                        f"ports.{family} listener {listener!r} requires a privileged port; "
                        "v1 grants no bind capability"
                    )
    if "blocking" in result:
        _require_object(result["blocking"], "blocking")
    return result


def _catalog_index(catalog: Any) -> dict[str, dict[str, Any]]:
    document = _require_object(catalog, "DoH provider catalog")
    if document.get("schemaVersion") != 1:
        raise BlockyError("unsupported DoH provider catalog version")
    providers = document.get("providers")
    if not isinstance(providers, list):
        raise BlockyError("DoH provider catalog providers must be an array")
    result: dict[str, dict[str, Any]] = {}
    for provider in providers:
        item = _require_object(provider, "DoH provider")
        provider_id = item.get("id")
        if not isinstance(provider_id, str) or not re.fullmatch(r"[a-z0-9-]+", provider_id):
            raise BlockyError("invalid DoH provider ID")
        if provider_id in result:
            raise BlockyError(f"duplicate DoH provider: {provider_id}")
        _string_list(item.get("domains", []), f"provider {provider_id} domains")
        _string_list(item.get("ipv4", []), f"provider {provider_id} IPv4")
        result[provider_id] = item
    return result


def _unique_strings(values: Iterable[str]) -> list[str]:
    return sorted({value.strip() for value in values if value.strip()})


def _validate_domain_pattern(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or len(candidate) > 253:
        raise BlockyError(f"invalid DoH domain: {value}")
    plain = candidate[2:] if candidate.startswith("*.") else candidate
    labels = plain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise BlockyError(f"invalid DoH domain: {value}")
    return candidate


def _validate_ipv4_network(value: str) -> str:
    try:
        return str(ipaddress.IPv4Network(value.strip(), strict=False))
    except ValueError as error:
        raise BlockyError(f"invalid DoH IPv4 network {value}: {error}") from error


def build_runtime(
    user_config: dict[str, Any],
    settings: dict[str, Any],
    network: dict[str, str],
    catalog: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge protected IPFire integration values into a Blocky document."""

    validate_user_config(user_config)
    validate_settings(settings)
    providers = _catalog_index(catalog)
    runtime = copy.deepcopy(user_config)
    ports = runtime.setdefault("ports", {})
    listeners = ["127.0.0.1:1053"]
    manifest_zones: dict[str, dict[str, Any]] = {}

    for name in ("green", "blue"):
        desired = settings["zones"][name]
        info = zone_info(network, name)
        if desired["selected"]:
            if info is None:
                raise BlockyError(f"{name.upper()} is selected but is not configured in IPFire")
            listeners.append(f"{info['address']}:1053")
        if desired["route"]:
            if info is None:
                raise BlockyError(f"{name.upper()} routing has no usable IPFire interface")
            manifest_zones[name] = {
                **info,
                "route": True,
                "bypass": desired["bypass"],
            }
    ports["dns"] = listeners

    selected_provider_ids = settings["doh"]["providers"]
    unknown = sorted(set(selected_provider_ids) - set(providers))
    if unknown:
        raise BlockyError(f"unknown DoH providers: {', '.join(unknown)}")

    domains: list[str] = []
    ipv4_networks: list[str] = []
    for provider_id in selected_provider_ids:
        provider = providers[provider_id]
        domains.extend(provider.get("domains", []))
        ipv4_networks.extend(provider.get("ipv4", []))
    domains.extend(settings["doh"]["customDomains"])
    ipv4_networks.extend(settings["doh"]["customIPv4"])

    domains = _unique_strings(_validate_domain_pattern(value) for value in domains)
    except_domains = _unique_strings(
        _validate_domain_pattern(value) for value in settings["doh"]["exceptDomains"]
    )
    ipv4_networks = _unique_strings(_validate_ipv4_network(value) for value in ipv4_networks)
    except_ipv4 = _unique_strings(
        _validate_ipv4_network(value) for value in settings["doh"]["exceptIPv4"]
    )

    bypass_zones = [item for item in manifest_zones.values() if item["bypass"]]
    if bypass_zones and (domains or except_domains):
        blocking = runtime.setdefault("blocking", {})
        denylists = blocking.setdefault("denylists", {})
        denylists[DOH_GROUP] = ["\n".join(domains) + "\n"] if domains else []
        if except_domains:
            allowlists = blocking.setdefault("allowlists", {})
            allowlists[DOH_GROUP] = ["\n".join(except_domains) + "\n"]
        client_groups = blocking.setdefault("clientGroupsBlock", {})
        for zone in bypass_zones:
            groups = client_groups.setdefault(zone["cidr"], [])
            if not isinstance(groups, list):
                raise BlockyError(f"blocking.clientGroupsBlock.{zone['cidr']} must be an array")
            if DOH_GROUP not in groups:
                groups.append(DOH_GROUP)

    manifest = {
        "schemaVersion": 1,
        "active": bool(manifest_zones),
        "zones": manifest_zones,
        "dohIPv4": ipv4_networks,
        "dohExceptIPv4": except_ipv4,
    }
    return runtime, manifest


def generated_config_bytes(runtime: dict[str, Any]) -> bytes:
    return (
        "# Generated by the IPFire Blocky add-on. Do not edit this file.\n"
        + json.dumps(runtime, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, data: bytes, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: Any, mode: int = 0o640) -> None:
    atomic_write(
        path,
        (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
        mode,
    )


def chown_group(path: Path, group_user: str) -> None:
    try:
        account = pwd.getpwnam(group_user)
    except KeyError:
        return
    os.chown(path, 0, account.pw_gid)


def redact(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {item_key: redact(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if key.lower() in {"password", "sentinelpassword"} and value:
        return "********"
    if key == "target" and isinstance(value, str):
        return re.sub(r"(://[^:/@]+:)[^@/]+(@)", r"\1********\2", value)
    return value


def restore_secret_markers(candidate: Any, active: Any, key: str = "") -> Any:
    """Replace UI redaction sentinels with the active secret values."""

    if isinstance(candidate, dict) and isinstance(active, dict):
        return {
            item_key: restore_secret_markers(item_value, active.get(item_key), item_key)
            for item_key, item_value in candidate.items()
        }
    if isinstance(candidate, list) and isinstance(active, list):
        return [
            restore_secret_markers(item, active[index] if index < len(active) else None, key)
            for index, item in enumerate(candidate)
        ]
    if key.lower() in {"password", "sentinelpassword"}:
        if candidate == CLEAR_SECRET_MARKER:
            return ""
        if candidate in {"********", ""}:
            return active
    if key == "target" and candidate == CLEAR_SECRET_MARKER:
        return ""
    if key == "target" and candidate == "" and isinstance(active, str) and active:
        return active
    if (
        key == "target"
        and isinstance(candidate, str)
        and ":********@" in candidate
        and isinstance(active, str)
    ):
        return active
    return candidate


def sanitize_error(message: str, document: Any) -> str:
    secrets: set[str] = set()

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, child_key)
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif isinstance(value, str):
            if key.lower() in {"password", "sentinelpassword"} and value:
                secrets.add(value)
            elif key == "target":
                match = re.search(r"://[^:/@]+:([^@/]+)@", value)
                if match:
                    secrets.add(match.group(1))

    collect(document)
    sanitized = message
    for secret in sorted(secrets, key=len, reverse=True):
        sanitized = sanitized.replace(secret, "********")
    return sanitized


CommandRunner = Callable[[list[str], bool], subprocess.CompletedProcess[str]]


def default_runner(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def _delete_all_rules(
    runner: CommandRunner, table: str | None, chain: str, rule: list[str]
) -> None:
    prefix = ["/sbin/iptables", "--wait"]
    if table:
        prefix += ["-t", table]
    while runner(prefix + ["-D", chain] + rule, False).returncode == 0:
        pass


def remove_firewall(runner: CommandRunner = default_runner) -> None:
    jumps = [
        (None, "CUSTOMFORWARD", ["-j", "BLOCKY_FWD"]),
        (None, "CUSTOMINPUT", ["-j", "BLOCKY_IN"]),
        ("nat", "CUSTOMPREROUTING", ["-j", "BLOCKY_PRE"]),
    ]
    for table, parent, rule in jumps:
        _delete_all_rules(runner, table, parent, rule)
    chains = (
        ("nat", "BLOCKY_PRE"),
        (None, "BLOCKY_IN"),
        (None, "BLOCKY_FWD"),
        ("nat", "BLOCKY_PRE_A"),
        ("nat", "BLOCKY_PRE_B"),
        (None, "BLOCKY_IN_A"),
        (None, "BLOCKY_IN_B"),
        (None, "BLOCKY_FWD_A"),
        (None, "BLOCKY_FWD_B"),
    )
    for table, chain in chains:
        command = ["/sbin/iptables", "--wait"]
        if table:
            command += ["-t", table]
        runner(command + ["-F", chain], False)
        runner(command + ["-X", chain], False)
    for name in (
        "blocky_doh_v4", "blocky_doh_allow_v4",
        "blocky_doh_v4_a", "blocky_doh_allow_v4_a",
        "blocky_doh_v4_b", "blocky_doh_allow_v4_b",
        "blocky_doh_v4_a_new", "blocky_doh_allow_v4_a_new",
        "blocky_doh_v4_b_new", "blocky_doh_allow_v4_b_new",
    ):
        runner(["/sbin/ipset", "destroy", name], False)


def _prepare_ipset(name: str, networks: list[str], runner: CommandRunner) -> None:
    temporary = f"{name}_new"
    runner(["/sbin/ipset", "destroy", temporary], False)
    runner(["/sbin/ipset", "create", temporary, "hash:net", "family", "inet"], True)
    for network in networks:
        runner(["/sbin/ipset", "add", temporary, network], True)
    if (
        runner(
            ["/sbin/ipset", "create", name, "hash:net", "family", "inet"],
            False,
        ).returncode
        != 0
    ):
        runner(["/sbin/ipset", "flush", name], True)
    runner(["/sbin/ipset", "swap", temporary, name], True)
    runner(["/sbin/ipset", "destroy", temporary], True)


def _iptables_command(table: str | None) -> list[str]:
    command = ["/sbin/iptables", "--wait"]
    if table:
        command += ["-t", table]
    return command


def _rule_exists(
    runner: CommandRunner, table: str | None, chain: str, rule: list[str]
) -> bool:
    return runner(_iptables_command(table) + ["-C", chain] + rule, False).returncode == 0


def _ensure_chain(runner: CommandRunner, table: str | None, chain: str) -> None:
    if runner(_iptables_command(table) + ["-L", chain, "-n"], False).returncode != 0:
        runner(_iptables_command(table) + ["-N", chain], True)


def _reset_chain(runner: CommandRunner, table: str | None, chain: str) -> None:
    command = _iptables_command(table)
    runner(command + ["-F", chain], False)
    runner(command + ["-X", chain], False)
    runner(command + ["-N", chain], True)


def reconcile_firewall(
    manifest: dict[str, Any], runner: CommandRunner = default_runner
) -> None:
    if not manifest.get("active"):
        remove_firewall(runner)
        return

    anchors = (("nat", "BLOCKY_PRE"), (None, "BLOCKY_IN"), (None, "BLOCKY_FWD"))
    for table, chain in anchors:
        _ensure_chain(runner, table, chain)

    active_by_anchor: dict[str, str | None] = {}
    for table, anchor in anchors:
        generations = {
            suffix
            for suffix in ("A", "B")
            if _rule_exists(runner, table, anchor, ["-j", f"{anchor}_{suffix}"])
        }
        if len(generations) > 1:
            raise BlockyError(f"ambiguous firewall generation in {anchor}")
        active_by_anchor[anchor] = next(iter(generations), None)
    parents = (
        ("nat", "CUSTOMPREROUTING", "BLOCKY_PRE"),
        (None, "CUSTOMINPUT", "BLOCKY_IN"),
        (None, "CUSTOMFORWARD", "BLOCKY_FWD"),
    )
    for table, parent, anchor in parents:
        if active_by_anchor[anchor] is None and _rule_exists(
            runner, table, parent, ["-j", anchor]
        ):
            raise BlockyError(f"reachable firewall anchor {anchor} has no valid generation")
    next_by_anchor = {
        anchor: "B" if active_by_anchor[anchor] == "A" else "A"
        for _, anchor in anchors
    }
    set_suffix = next_by_anchor["BLOCKY_FWD"].lower()
    blocked_set = f"blocky_doh_v4_{set_suffix}"
    allowed_set = f"blocky_doh_allow_v4_{set_suffix}"

    # Populate an inactive generation first. The current generation remains
    # reachable until every replacement rule is ready, so a failed update does
    # not briefly expose an unfiltered path.
    for table, anchor in anchors:
        _reset_chain(runner, table, f"{anchor}_{next_by_anchor[anchor]}")
    _prepare_ipset(blocked_set, manifest.get("dohIPv4", []), runner)
    _prepare_ipset(allowed_set, manifest.get("dohExceptIPv4", []), runner)

    for zone in manifest.get("zones", {}).values():
        interface = zone["interface"]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", interface):
            raise BlockyError(f"unsafe interface name in enforcement manifest: {interface}")
        for protocol in ("udp", "tcp"):
            runner(
                [
                    "/sbin/iptables", "--wait", "-t", "nat", "-A",
                    f"BLOCKY_PRE_{next_by_anchor['BLOCKY_PRE']}",
                    "-i", interface, "-p", protocol, "--dport", "53", "-j", "REDIRECT",
                    "--to-ports", "1053",
                ],
                True,
            )
            runner(
                [
                    "/sbin/iptables", "--wait", "-A",
                    f"BLOCKY_IN_{next_by_anchor['BLOCKY_IN']}",
                    "-i", interface,
                    "-p", protocol, "--dport", "1053", "-j", "ACCEPT",
                ],
                True,
            )
        if zone.get("bypass"):
            for protocol in ("udp", "tcp"):
                runner(
                    [
                        "/sbin/iptables", "--wait", "-A",
                        f"BLOCKY_FWD_{next_by_anchor['BLOCKY_FWD']}",
                        "-i", interface,
                        "-p", protocol, "--dport", "53", "-j", "REJECT",
                    ],
                    True,
                )
                runner(
                    [
                        "/sbin/iptables", "--wait", "-A",
                        f"BLOCKY_FWD_{next_by_anchor['BLOCKY_FWD']}",
                        "-i", interface,
                        "-p", protocol, "--dport", "853", "-j", "REJECT",
                    ],
                    True,
                )
                runner(
                    [
                        "/sbin/iptables", "--wait", "-A",
                        f"BLOCKY_FWD_{next_by_anchor['BLOCKY_FWD']}",
                        "-i", interface,
                        "-p", protocol, "--dport", "443", "-m", "set", "--match-set",
                        allowed_set, "dst", "-j", "RETURN",
                    ],
                    True,
                )
                runner(
                    [
                        "/sbin/iptables", "--wait", "-A",
                        f"BLOCKY_FWD_{next_by_anchor['BLOCKY_FWD']}",
                        "-i", interface,
                        "-p", protocol, "--dport", "443", "-m", "set", "--match-set",
                        blocked_set, "dst", "-j", "REJECT",
                    ],
                    True,
                )

    for table, anchor in anchors:
        next_suffix = next_by_anchor[anchor]
        active_suffix = active_by_anchor[anchor]
        new_rule = ["-j", f"{anchor}_{next_suffix}"]
        old_rule = ["-j", f"{anchor}_{active_suffix}"] if active_suffix else None
        if old_rule and _rule_exists(runner, table, anchor, old_rule):
            runner(_iptables_command(table) + ["-R", anchor, "1"] + new_rule, True)
        else:
            # First activation: make the completed generation reachable from its
            # anchor before adding the anchor to IPFire's packet path.
            runner(_iptables_command(table) + ["-F", anchor], True)
            runner(_iptables_command(table) + ["-A", anchor] + new_rule, True)

    for table, parent, anchor in parents:
        rule = ["-j", anchor]
        if not _rule_exists(runner, table, parent, rule):
            runner(_iptables_command(table) + ["-I", parent, "1"] + rule, True)

    for table, anchor in anchors:
        active_suffix = active_by_anchor[anchor]
        if active_suffix:
            old_chain = f"{anchor}_{active_suffix}"
            runner(_iptables_command(table) + ["-F", old_chain], False)
            runner(_iptables_command(table) + ["-X", old_chain], False)
    old_forward_suffix = active_by_anchor["BLOCKY_FWD"]
    if old_forward_suffix:
        old_set_suffix = old_forward_suffix.lower()
        runner(["/sbin/ipset", "destroy", f"blocky_doh_v4_{old_set_suffix}"], False)
        runner(
            ["/sbin/ipset", "destroy", f"blocky_doh_allow_v4_{old_set_suffix}"],
            False,
        )


def update_firewall_hook(path: Path, install: bool) -> None:
    if path.is_symlink():
        raise BlockyError("refusing symlinked firewall.local")
    if path.exists():
        original_stat = path.stat()
        original = path.read_text(encoding="utf-8")
        mode = stat.S_IMODE(original_stat.st_mode)
        owner = (original_stat.st_uid, original_stat.st_gid)
    else:
        original = "#!/bin/sh\n"
        mode = 0o755
        owner = (os.getuid(), os.getgid())
    starts = original.count(HOOK_BEGIN)
    ends = original.count(HOOK_END)
    if starts != ends or starts > 1:
        raise BlockyError("ambiguous Blocky marker in firewall.local")
    if starts == 1:
        if HOOK_BEGIN_JOINED in original:
            pattern = re.compile(
                rf"(?ms)\n^{re.escape(HOOK_BEGIN_JOINED)}\n.*?"
                rf"^{re.escape(HOOK_END)}\n?"
            )
        else:
            pattern = re.compile(
                rf"(?ms)^{re.escape(HOOK_BEGIN)}\n.*?^{re.escape(HOOK_END)}\n?"
            )
        cleaned, count = pattern.subn("", original)
        if count != 1:
            raise BlockyError("malformed Blocky marker in firewall.local")
    else:
        cleaned = original
    if install:
        if cleaned and not cleaned.endswith("\n"):
            cleaned += "\n" + HOOK_BODY.replace(HOOK_BEGIN, HOOK_BEGIN_JOINED, 1)
        else:
            cleaned += HOOK_BODY
    atomic_write(path, cleaned.encode("utf-8"), mode)
    os.chown(path, *owner)


def enforcement_active(settings: dict[str, Any]) -> bool:
    return any(zone.get("route") for zone in settings.get("zones", {}).values())


class Manager:
    def __init__(self, layout: Layout = Layout(), runner: CommandRunner = default_runner) -> None:
        self.layout = layout
        self.runner = runner

    def _run(self, command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.runner(command, check)

    def _locked(self) -> Any:
        self.layout.lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.layout.lock,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as error:
            raise BlockyError(f"cannot open manager lock: {error.strerror}") from error
        file_stat = os.fstat(descriptor)
        expected_uid = 0 if self.layout.root == Path("/") else os.getuid()
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != expected_uid:
            os.close(descriptor)
            raise BlockyError("manager lock has unsafe ownership or type")
        stream = os.fdopen(descriptor, "r+", encoding="utf-8")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        return stream

    def initialize(self) -> None:
        self.layout.state_dir.mkdir(parents=True, exist_ok=True)
        (self.layout.state_dir / "pending").mkdir(parents=True, exist_ok=True)
        self.layout.enforcement_manifest.parent.mkdir(parents=True, exist_ok=True)
        self.layout.runtime_config.parent.mkdir(parents=True, exist_ok=True)
        if not self.layout.canonical_config.exists():
            atomic_write(self.layout.canonical_config, self.layout.default_config.read_bytes())
            chown_group(self.layout.canonical_config, "nobody")
        if not self.layout.settings.exists():
            atomic_write(self.layout.settings, self.layout.default_settings.read_bytes())
            chown_group(self.layout.settings, "nobody")
        self.render_active(validate_binary=False)

    def _documents(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
        config = validate_user_config(load_json(self.layout.canonical_config))
        settings = validate_settings(load_json(self.layout.settings))
        catalog = load_json(self.layout.provider_catalog)
        network = read_ipfire_settings(self.layout.network_settings)
        return config, settings, catalog, network

    def render_active(self, validate_binary: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
        config, settings, catalog, network = self._documents()
        runtime, manifest = build_runtime(config, settings, network, catalog)
        candidate = generated_config_bytes(runtime)
        if validate_binary:
            self.validate_runtime(candidate)
        atomic_write(self.layout.runtime_config, candidate)
        chown_group(self.layout.runtime_config, "blocky")
        write_json(self.layout.enforcement_manifest, manifest, 0o600)
        return runtime, manifest

    def snapshot(self, documents: dict[Path, bytes | None]) -> None:
        self.layout.last_known_good.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.layout.last_known_good, 0o700)
        names = {
            self.layout.canonical_config: "config.json",
            self.layout.settings: "settings.json",
            self.layout.runtime_config: "config.yml",
            self.layout.enforcement_manifest: "enforcement.json",
        }
        for source, destination_name in names.items():
            destination = self.layout.last_known_good / destination_name
            content = documents.get(source)
            if content is None:
                destination.unlink(missing_ok=True)
            else:
                atomic_write(destination, content, 0o600)

    def validate_runtime(self, candidate: bytes) -> None:
        self.layout.runtime_config.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".candidate.", dir=self.layout.runtime_config.parent)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o640)
            try:
                account = pwd.getpwnam("blocky")
                os.fchown(descriptor, 0, account.pw_gid)
            except KeyError:
                account = None
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            descriptor = -1
            command = ["/usr/bin/blocky", "--config", str(temporary), "validate"]
            try:
                blocky = account or pwd.getpwnam("blocky")
                command = [
                    "/usr/sbin/runuser", "-u", blocky.pw_name, "--",
                ] + command
            except KeyError:
                pass
            result = self._run(command, False)
            if result.returncode:
                message = (result.stderr or result.stdout or "Blocky validation failed").strip()
                try:
                    document = load_yaml_or_json(candidate.decode("utf-8"))
                except (BlockyError, UnicodeDecodeError):
                    document = {}
                raise BlockyError(sanitize_error(message, document)[-4096:])
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def healthy(self) -> bool:
        result = self._run(
            ["/usr/bin/blocky", "healthcheck", "--bindip", "127.0.0.1", "--port", "1053"],
            False,
        )
        return result.returncode == 0

    def knot_healthy(self) -> bool:
        return self._run(
            ["/usr/bin/kdig", "@127.0.0.1", "localhost", "A", "+timeout=2", "+retry=0"],
            False,
        ).returncode == 0

    def process_running(self) -> bool:
        return self._run(["/bin/pidof", "blocky"], False).returncode == 0

    def configuration_valid(self) -> bool:
        command = ["/usr/bin/blocky", "--config", str(self.layout.runtime_config), "validate"]
        try:
            account = pwd.getpwnam("blocky")
            command = ["/usr/sbin/runuser", "-u", account.pw_name, "--"] + command
        except KeyError:
            pass
        return self._run(command, False).returncode == 0

    def boot_enabled(self) -> bool:
        return bool(glob.glob(str(self.layout.path("/etc/rc.d/rc3.d/S??blocky"))))

    def service(self, action: str) -> None:
        settings = validate_settings(load_json(self.layout.settings))
        if action in {"stop", "disable"} and enforcement_active(settings):
            raise BlockyError("disable routing and bypass enforcement before stopping Blocky")
        if action in {"start", "stop", "restart"}:
            result = self._run(["/etc/rc.d/init.d/blocky", action], False)
            if result.returncode:
                raise BlockyError((result.stderr or result.stdout or f"service {action} failed")[-4096:])
            if action in {"start", "restart"} and not self.healthy():
                raise BlockyError("Blocky started but its loopback health check failed")
            return
        enabled = self.layout.path("/etc/rc.d/rc3.d/S50blocky")
        disabled = self.layout.path("/etc/rc.d/rc3.d/off/S50blocky")
        disabled.parent.mkdir(parents=True, exist_ok=True)
        if action == "enable":
            source, destination, link_target = disabled, enabled, "../init.d/blocky"
        elif action == "disable":
            source, destination, link_target = enabled, disabled, "../../init.d/blocky"
        else:
            raise BlockyError(f"unsupported service action: {action}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}.{os.getpid()}"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(link_target)
        os.replace(temporary, destination)
        if source != destination:
            source.unlink(missing_ok=True)

    def _apply(self) -> None:
        with self._locked():
            try:
                pending_owner = pwd.getpwnam("nobody").pw_uid
            except KeyError:
                pending_owner = None
            envelope = _require_object(
                load_json(self.layout.pending, expected_uid=pending_owner), "candidate"
            )
            if set(envelope) - {"config", "settings", "import"}:
                raise BlockyError("candidate contains unknown top-level fields")
            config_value = envelope.get("config")
            if "import" in envelope:
                if not isinstance(envelope["import"], str):
                    raise BlockyError("candidate import must be text")
                config_value = load_yaml_or_json(envelope["import"])
            active_config = load_json(self.layout.canonical_config)
            config_value = restore_secret_markers(config_value, active_config)
            config = validate_user_config(config_value)
            settings = validate_settings(envelope.get("settings"))
            catalog = load_json(self.layout.provider_catalog)
            network = read_ipfire_settings(self.layout.network_settings)
            runtime, manifest = build_runtime(config, settings, network, catalog)
            candidate_runtime = generated_config_bytes(runtime)
            self.validate_runtime(candidate_runtime)

            previous = {
                path: path.read_bytes() if path.exists() else None
                for path in (
                    self.layout.canonical_config,
                    self.layout.settings,
                    self.layout.runtime_config,
                    self.layout.enforcement_manifest,
                )
            }
            self.snapshot(previous)
            previously_running = self.process_running()
            previous_settings = validate_settings(load_json(self.layout.settings))
            first_enforcement = enforcement_active(settings) and not enforcement_active(previous_settings)
            disabling_enforcement = (
                enforcement_active(previous_settings) and not enforcement_active(settings)
            )
            started_for_apply = False
            try:
                write_json(self.layout.canonical_config, config)
                chown_group(self.layout.canonical_config, "nobody")
                write_json(self.layout.settings, settings)
                chown_group(self.layout.settings, "nobody")
                atomic_write(self.layout.runtime_config, candidate_runtime)
                chown_group(self.layout.runtime_config, "blocky")
                write_json(self.layout.enforcement_manifest, manifest, 0o600)
                if previously_running:
                    self.service("restart")
                elif enforcement_active(settings):
                    started_for_apply = True
                    self.service("start")
                if first_enforcement and not self.healthy():
                    raise BlockyError("refusing first enforcement activation: Blocky is unhealthy")
                if disabling_enforcement and not self.knot_healthy():
                    raise BlockyError("refusing to disable enforcement: Knot is not answering")
                reconcile_firewall(manifest, self.runner)
            except Exception:
                for path, data in previous.items():
                    if data is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, data, 0o600 if path == self.layout.enforcement_manifest else 0o640)
                if previously_running:
                    self._run(["/etc/rc.d/init.d/blocky", "restart"], False)
                elif started_for_apply:
                    self._run(["/etc/rc.d/init.d/blocky", "stop"], False)
                chown_group(self.layout.canonical_config, "nobody")
                chown_group(self.layout.settings, "nobody")
                chown_group(self.layout.runtime_config, "blocky")
                old_manifest = load_json(self.layout.enforcement_manifest) if self.layout.enforcement_manifest.exists() else {"active": False}
                reconcile_firewall(old_manifest, self.runner)
                raise
            finally:
                self.layout.pending.unlink(missing_ok=True)
            self.write_status("configuration applied")

    def apply(self) -> None:
        try:
            self._apply()
        finally:
            self.layout.pending.unlink(missing_ok=True)

    def firewall(self, action: str) -> None:
        if action not in {"start", "stop", "reload"}:
            raise BlockyError(f"unsupported firewall action: {action}")
        with self._locked():
            if action == "stop":
                remove_firewall(self.runner)
                return
            config, settings, catalog, network = self._documents()
            _, manifest = build_runtime(config, settings, network, catalog)
            write_json(self.layout.enforcement_manifest, manifest, 0o600)
            reconcile_firewall(manifest, self.runner)

    def recover(self) -> None:
        with self._locked():
            settings = validate_settings(load_json(self.layout.settings))
            for zone in settings["zones"].values():
                zone["bypass"] = False
                zone["route"] = False
            write_json(self.layout.settings, settings)
            chown_group(self.layout.settings, "nobody")
            self.render_active(validate_binary=False)
            remove_firewall(self.runner)
            if not self.knot_healthy():
                raise BlockyError("enforcement is disabled, but Knot did not answer on 127.0.0.1:53")
            self.write_status("emergency recovery disabled enforcement")

    def status_document(self) -> dict[str, Any]:
        try:
            settings = validate_settings(load_json(self.layout.settings))
            selected = [name for name, zone in settings["zones"].items() if zone["selected"]]
            routed = [name for name, zone in settings["zones"].items() if zone["route"]]
            bypass = [name for name, zone in settings["zones"].items() if zone["bypass"]]
        except BlockyError:
            selected, routed, bypass = [], [], []
        running = self.process_running()
        healthy = running and self.healthy()
        pid_result = self._run(["/bin/pidof", "blocky"], False)
        version_result = self._run(["/usr/bin/blocky", "version"], False)
        blocky_version = "unknown"
        if version_result.returncode == 0:
            for line in (version_result.stdout or "").splitlines():
                if line.startswith("Version:"):
                    blocky_version = line.split(":", 1)[1].strip()
                    break
        package_version = "unknown"
        meta = self.layout.path("/opt/pakfire/db/installed/meta-blocky")
        if meta.exists():
            metadata: dict[str, str] = {}
            for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key] = value.strip()
            version = metadata.get("ProgVersion")
            release = metadata.get("Release")
            if version:
                package_version = f"{version}-{release}" if release else version
        return {
            "schemaVersion": 1,
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "running": running,
            "healthy": healthy,
            "configurationValid": self.configuration_valid(),
            "bootEnabled": self.boot_enabled(),
            "pid": (pid_result.stdout or "").strip(),
            "user": "blocky",
            "blockyVersion": blocky_version,
            "packageVersion": package_version,
            "selectedZones": selected,
            "routedZones": routed,
            "bypassZones": bypass,
            "enforcementActive": bool(routed),
            "enforcedDown": bool(routed) and not healthy,
        }

    def write_status(self, message: str = "") -> dict[str, Any]:
        status = self.status_document()
        status["message"] = message[-4096:]
        if self.layout.status.exists():
            try:
                previous = load_json(self.layout.status)
                if previous.get("lastSuccessfulApply"):
                    status["lastSuccessfulApply"] = previous["lastSuccessfulApply"]
            except BlockyError:
                pass
        if message == "configuration applied":
            status["lastSuccessfulApply"] = status["time"]
        write_json(self.layout.status, status)
        chown_group(self.layout.status, "nobody")
        return status

    def public_data(self) -> dict[str, Any]:
        config, settings, catalog, network = self._documents()
        live_status = self.status_document()
        if self.layout.status.exists():
            try:
                stored_status = load_json(self.layout.status)
                for key in ("message", "lastSuccessfulApply"):
                    if key in stored_status:
                        live_status[key] = stored_status[key]
            except BlockyError:
                pass
        zones = {name: zone_info(network, name) for name in ("green", "blue")}
        return {
            "config": redact(config),
            "settings": settings,
            "catalog": catalog,
            "zones": zones,
            "status": live_status,
        }

    def private_data(self) -> dict[str, Any]:
        config, settings, catalog, network = self._documents()
        return {
            "config": config,
            "settings": settings,
            "catalog": catalog,
            "zones": {name: zone_info(network, name) for name in ("green", "blue")},
            "status": self.status_document(),
        }


def main(argv: list[str]) -> int:
    manager = Manager()
    action = argv[1] if len(argv) > 1 else ""
    try:
        if action == "initialize":
            manager.initialize()
        elif action == "apply":
            manager.apply()
        elif action == "validate":
            manager.render_active(validate_binary=True)
            manager.write_status("configuration is valid")
        elif action in {"start", "stop", "restart", "enable", "disable"}:
            manager.service(action)
            manager.write_status(f"service {action} completed")
        elif action == "status":
            print(json.dumps(manager.write_status(), sort_keys=True))
        elif action == "public-data":
            print(json.dumps(manager.public_data(), sort_keys=True))
        elif action == "private-data":
            print(json.dumps(manager.private_data(), sort_keys=True))
        elif action == "enforcement-enabled":
            settings = validate_settings(load_json(manager.layout.settings))
            return 0 if enforcement_active(settings) else 1
        elif action == "firewall" and len(argv) == 3:
            manager.firewall(argv[2])
        elif action == "hook" and len(argv) == 3 and argv[2] in {"install", "uninstall"}:
            update_firewall_hook(manager.layout.firewall_local, argv[2] == "install")
        elif action == "recover":
            manager.recover()
            print("Blocky enforcement disabled; Knot DNS path verified.")
        else:
            raise BlockyError("unsupported or incomplete action")
        return 0
    except Exception as error:  # Last-resort privilege-boundary error handling.
        if not isinstance(error, BlockyError):
            error = BlockyError(f"{type(error).__name__}: {error}")
        try:
            manager.write_status(str(error))
        except Exception:
            pass
        print(f"blocky-manager: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
