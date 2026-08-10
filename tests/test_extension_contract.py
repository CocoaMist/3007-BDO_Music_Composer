from __future__ import annotations

import unittest

from bdo_common.extension_contract import (
    ExtensionContractError,
    ExtensionRequirement,
    HostExtensionContract,
    negotiate_extension,
)
from bdo_common.extension_protocol import (
    ExtensionEnvelope,
    ExtensionProtocolError,
    decode_extension_envelope,
    encode_extension_envelope,
)


class ExtensionContractTests(unittest.TestCase):
    def test_version_capability_and_transport_are_negotiated_fail_closed(self) -> None:
        host = HostExtensionContract(
            "bdo.test",
            2,
            frozenset({"read.notes", "write.preview"}),
            frozenset({"ndjson-stdio"}),
        )
        result = negotiate_extension(
            host,
            ExtensionRequirement(
                "bdo.test",
                1,
                2,
                frozenset({"read.notes"}),
                frozenset({"write.preview", "future.optional"}),
            ),
        )
        self.assertEqual(result.capabilities, frozenset({"read.notes", "write.preview"}))
        with self.assertRaises(ExtensionContractError):
            negotiate_extension(
                host,
                ExtensionRequirement("bdo.test", 3, 4),
            )

    def test_ndjson_protocol_is_bounded_and_exact_field(self) -> None:
        source = ExtensionEnvelope("request-1", "analyse", {"value": 3})
        self.assertEqual(decode_extension_envelope(encode_extension_envelope(source)), source)
        with self.assertRaises(ExtensionProtocolError):
            decode_extension_envelope(b'{"protocol_version":1}\n')


if __name__ == "__main__":
    unittest.main()
