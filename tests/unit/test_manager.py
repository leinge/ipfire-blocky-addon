import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "packaging/ipfire/src/blocky/blocky_manager.py"
SPEC = importlib.util.spec_from_file_location("blocky_manager", MODULE_PATH)
manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manager)


def defaults():
    config = json.loads((ROOT / "packaging/ipfire/config/blocky/default-config.json").read_text())
    settings = json.loads((ROOT / "packaging/ipfire/config/blocky/default-settings.json").read_text())
    catalog = json.loads((ROOT / "packaging/ipfire/config/blocky/doh-providers.json").read_text())
    return config, settings, catalog


NETWORK = {
    "GREEN_DEV": "green0",
    "GREEN_ADDRESS": "192.168.10.1",
    "GREEN_NETADDRESS": "192.168.10.0",
    "GREEN_NETMASK": "255.255.255.0",
    "BLUE_DEV": "blue0",
    "BLUE_ADDRESS": "192.168.20.1",
    "BLUE_NETADDRESS": "192.168.20.0",
    "BLUE_NETMASK": "255.255.255.0",
    "RED_DEV": "red0",
    "RED_ADDRESS": "198.51.100.2",
}


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, check=True):
        self.commands.append(command)
        if "-D" in command or "-C" in command or "-L" in command:
            return Result(1)
        return Result(0)


class ActiveGenerationRunner(RecordingRunner):
    def __call__(self, command, check=True):
        self.commands.append(command)
        if "-D" in command:
            return Result(1)
        if "-L" in command:
            return Result(0)
        if "-C" in command:
            target = command[-1]
            return Result(0 if target.endswith("_A") or target in {
                "BLOCKY_PRE", "BLOCKY_IN", "BLOCKY_FWD",
            } else 1)
        return Result(0)


class ApplyRunner(RecordingRunner):
    def __init__(self, fail_firewall=False):
        super().__init__()
        self.fail_firewall = fail_firewall
        self.failed = False

    def __call__(self, command, check=True):
        self.commands.append(command)
        if command[:2] == ["/bin/pidof", "blocky"]:
            return Result(1)
        if "-C" in command or "-L" in command or "-D" in command:
            return Result(1)
        if (
            self.fail_firewall
            and not self.failed
            and "-I" in command
            and "CUSTOMPREROUTING" in command
        ):
            self.failed = True
            raise manager.BlockyError("injected firewall failure")
        return Result(0, stdout="blocky v0.35.0\n" if "version" in command else "")


class FirewallStateRunner:
    def __init__(self, fail_replacement=None):
        self.commands = []
        self.chains = {
            "BLOCKY_PRE": [("-j", "BLOCKY_PRE_A")],
            "BLOCKY_IN": [("-j", "BLOCKY_IN_A")],
            "BLOCKY_FWD": [("-j", "BLOCKY_FWD_A")],
            "BLOCKY_PRE_A": [], "BLOCKY_IN_A": [], "BLOCKY_FWD_A": [],
            "CUSTOMPREROUTING": [("-j", "BLOCKY_PRE")],
            "CUSTOMINPUT": [("-j", "BLOCKY_IN")],
            "CUSTOMFORWARD": [("-j", "BLOCKY_FWD")],
        }
        self.fail_replacement = fail_replacement

    def __call__(self, command, check=True):
        self.commands.append(command)
        if command[0] == "/sbin/ipset":
            return Result(0)
        action_index = next(
            (index for index, item in enumerate(command) if item in {"-L", "-N", "-C", "-A", "-I", "-R", "-F", "-X", "-D"}),
            None,
        )
        if action_index is None:
            return Result(0)
        action = command[action_index]
        chain = command[action_index + 1]
        tail = command[action_index + 2:]
        if action == "-L":
            return Result(0 if chain in self.chains else 1)
        if action == "-N":
            self.chains[chain] = []
        elif action == "-C":
            return Result(0 if tuple(tail) in self.chains.get(chain, []) else 1)
        elif action == "-A":
            self.chains.setdefault(chain, []).append(tuple(tail))
        elif action == "-I":
            position = int(tail[0]) if tail and tail[0].isdigit() else 1
            rule = tuple(tail[1:] if tail and tail[0].isdigit() else tail)
            self.chains.setdefault(chain, []).insert(position - 1, rule)
        elif action == "-R":
            if self.fail_replacement == chain:
                self.fail_replacement = None
                raise manager.BlockyError("injected generation switch failure")
            position = int(tail[0])
            self.chains[chain][position - 1] = tuple(tail[1:])
        elif action == "-F":
            self.chains.setdefault(chain, []).clear()
        elif action == "-X":
            self.chains.pop(chain, None)
        elif action == "-D":
            rule = tuple(tail)
            if rule not in self.chains.get(chain, []):
                return Result(1)
            self.chains[chain].remove(rule)
        return Result(0)


