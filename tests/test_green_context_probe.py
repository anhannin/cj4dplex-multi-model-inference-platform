import unittest
from diagnostics.green_context.validate import validate_native


class GreenProbeTests(unittest.TestCase):
    def valid(self):
        return {
            "total_sms": 48,
            "parts": [
                {"actual_sms": 16, "smids": list(range(16))},
                {"actual_sms": 32, "smids": list(range(16, 48))},
            ],
        }

    def test_disjoint_physical_smid_samples(self):
        self.assertTrue(validate_native(self.valid())["observed_disjoint"])

    def test_overlapping_ids_rejected_not_called_isolation(self):
        r = self.valid()
        r["parts"][1]["smids"] = [0, 16]
        with self.assertRaises(AssertionError):
            validate_native(r)

    def test_sampling_does_not_have_to_hit_every_assigned_sm(self):
        r = self.valid()
        r["parts"][0]["smids"] = [0, 1]
        self.assertEqual(validate_native(r)["observed_sm_counts"], [2, 32])

    def test_too_many_sms_cannot_be_claimed(self):
        r = self.valid()
        r["parts"][0]["actual_sms"] = 8
        with self.assertRaises(AssertionError):
            validate_native(r)


class GreenTraceValidationTests(unittest.TestCase):
    def database(self):
        import sqlite3

        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE NVTX_EVENTS(text TEXT,start INTEGER,end INTEGER)")
        c.execute(
            "CREATE TABLE CUPTI_ACTIVITY_KIND_KERNEL(start INTEGER,end INTEGER,greenContextId INTEGER)"
        )
        c.execute("INSERT INTO NVTX_EVENTS VALUES('model',10,100)")
        c.execute("INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES(1,5,0)")
        c.execute("INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES(20,90,2)")
        return c

    def test_nvtx_label_alone_does_not_prove_green_execution(self):
        from diagnostics.green_context.verify_nsys import verify_window

        c = self.database()
        self.assertEqual(
            verify_window(c, "model")["kernel_groups"],
            [{"greenContextId": 2, "kernels": 1}],
        )
        c.execute("INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES(30,40,0)")
        with self.assertRaises(AssertionError):
            verify_window(c, "model")

    def test_incomplete_window_is_not_silently_accepted(self):
        from diagnostics.green_context.verify_nsys import verify_window

        c = self.database()
        c.execute("INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES(90,110,2)")
        with self.assertRaises(AssertionError):
            verify_window(c, "model")
