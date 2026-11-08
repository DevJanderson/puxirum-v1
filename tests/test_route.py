import unittest

from puxirum.config import Config, parse
from puxirum.route import RouteError, reviewers


class RouteTest(unittest.TestCase):
    def test_default_table(self):
        c = Config()
        cases = [
            ("low", [], {"code": "haiku"}),
            ("medium", [], {"code": "sonnet"}),
            ("low", ["ui"], {"code": "haiku", "ux": "sonnet", "ui": "haiku"}),
            ("high", ["ui", "security"], {"code": "sonnet", "ux": "sonnet", "ui": "haiku", "security": "opus"}),
        ]
        for risk, surfaces, want in cases:
            with self.subTest(risk=risk, surfaces=surfaces):
                self.assertEqual(reviewers(c, risk, surfaces), want)

    def test_surface_overrides_risk_model(self):
        c = parse({"routing": {"risk": {"low": {"code": "haiku"}, "medium": {"code": "haiku"}, "high": {"code": "haiku"}},
                               "surfaces": {"security": {"code": "opus", "security": "opus"}}}})
        self.assertEqual(reviewers(c, "low", ["security"]), {"code": "opus", "security": "opus"})

    def test_unknown_surface_or_risk(self):
        with self.assertRaisesRegex(RouteError, "surface 'db'"):
            reviewers(Config(), "low", ["db"])
        with self.assertRaisesRegex(RouteError, "risk 'huge'"):
            reviewers(Config(), "huge", [])

    def test_empty_route_is_an_error(self):
        c = parse({"routing": {"risk": {"low": {}, "medium": {}, "high": {}}}})
        with self.assertRaisesRegex(RouteError, "no reviewer"):
            reviewers(c, "low", [])


if __name__ == "__main__":
    unittest.main()
