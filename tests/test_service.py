import tempfile
import unittest

from route_hints_service.app import PROTOCOL, Store, now_ms


class StoreTests(unittest.TestCase):
    def test_expiring_band_scoped_evidence(self) -> None:
        with tempfile.NamedTemporaryFile() as handle:
            store = Store(handle.name)
            observed = now_ms()
            accepted = store.put_batch(
                "OH3SPN",
                [
                    {
                        "kind": "heard",
                        "source": "F4LPU",
                        "band": "20m",
                        "observed_at_ms": observed,
                        "snr": -14,
                    },
                    {
                        "kind": "observed_traffic",
                        "source": "F4LPU",
                        "destination": "HB9TLY",
                        "band": "20m",
                        "observed_at_ms": observed,
                    },
                ],
            )
            self.assertEqual(accepted, 2)
            self.assertEqual(len(store.query("HB9TLY", "20m", 10)), 1)
            self.assertEqual(len(store.query("HB9TLY", "40m", 10)), 0)
            self.assertEqual(store.graph("20m", 10)["protocol"], PROTOCOL)

    def test_duplicate_claim_is_ignored(self) -> None:
        with tempfile.NamedTemporaryFile() as handle:
            store = Store(handle.name)
            claim = {
                "kind": "heard",
                "source": "F4LPU",
                "band": "20m",
                "observed_at_ms": now_ms(),
            }
            self.assertEqual(store.put_batch("OH3SPN", [claim]), 1)
            self.assertEqual(store.put_batch("OH3SPN", [claim]), 0)