class ParsingTests(unittest.TestCase):
    def test_duplicate_json_key_is_rejected(self):
        with self.assertRaises(manager.DuplicateKeyError):
            manager.load_json_bytes(b'{"a":1,"a":2}')

    def test_duplicate_yaml_key_is_rejected(self):
        with self.assertRaises(manager.BlockyError):
            manager.load_yaml_or_json("a: 1\na: 2\n")

    def test_yaml_import_is_normalized(self):
        value = manager.load_yaml_or_json("upstreams:\n  groups:\n    default: [127.0.0.1]\n")
        self.assertEqual(value["upstreams"]["groups"]["default"], ["127.0.0.1"])

    def test_yaml_aliases_are_rejected(self):
        with self.assertRaisesRegex(manager.BlockyError, "anchors and aliases"):
            manager.load_yaml_or_json("first: &value [one]\nsecond: *value\n")

    def test_load_json_rejects_symlink_and_writable_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text("{}")
            target.chmod(0o600)
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaises(manager.BlockyError):
                manager.load_json(link)
            target.chmod(0o622)
            with self.assertRaises(manager.BlockyError):
                manager.load_json(target)


class RuntimeTests(unittest.TestCase):
    def test_inert_defaults_bind_only_loopback(self):
        config, settings, catalog = defaults()
        runtime, manifest = manager.build_runtime(config, settings, NETWORK, catalog)
        self.assertEqual(runtime["ports"]["dns"], ["127.0.0.1:1053"])
        self.assertFalse(manifest["active"])
        self.assertEqual(manifest["zones"], {})

    def test_green_routing_and_bypass_overlay(self):
        config, settings, catalog = defaults()
        settings["zones"]["green"] = {"selected": True, "route": True, "bypass": True}
        settings["doh"]["providers"] = ["cloudflare"]
        settings["doh"]["exceptDomains"] = ["allowed.example"]
        settings["doh"]["exceptIPv4"] = ["1.1.1.2/32"]
        runtime, manifest = manager.build_runtime(config, settings, NETWORK, catalog)

        self.assertEqual(
            runtime["ports"]["dns"],
            ["127.0.0.1:1053", "192.168.10.1:1053"],
        )
        self.assertIn("cloudflare-dns.com", runtime["blocking"]["denylists"][manager.DOH_GROUP][0])
        self.assertIn("allowed.example", runtime["blocking"]["allowlists"][manager.DOH_GROUP][0])
        self.assertIn(manager.DOH_GROUP, runtime["blocking"]["clientGroupsBlock"]["192.168.10.0/24"])
        self.assertEqual(manifest["zones"]["green"]["interface"], "green0")
        self.assertNotIn("red", manifest["zones"])
        self.assertIn("1.1.1.1/32", manifest["dohIPv4"])
        self.assertEqual(manifest["dohExceptIPv4"], ["1.1.1.2/32"])

    def test_blue_must_exist_when_selected(self):
        config, settings, catalog = defaults()
        settings["zones"]["blue"]["selected"] = True
        network = {key: value for key, value in NETWORK.items() if not key.startswith("BLUE_")}
        with self.assertRaisesRegex(manager.BlockyError, "BLUE"):
            manager.build_runtime(config, settings, network, catalog)

    def test_bypass_requires_route_and_route_requires_selection(self):
        _, settings, _ = defaults()
        settings["zones"]["green"]["route"] = True
        with self.assertRaises(manager.BlockyError):
            manager.validate_settings(settings)
        settings["zones"]["green"]["selected"] = True
        settings["zones"]["green"]["route"] = False
        settings["zones"]["green"]["bypass"] = True
        with self.assertRaises(manager.BlockyError):
            manager.validate_settings(settings)

    def test_reserved_names_are_rejected(self):
        config, _, _ = defaults()
        config["blocking"] = {"denylists": {manager.DOH_GROUP: ["example"]}}
        with self.assertRaisesRegex(manager.BlockyError, "reserved"):
            manager.validate_user_config(config)

    def test_privileged_optional_listener_is_rejected(self):
        config, _, _ = defaults()
        config["ports"] = {"https": "192.168.10.1:443"}
        with self.assertRaisesRegex(manager.BlockyError, "privileged port"):
            manager.validate_user_config(config)

    def test_generated_document_is_json_compatible_yaml(self):
        config, settings, catalog = defaults()
        runtime, _ = manager.build_runtime(config, settings, NETWORK, catalog)
        text = manager.generated_config_bytes(runtime).decode()
        self.assertTrue(text.startswith("# Generated"))
        parsed = manager.load_yaml_or_json(text)
        self.assertEqual(parsed, runtime)


