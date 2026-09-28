"""Small fail-closed tests for supplemental map provenance and binary structure."""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from build_rich_context_manifest import build, inspect, verify


def rich_blob() -> bytes:
    # One named point (kind 9) using the production THRICH01 v3 layout.
    return (b"THRICH01" + struct.pack(">i4d2i", 3, 50.7472, 25.3254, 111132.0,
                                      71000.0, 1, 1) + struct.pack(">BHHii", 9, 1, 4, 0, 0)
            + b"Test")


class VisualBundleTest(unittest.TestCase):
    def test_rich_manifest_binds_binary_map_and_osm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, source_map, osm, manifest = [root / name for name in
                                                 ("rich_context.bin", "lutsk_area.map", "area.osm", "rich.json")]
            binary.write_bytes(rich_blob())
            source_map.write_bytes(b"map")
            osm.write_bytes(b"osm")
            build(binary, source_map, osm, manifest)
            self.assertEqual(1, verify(binary, source_map, osm, manifest)["feature_count"])
            source_map.write_bytes(b"different map")
            with self.assertRaisesRegex(ValueError, "source_map_sha256"):
                verify(binary, source_map, osm, manifest)

    def test_corrupt_rich_geometry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "rich_context.bin"
            binary.write_bytes(rich_blob()[:-1])
            with self.assertRaisesRegex(ValueError, "Truncated"):
                inspect(binary)


if __name__ == "__main__":
    unittest.main()
