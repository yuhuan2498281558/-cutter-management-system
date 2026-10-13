"""No database or model is needed to test structural evidence preservation."""

import copy
import json
import unittest

from application.ai_assistant.context_compaction import (
    COLUMNAR_FORMAT, COLUMNAR_INSTRUCTIONS, compact_tool_content, unpack_columnar,
)


def count_tokens(text):
    return len(text) // 4


def trend_rows(count=120):
    return [
        {
            "start_ring": index + 1,
            "end_ring": index + 1,
            "normal_count": 5,
            "abnormal_count": 5,
            "unknown_count": 90,
            "abnormal_rate": 50.0,
            "valid_sample_count": 10,
            "average_wear_mm": None if index % 2 else 0.0,
            "tool_type": "滚刀",
            "is_complete": index % 2 == 0,
        }
        for index in range(count)
    ]


class ContextCompactionTests(unittest.TestCase):
    def compact(self, data, **kwargs):
        return compact_tool_content(json.dumps(data, ensure_ascii=False), count_tokens, **kwargs)

    def test_statistical_evidence_roundtrip_and_savings(self):
        original = {
            "project_id": 17, "ring_range": [1, 120], "unit": "mm",
            "denominator_rule": "正常+异常，未知不参与", "data": trend_rows(),
        }
        encoded = self.compact(original)
        self.assertEqual(unpack_columnar(encoded), original)
        self.assertLess(count_tokens(encoded), count_tokens(json.dumps(original)) * 0.6)
        restored = unpack_columnar(encoded)["data"]
        self.assertIsNone(restored[1]["average_wear_mm"])
        self.assertEqual(restored[0]["average_wear_mm"], 0.0)
        self.assertEqual(restored[0]["unknown_count"], 90)
        self.assertEqual(restored[0]["abnormal_rate"], 50.0)

    def test_root_array(self):
        original = trend_rows()
        encoded = self.compact(original)
        self.assertEqual(json.loads(encoded)["table_paths"], [[]])
        self.assertEqual(unpack_columnar(encoded), original)

    def test_nested_arrays_and_path_keys_are_unambiguous(self):
        original = {"0": [{"a/b~[0]": trend_rows()}], "": {"0": trend_rows()}}
        encoded = self.compact(original)
        self.assertEqual(
            json.loads(encoded)["table_paths"], [["0", 0, "a/b~[0]"], ["", "0"]]
        )
        self.assertEqual(unpack_columnar(encoded), original)

    def test_original_column_row_objects_are_not_decoded(self):
        original = {"data": trend_rows(), "schema": {"columns": ["x"], "rows": [[1]]}}
        self.assertEqual(unpack_columnar(self.compact(original)), original)

    def test_permuted_dictionary_keys_preserve_values(self):
        original = trend_rows()
        original[2] = dict(reversed(list(original[2].items())))
        self.assertEqual(unpack_columnar(self.compact(original)), original)

    def test_heterogeneous_rows_remain_original(self):
        original = trend_rows()
        original[1]["extra"] = "different schema"
        raw = json.dumps(original)
        self.assertEqual(compact_tool_content(raw, count_tokens), raw)

    def test_nested_values_not_mistaken_for_scalar_table(self):
        original = [{"details": [1, 2], "long_name": index} for index in range(100)]
        raw = json.dumps(original)
        self.assertEqual(compact_tool_content(raw, count_tokens), raw)

    def test_small_result_and_high_threshold_preserve_exact_input(self):
        for original, threshold in [(trend_rows(3), 1000), (trend_rows(), 100000)]:
            raw = json.dumps(original, indent=2)
            self.assertEqual(compact_tool_content(raw, count_tokens, threshold), raw)

    def test_instruction_overhead_can_make_compaction_unprofitable(self):
        raw = json.dumps([{"a": 1, "b": 2} for _ in range(3)], indent=40)
        self.assertEqual(compact_tool_content(raw, count_tokens, 0), raw)

    def test_invalid_json_scalars_duplicates_nonfinite_are_unchanged(self):
        for raw in ["not json", '"a scalar"', "42", "null", '{"a": 1, "a": 2}',
                    '[{"x": NaN}]', '[{"x": Infinity}]', '[{"x": 1e999}]']:
            with self.subTest(raw=raw):
                self.assertEqual(compact_tool_content(raw, count_tokens, 0), raw)

    def test_errors_and_wrapped_errors_are_unchanged(self):
        for marker in [{"error": "查询失败"}, {"success": False}, {"status": "error"},
                       {"result": {"error": "invalid ring"}}]:
            raw = json.dumps({**marker, "partial": trend_rows()})
            self.assertEqual(compact_tool_content(raw, count_tokens), raw)

    def test_high_precision_and_underflow_numbers_preserve_original_text(self):
        for number in ["1.000000000000000001", "1e-999", "1e999"]:
            raw = json.dumps({"data": trend_rows(), "precise": "PLACEHOLDER"})
            raw = raw.replace('"PLACEHOLDER"', number)
            self.assertEqual(compact_tool_content(raw, count_tokens), raw)

    def test_already_packed_is_idempotent(self):
        encoded = self.compact(trend_rows())
        self.assertEqual(compact_tool_content(encoded, count_tokens, 0), encoded)

    def test_marker_collision_is_preserved(self):
        raw = json.dumps({"format": COLUMNAR_FORMAT, "data": trend_rows()})
        self.assertEqual(compact_tool_content(raw, count_tokens), raw)
        with self.assertRaises(ValueError):
            unpack_columnar(raw)

    def test_unpack_does_not_mutate_envelope(self):
        envelope = json.loads(self.compact({"data": trend_rows()}))
        original = copy.deepcopy(envelope)
        unpack_columnar(envelope)
        self.assertEqual(envelope, original)

    def test_unpack_rejects_bad_paths_and_table_shapes(self):
        good = json.loads(self.compact({"data": trend_rows()}))
        variants = []
        for paths in [[["data"], ["data"]], [["missing"]], [[True]], [[-1]],
                      [["data"], ["data", 0]], [["data", 0], ["data"]], "data"]:
            variant = copy.deepcopy(good)
            variant["table_paths"] = paths
            variants.append(variant)
        for table in [{"columns": ["x", "x"], "rows": [[1, 2]]},
                      {"columns": ["x"], "rows": [[1, 2]]},
                      {"columns": ["x"], "rows": [[{}]]},
                      {"columns": "x", "rows": [[1]]}]:
            variant = copy.deepcopy(good)
            variant["data"]["data"] = table
            variants.append(variant)
        for variant in variants:
            with self.subTest(variant=variant["table_paths"]):
                with self.assertRaises(ValueError):
                    unpack_columnar(variant)

    def test_format_instructions_present_and_counted(self):
        encoded = self.compact(trend_rows())
        self.assertEqual(json.loads(encoded)["instructions"], COLUMNAR_INSTRUCTIONS)
        # A tokenizer can assign a high cost to the explanatory text.
        def costly_instructions(text):
            return count_tokens(text) + (100000 if COLUMNAR_FORMAT in text else 0)
        raw = json.dumps(trend_rows())
        self.assertEqual(compact_tool_content(raw, costly_instructions), raw)

    def test_scalar_types_and_large_identifiers_are_preserved(self):
        original = [{"identifier": 2 ** 70 + index, "negative": -1.25,
                     "boolean": False, "empty_string": "", "null_value": None,
                     "quoted": 'a"b\\c\n中文'} for index in range(120)]
        restored = unpack_columnar(self.compact(original))
        self.assertEqual(restored, original)
        self.assertIs(type(restored[0]["identifier"]), int)
        self.assertIs(type(restored[0]["boolean"]), bool)


if __name__ == "__main__":
    unittest.main()