class SecretTests(unittest.TestCase):
    def test_redaction_and_restoration(self):
        active = {
            "redis": {"password": "real", "sentinelPassword": "sentinel"},
            "queryLog": {"target": "postgresql://user:secret@db/blocky"},
        }
        public = manager.redact(active)
        self.assertEqual(public["redis"]["password"], "********")
        self.assertNotIn("secret", public["queryLog"]["target"])
        self.assertEqual(manager.restore_secret_markers(public, active), active)
        blank = {
            "redis": {"password": "", "sentinelPassword": ""},
            "queryLog": {"target": ""},
        }
        self.assertEqual(manager.restore_secret_markers(blank, active), active)
        cleared = {"redis": {"password": manager.CLEAR_SECRET_MARKER}}
        self.assertEqual(manager.restore_secret_markers(cleared, active)["redis"]["password"], "")

    def test_validation_errors_are_sanitized(self):
        document = {
            "redis": {"password": "redis-secret"},
            "queryLog": {"target": "postgresql://user:db-secret@example.invalid/blocky"},
        }
        message = "redis-secret and db-secret are invalid"
        sanitized = manager.sanitize_error(message, document)
        self.assertNotIn("redis-secret", sanitized)
        self.assertNotIn("db-secret", sanitized)


class ApplyTransactionTests(unittest.TestCase):
    def prepare_layout(self, root):
        layout = manager.Layout(root)
        config, settings, catalog = defaults()
        files = {
            layout.canonical_config: config,
            layout.settings: settings,
            layout.provider_catalog: catalog,
            layout.enforcement_manifest: {"schemaVersion": 1, "active": False, "zones": {}},
        }
        for path, value in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value) + "\n")
            path.chmod(0o600)
        layout.runtime_config.parent.mkdir(parents=True, exist_ok=True)
        layout.runtime_config.write_text("old runtime\n")
        layout.runtime_config.chmod(0o600)
        layout.network_settings.parent.mkdir(parents=True, exist_ok=True)
        layout.network_settings.write_text("\n".join(f"{key}={value}" for key, value in NETWORK.items()))
        layout.network_settings.chmod(0o600)
        return layout, config, settings

    @staticmethod
    def account(name):
        if name == "nobody":
            return SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_name=name)
        raise KeyError(name)

    def apply_candidate(self, layout, config, settings, runner):
        layout.pending.parent.mkdir(parents=True, exist_ok=True)
        layout.pending.write_text(json.dumps({"config": config, "settings": settings}))
        layout.pending.chmod(0o600)
        with (
            mock.patch.object(manager.pwd, "getpwnam", side_effect=self.account),
            mock.patch.object(manager, "chown_group"),
        ):
            manager.Manager(layout, runner).apply()

    def test_first_enforcement_starts_service_before_installing_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            layout, config, settings = self.prepare_layout(temporary)
            settings["zones"]["green"] = {"selected": True, "route": True, "bypass": False}
            runner = ApplyRunner()

            self.apply_candidate(layout, config, settings, runner)

            commands = [" ".join(command) for command in runner.commands]
            start = commands.index("/etc/rc.d/init.d/blocky start")
            first_jump = next(index for index, item in enumerate(commands) if " -I CUSTOM" in item)
            self.assertLess(start, first_jump)
            self.assertTrue(json.loads(layout.enforcement_manifest.read_text())["active"])
            self.assertEqual(
                json.loads((layout.last_known_good / "settings.json").read_text())["zones"]["green"]["route"],
                False,
            )
            self.assertFalse(layout.pending.exists())

    def test_failed_first_enforcement_restores_files_and_stops_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            layout, config, settings = self.prepare_layout(temporary)
            old_documents = {
                path: path.read_bytes()
                for path in (
                    layout.canonical_config,
                    layout.settings,
                    layout.runtime_config,
                    layout.enforcement_manifest,
                )
            }
            settings["zones"]["green"] = {"selected": True, "route": True, "bypass": False}
            runner = ApplyRunner(fail_firewall=True)

            with self.assertRaisesRegex(manager.BlockyError, "injected firewall failure"):
                self.apply_candidate(layout, config, settings, runner)

            for path, content in old_documents.items():
                self.assertEqual(path.read_bytes(), content)
            commands = [" ".join(command) for command in runner.commands]
            self.assertIn("/etc/rc.d/init.d/blocky stop", commands)
            self.assertFalse(layout.pending.exists())

    def test_rejected_candidate_is_removed_before_any_state_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            layout, config, settings = self.prepare_layout(temporary)
            original = layout.canonical_config.read_bytes()
            config.pop("upstreams")

            with self.assertRaisesRegex(manager.BlockyError, "upstreams"):
                self.apply_candidate(layout, config, settings, ApplyRunner())

            self.assertEqual(layout.canonical_config.read_bytes(), original)
            self.assertFalse(layout.pending.exists())

    def test_manager_lock_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            layout = manager.Layout(temporary)
            layout.lock.parent.mkdir(parents=True)
            target = Path(temporary) / "target"
            target.write_text("untouched")
            layout.lock.symlink_to(target)
            with self.assertRaisesRegex(manager.BlockyError, "manager lock"):
                manager.Manager(layout, ApplyRunner())._locked()
            self.assertEqual(target.read_text(), "untouched")


