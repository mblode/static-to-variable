"""The pytest half of the cross-language schema agreement corpus.

Each fixture under schemas/fixtures/ is annotated with the verdict expected
from the JSON-schema validator (checked by the CLI's vitest suite) and from
this package's load_config. Running both halves against the same files pins
what "a valid config" means across the TypeScript and Python validators.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from variable_gen.config import ConfigError, load_config  # noqa: E402

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "fixtures"


def iter_fixtures():
    for kind in ("valid", "invalid"):
        for path in sorted((FIXTURES_ROOT / kind).glob("*.json")):
            payload = json.loads(path.read_text())
            expect = payload.pop("_expect")
            yield f"{kind}/{path.name}", payload, expect


class SchemaFixtureAgreementTests(unittest.TestCase):
    def test_fixture_corpus_exists(self):
        self.assertGreaterEqual(len(list(iter_fixtures())), 8)

    def test_load_config_matches_expectations(self):
        for name, payload, expect in iter_fixtures():
            with self.subTest(fixture=name):
                with tempfile.TemporaryDirectory() as tmp:
                    config_path = Path(tmp) / "stv.config.json"
                    config_path.write_text(json.dumps(payload))
                    if expect["python"]:
                        config = load_config(config_path)
                        self.assertEqual(config.version, 3)
                    else:
                        with self.assertRaises(ConfigError):
                            load_config(config_path)


if __name__ == "__main__":
    unittest.main()
