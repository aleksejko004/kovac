# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parameters: units, expressions, promotion, regeneration (headless)."""
import unittest

import FreeCAD as App

from helpers import feature, live_bodies, rect, sketch
from kovac import features, model, params


class Params(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("P")
        sk = sketch(self.doc, rect(0, 0, 40, 20))
        self.ex = feature(self.doc, features.Extrude, Profile=sk, Length=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def volume(self):
        model.commit(self.doc)
        return live_bodies(self.doc)[0].Shape.Volume

    def test_units_convert(self):
        params.set_value(self.ex, "Length", "1 in")
        self.assertAlmostEqual(self.ex.Length.Value, 25.4, 9)
        self.assertAlmostEqual(self.volume(), 800 * 25.4, 6)

    def test_user_parameter_drives_model(self):
        params.add_user(self.doc, "Thickness", "Length", "5 mm")
        params.set_value(self.ex, "Length", "Thickness * 2")          # bare name works
        self.assertAlmostEqual(self.volume(), 8000, 6)
        params.set_value(params.varset(self.doc), "Thickness", "8 mm")
        self.assertAlmostEqual(self.volume(), 800 * 16, 6)

    def test_promote_model_value(self):
        params.promote(self.ex, "Length", "PlateT")
        self.assertIn("PlateT", params.user_params(self.doc))
        self.assertEqual(params.expression(self.ex, "Length"), "Parameters.PlateT")
        params.set_value(params.varset(self.doc), "PlateT", "12")
        self.assertAlmostEqual(self.volume(), 800 * 12, 6)
        with self.assertRaises(ValueError):
            params.remove_user(self.doc, "PlateT")                     # still used

    def test_model_params_listed_by_feature(self):
        names = [(o.Name, p) for o, p in params.model_params(self.doc)]
        self.assertIn((self.ex.Name, "Length"), names)
        self.assertNotIn((self.ex.Name, "BodyState"), names)

    def test_bad_names_rejected(self):
        with self.assertRaises(ValueError):
            params.add_user(self.doc, "2fast")


if __name__ == "__main__":
    unittest.main()
