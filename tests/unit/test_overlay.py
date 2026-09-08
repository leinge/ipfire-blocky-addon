import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "packaging/ipfire"


class OverlayTests(unittest.TestCase):
    def test_ipfire_baseline_is_a_full_commit(self):
        baseline = (OVERLAY / "IPFIRE_BASELINE").read_text().strip()
        self.assertEqual(len(baseline), 40)
        int(baseline, 16)

    def test_vendored_upstream_assets_match_recorded_hashes(self):
        expected = {
            "config.schema.json": "2d46c12a3b2850c3a906093339f2609c5ddbb7eedaaa21762eff673a1a2537bf",
            "LICENSE.blocky": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        }
        for name, digest in expected.items():
            content = (OVERLAY / "config/blocky" / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), digest)

    def test_schema_top_level_coverage(self):
        schema = json.loads((OVERLAY / "config/blocky/config.schema.json").read_text())
        descriptor = json.loads((OVERLAY / "config/blocky/ui-descriptor.json").read_text())
        covered = {name for section in descriptor["sections"] for name in section["properties"]}
        supported = {
            name for name, value in schema["properties"].items()
            if not value.get("deprecated", False)
        }
        self.assertEqual(supported, covered)

    def test_schema_uses_only_editor_supported_constructs(self):
        schema = json.loads((OVERLAY / "config/blocky/config.schema.json").read_text())
        unsupported = []

        def visit(value, path="$"):
            if isinstance(value, dict):
                for keyword in ("$ref", "oneOf", "allOf", "patternProperties"):
                    if keyword in value:
                        unsupported.append(f"{path}:{keyword}")
                schema_type = value.get("type")
                if isinstance(schema_type, list) or (
                    isinstance(schema_type, str) and schema_type not in {
                        "object", "array", "boolean", "integer", "number", "string",
                    }
                ):
                    unsupported.append(f"{path}:type={schema_type}")
                if isinstance(value.get("items"), list):
                    unsupported.append(f"{path}:tuple-items")
                for key, child in value.items():
                    visit(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")

        visit(schema)
        self.assertEqual(unsupported, [])

    def test_catalog_has_required_reviewed_providers(self):
        catalog = json.loads((OVERLAY / "config/blocky/doh-providers.json").read_text())
        providers = {item["id"]: item for item in catalog["providers"]}
        self.assertTrue({"cloudflare", "google", "quad9", "adguard", "nextdns"} <= set(providers))
        for provider in providers.values():
            self.assertTrue(provider["source"].startswith("https://"))
            self.assertTrue(provider["domains"] or provider["ipv4"])

    def test_rootfile_covers_runtime_files(self):
        rootfile = set((OVERLAY / "config/rootfiles/packages/blocky").read_text().splitlines())
        required = {
            "etc/blocky/config.yml",
            "etc/rc.d/init.d/blocky",
            "srv/web/ipfire/cgi-bin/blocky.cgi",
            "srv/web/ipfire/html/include/blocky.js",
            "usr/bin/blocky",
            "usr/local/bin/blockyctrl",
            "usr/sbin/blocky-recovery",
            "usr/share/blocky/config.schema.json",
            "var/ipfire/menu.d/EX-blocky.menu",
        }
        self.assertTrue(required <= rootfile)

    def test_initial_defaults_are_inert(self):
        settings = json.loads((OVERLAY / "config/blocky/default-settings.json").read_text())
        self.assertTrue(all(not zone["selected"] and not zone["route"] and not zone["bypass"] for zone in settings["zones"].values()))

    def test_controller_uses_fixed_exec_and_allowlist(self):
        source = (OVERLAY / "src/misc-progs/blockyctrl.c").read_text()
        expected = {
            "apply", "validate", "start", "stop", "restart", "enable", "disable",
            "status", "public-data", "private-data",
        }
        actions = {
            item.split('"')[1]
            for item in source.splitlines()
            if 'strcmp(argv[1], "' in item
        }
        self.assertEqual(actions, expected)
        self.assertIn('run("/usr/lib/blocky/blocky-manager", args)', source)
        self.assertNotIn("safe_system(", source)


if __name__ == "__main__":
    unittest.main()
