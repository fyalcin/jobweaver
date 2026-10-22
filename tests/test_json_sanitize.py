
import unittest

import server


class JsonSanitizeTest(unittest.TestCase):
    """NaN/Inf floats must become None — browsers' JSON.parse rejects bare NaN,
    which silently broke the unprocessed-jobs queue before the fix."""

    def test_nan_and_inf_become_none(self):
        res = server._sanitize_for_json({"a": float("nan"), "b": [float("inf"), 1.5, "x"], "c": {"d": float("-inf")}})
        self.assertIsNone(res["a"])
        self.assertIsNone(res["b"][0])
        self.assertEqual(res["b"][1], 1.5)
        self.assertEqual(res["b"][2], "x")
        self.assertIsNone(res["c"]["d"])

    def test_non_float_values_untouched(self):
        src = {"s": "NaN text", "i": 3, "n": None, "l": [{"k": True}]}
        self.assertEqual(server._sanitize_for_json(src), src)

    def test_detects_nan(self):
        self.assertIsNone(server._sanitize_for_json(float("nan")))
        self.assertEqual(server._sanitize_for_json(float("1.5")), 1.5)


if __name__ == "__main__":
    unittest.main()
