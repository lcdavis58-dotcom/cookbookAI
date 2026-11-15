"""
Tests for scale_utils/pan_scaling.py: reading a pan's shape and size
from text, and the scale factor between two pans. Pure functions, no
database or model.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import math
import unittest

from scale_utils.pan_scaling import (describe_pan, detect_pan_request, extract_all_pan_shapes, extract_pan_shape,
                                     normalize_connectors, pan_area, pan_scale_factor,
                                     pan_scale_factor_from_question)


def rect(length, width):
    return {"shape": "rectangle", "length": length, "width": width}


def circle(diameter):
    return {"shape": "circle", "diameter": diameter}


class NormalizeConnectorsTest(unittest.TestCase):
    def test_by_and_times_sign(self):
        self.assertEqual(normalize_connectors("a 9-By-13-inch pan"), "a 9 by 13-inch pan")
        self.assertEqual(normalize_connectors("9 × 13"), "9 x 13")


class ExtractPanShapeTest(unittest.TestCase):
    def test_rectangles(self):
        for text in ("a 9x13 pan", "a 9-by-13-inch pan", "a 9 × 13 in. dish", "9 by 13 inches"):
            with self.subTest(text=text):
                self.assertEqual(extract_pan_shape(text), rect(9.0, 13.0))

    def test_inches_preferred_over_cm(self):
        self.assertEqual(extract_pan_shape("23 by 33 cm / 9 by 13 inches"), rect(9.0, 13.0))
        self.assertEqual(extract_pan_shape("MAKES ONE 9-INCH / 23-CM TART"), circle(9.0))

    def test_cm_only_is_converted(self):
        pan = extract_pan_shape("a 23 cm round")
        self.assertEqual(pan["shape"], "circle")
        self.assertAlmostEqual(pan["diameter"], 23 / 2.54)
        pan = extract_pan_shape("a 20 by 30 cm tray")
        self.assertAlmostEqual(pan["length"], 20 / 2.54)
        self.assertAlmostEqual(pan["width"], 30 / 2.54)

    def test_square_reads_as_a_rectangle(self):
        self.assertEqual(extract_pan_shape("a 9-inch square pan"), rect(9.0, 9.0))

    def test_single_size_is_round(self):
        self.assertEqual(extract_pan_shape("a 9-inch pie plate"), circle(9.0))

    def test_fraction(self):
        self.assertEqual(extract_pan_shape("an 8½-inch pan"), circle(8.5))

    def test_thickness_next_to_the_pan_isnt_read(self):
        self.assertEqual(extract_pan_shape("10 by 14 inches and just over ¼ inch thick"), rect(10.0, 14.0))

    def test_nothing(self):
        self.assertIsNone(extract_pan_shape("Serves 8"))
        self.assertIsNone(extract_pan_shape(""))


class ExtractAllPanShapesTest(unittest.TestCase):
    def test_in_order(self):
        self.assertEqual(extract_all_pan_shapes("from a 9x9 to an 8-inch round"), [rect(9.0, 9.0), circle(8.0)])

    def test_half_of_a_pair_isnt_its_own_pan(self):
        self.assertEqual(extract_all_pan_shapes("8 by 16 inches"), [rect(8.0, 16.0)])

    def test_square_single(self):
        self.assertEqual(extract_all_pan_shapes("a 9-inch square"), [rect(9.0, 9.0)])

    def test_none(self):
        self.assertEqual(extract_all_pan_shapes("no pans here"), [])


class AreaAndDescriptionTest(unittest.TestCase):
    def test_area(self):
        self.assertEqual(pan_area(rect(9, 13)), 117)
        self.assertAlmostEqual(pan_area(circle(10)), math.pi * 25)
        self.assertIsNone(pan_area({"shape": "oval"}))

    def test_describe(self):
        self.assertEqual(describe_pan(rect(9.0, 13.0)), "9x13in rectangle")
        self.assertEqual(describe_pan(circle(9.0)), "9in circle")


class PanScaleFactorTest(unittest.TestCase):
    def test_factor(self):
        factor, explanation = pan_scale_factor("MAKES ONE 9-BY-9-INCH PAN", "my 8x8 pan")
        self.assertAlmostEqual(factor, 64 / 81)
        self.assertEqual(explanation, "Pan scaling: 8x8in rectangle (64.0 sq in) ÷ "
                                      "9x9in rectangle (81.0 sq in) = 0.790x")

    def test_missing_original(self):
        factor, reason = pan_scale_factor("Serves 8", "my 8x8 pan")
        self.assertIsNone(factor)
        self.assertIn("recipe's own yield line", reason)

    def test_missing_target(self):
        factor, reason = pan_scale_factor("a 9x9 pan", "mine is bigger")
        self.assertIsNone(factor)
        self.assertIn("your request", reason)


class PanScaleFactorFromQuestionTest(unittest.TestCase):
    NINE_TO_EIGHT = 64 / 81

    def test_recipe_pan_first(self):
        factor, _ = pan_scale_factor_from_question("the recipe calls for a 9x9 pan but I only have an 8x8")
        self.assertAlmostEqual(factor, self.NINE_TO_EIGHT)

    def test_my_pan_first(self):
        factor, _ = pan_scale_factor_from_question("I have an 8x8, but the recipe wants a 9x9")
        self.assertAlmostEqual(factor, self.NINE_TO_EIGHT)

    def test_no_cues_goes_by_order(self):
        factor, _ = pan_scale_factor_from_question("9x9 to 8x8")
        self.assertAlmostEqual(factor, self.NINE_TO_EIGHT)

    def test_same_cue_twice_goes_by_order(self):
        factor, _ = pan_scale_factor_from_question("i have a 9x9 and i have an 8x8")
        self.assertAlmostEqual(factor, self.NINE_TO_EIGHT)

    def test_round_to_square(self):
        factor, explanation = pan_scale_factor_from_question("the recipe uses a 9-inch round, mine is a 8x8")
        self.assertAlmostEqual(factor, 64 / (math.pi * 4.5 ** 2))
        self.assertIn("9in circle", explanation)

    def test_one_pan(self):
        factor, reason = pan_scale_factor_from_question("an 8 inch pan")
        self.assertIsNone(factor)
        self.assertIn("Found 1 pan size(s)", reason)

    def test_three_pans(self):
        factor, reason = pan_scale_factor_from_question("8x8, 9x9 and 9x13")
        self.assertIsNone(factor)
        self.assertIn("Found 3 pan sizes", reason)


class DetectPanRequestTest(unittest.TestCase):
    def test_pan_words(self):
        for q in ("use a bigger pan", "a 9 inch tin", "in a baking dish"):
            with self.subTest(q=q):
                self.assertTrue(detect_pan_request(q))

    def test_whole_words_only(self):
        for q in ("panic", "spanish rice", "double it"):
            with self.subTest(q=q):
                self.assertFalse(detect_pan_request(q))


if __name__ == "__main__":
    unittest.main()
