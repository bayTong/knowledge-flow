from __future__ import annotations

import unittest
from uuid import UUID

from knowledgeflow_capture.ids import (
    IdKind,
    extract_unix_ts_ms,
    generate_typed_id,
    generate_uuid7,
    validate_typed_id,
)


class UUIDv7Test(unittest.TestCase):
    def test_rfc_vector_and_version_variant_bits(self) -> None:
        # RFC 9562 Appendix A.6 values: rand_a=0xcc3, rand_b=0x18c4dc0c0c07398f.
        random_74 = (0xCC3 << 62) | 0x18C4DC0C0C07398F
        value = generate_uuid7(
            unix_ts_ms=0x017F22E279B0,
            random_bytes=random_74.to_bytes(10, "big"),
        )

        self.assertEqual(str(value), "017f22e2-79b0-7cc3-98c4-dc0c0c07398f")
        self.assertEqual(value.version, 7)
        self.assertEqual(value.variant, "specified in RFC 4122")
        self.assertEqual(extract_unix_ts_ms(value), 0x017F22E279B0)

    def test_typed_ids_are_lowercase_canonical_uuid_text(self) -> None:
        capture_id = generate_typed_id(
            IdKind.CAPTURE,
            unix_ts_ms=1_789_000_000_123,
            random_bytes=bytes.fromhex("000123456789abcdef01"),
        )

        self.assertTrue(capture_id.startswith("cap_"))
        self.assertEqual(capture_id, capture_id.lower())
        parsed = validate_typed_id(capture_id, IdKind.CAPTURE)
        self.assertIsInstance(parsed, UUID)
        self.assertEqual(parsed.version, 7)

    def test_same_millisecond_requires_uniqueness_not_monotonicity(self) -> None:
        timestamp = 1_789_000_000_123
        values = {generate_uuid7(unix_ts_ms=timestamp) for _ in range(512)}

        self.assertEqual(len(values), 512)
        self.assertTrue(all(extract_unix_ts_ms(value) == timestamp for value in values))

    def test_increasing_and_rollback_timestamps_use_observed_clock(self) -> None:
        later = generate_uuid7(
            unix_ts_ms=2_000,
            random_bytes=(1).to_bytes(10, "big"),
        )
        rollback = generate_uuid7(
            unix_ts_ms=1_000,
            random_bytes=(2).to_bytes(10, "big"),
        )

        self.assertEqual(extract_unix_ts_ms(later), 2_000)
        self.assertEqual(extract_unix_ts_ms(rollback), 1_000)
        self.assertNotEqual(later, rollback)
        self.assertLess(rollback, later)

    def test_invalid_timestamp_random_source_and_prefix_are_rejected(self) -> None:
        for timestamp in (-1, 1 << 48, True):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                generate_uuid7(unix_ts_ms=timestamp)

        with self.assertRaises(ValueError):
            generate_uuid7(unix_ts_ms=0, random_bytes=b"short")
        with self.assertRaises(ValueError):
            validate_typed_id(
                "evt_017f22e2-79b0-7cc3-98c4-dc0c0c07398f",
                IdKind.CAPTURE,
            )


if __name__ == "__main__":
    unittest.main()
