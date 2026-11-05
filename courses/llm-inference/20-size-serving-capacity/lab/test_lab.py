import unittest
from lab import CapacityEvidence, plan


class CapacityTests(unittest.TestCase):
    def evidence(self, accepted=True, reference="run.json"):
        return CapacityEvidence(2, 3, "same workload", accepted, reference)

    def test_peak_rate_and_reserve_are_counted(self):
        result = plan(86400, 3, self.evidence(), 1)
        self.assertEqual(result["active_replicas"], 2)
        self.assertEqual(result["total_replicas"], 3)
        self.assertEqual(result["peak_hour_cost"], 9)

    def test_unaccepted_capacity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "accepted benchmark"):
            plan(86400, 3, self.evidence(False))

    def test_missing_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            plan(86400, 3, self.evidence(reference=""))

    def test_higher_peak_requires_more_capacity(self):
        self.assertGreater(
            plan(86400, 5, self.evidence())["active_replicas"],
            plan(86400, 2, self.evidence())["active_replicas"],
        )


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('CapacityEvidence(0,1,"test",True,"record").validate()', 'rate or price'), ('plan(0,1,CapacityEvidence(1,1,"test",True,"record"))', 'traffic or reserve')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