class ServiceTests(unittest.TestCase):
    def test_boot_links_use_correct_relative_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            layout = manager.Layout(temporary)
            _, settings, _ = defaults()
            layout.settings.parent.mkdir(parents=True, exist_ok=True)
            layout.settings.write_text(json.dumps(settings))
            layout.settings.chmod(0o600)
            disabled = layout.path("/etc/rc.d/rc3.d/off/S50blocky")
            disabled.parent.mkdir(parents=True)
            disabled.symlink_to("../../init.d/blocky")
            service = manager.Manager(layout, RecordingRunner())

            service.service("enable")
            enabled = layout.path("/etc/rc.d/rc3.d/S50blocky")
            self.assertEqual(os.readlink(enabled), "../init.d/blocky")
            self.assertFalse(disabled.exists())

            service.service("disable")
            self.assertEqual(os.readlink(disabled), "../../init.d/blocky")
            self.assertFalse(enabled.exists())


class FirewallTests(unittest.TestCase):
    def test_reconcile_uses_only_selected_zone_and_expected_ports(self):
        config, settings, catalog = defaults()
        settings["zones"]["green"] = {"selected": True, "route": True, "bypass": True}
        settings["doh"]["providers"] = ["quad9"]
        _, manifest = manager.build_runtime(config, settings, NETWORK, catalog)
        runner = RecordingRunner()
        manager.reconcile_firewall(manifest, runner)
        rendered = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("-i green0 -p udp --dport 53 -j REDIRECT --to-ports 1053" in item for item in rendered))
        self.assertTrue(any("-i green0 -p tcp --dport 853 -j REJECT" in item for item in rendered))
        self.assertTrue(any("--dport 443" in item and "blocky_doh_v4_a" in item for item in rendered))
        self.assertFalse(any("red0" in item for item in rendered))
        self.assertFalse(any("blue0" in item for item in rendered))

    def test_active_rules_stay_installed_until_replacement_is_complete(self):
        config, settings, catalog = defaults()
        settings["zones"]["green"] = {"selected": True, "route": True, "bypass": True}
        _, manifest = manager.build_runtime(config, settings, NETWORK, catalog)
        runner = ActiveGenerationRunner()

        manager.reconcile_firewall(manifest, runner)

        rendered = [" ".join(command) for command in runner.commands]
        replacement_positions = [
            index for index, command in enumerate(rendered)
            if " -R BLOCKY_" in command and command.endswith("_B")
        ]
        old_cleanup_positions = [
            index for index, command in enumerate(rendered)
            if " -F BLOCKY_" in command and command.endswith("_A")
        ]
        new_rule_positions = [
            index for index, command in enumerate(rendered)
            if " -A BLOCKY_" in command and "_B " in command
        ]
        self.assertEqual(len(replacement_positions), 3)
        self.assertTrue(new_rule_positions)
        self.assertGreater(min(replacement_positions), max(new_rule_positions))
        self.assertTrue(old_cleanup_positions)
        self.assertGreater(min(old_cleanup_positions), max(replacement_positions))

    def test_reconcile_recovers_from_a_partial_generation_switch(self):
        config, settings, catalog = defaults()
        settings["zones"]["green"] = {"selected": True, "route": True, "bypass": True}
        _, manifest = manager.build_runtime(config, settings, NETWORK, catalog)
        runner = FirewallStateRunner(fail_replacement="BLOCKY_IN")

        with self.assertRaisesRegex(manager.BlockyError, "generation switch"):
            manager.reconcile_firewall(manifest, runner)
        manager.reconcile_firewall(manifest, runner)

        for anchor in ("BLOCKY_PRE", "BLOCKY_IN", "BLOCKY_FWD"):
            self.assertEqual(len(runner.chains[anchor]), 1)
            self.assertRegex(runner.chains[anchor][0][-1], rf"^{anchor}_[AB]$")

    def test_inert_manifest_only_removes_owned_resources(self):
        runner = RecordingRunner()
        manager.reconcile_firewall({"active": False}, runner)
        rendered = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("BLOCKY_PRE" in item for item in rendered))
        self.assertFalse(any("green0" in item for item in rendered))
        forward = next(index for index, item in enumerate(rendered) if "-D CUSTOMFORWARD" in item)
        routing = next(index for index, item in enumerate(rendered) if "-D CUSTOMPREROUTING" in item)
        self.assertLess(forward, routing)


class HookTests(unittest.TestCase):
    def test_hook_round_trip_preserves_user_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "firewall.local"
            original = "#!/bin/sh\n# user rule\necho keep-me\n"
            path.write_text(original)
            path.chmod(0o750)
            manager.update_firewall_hook(path, True)
            installed = path.read_text()
            self.assertEqual(installed.count(manager.HOOK_BEGIN), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o750)
            manager.update_firewall_hook(path, True)
            self.assertEqual(path.read_text().count(manager.HOOK_BEGIN), 1)
            manager.update_firewall_hook(path, False)
            self.assertEqual(path.read_text(), original)

    def test_ambiguous_hook_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "firewall.local"
            path.write_text(f"{manager.HOOK_BEGIN}\n")
            with self.assertRaisesRegex(manager.BlockyError, "ambiguous"):
                manager.update_firewall_hook(path, True)

    def test_hook_preserves_missing_trailing_newline(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "firewall.local"
            original = "#!/bin/sh\necho no-final-newline"
            path.write_text(original)
            manager.update_firewall_hook(path, True)
            self.assertIn(manager.HOOK_BEGIN_JOINED, path.read_text())
            manager.update_firewall_hook(path, False)
            self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
