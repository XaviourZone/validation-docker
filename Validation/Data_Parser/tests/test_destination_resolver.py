import unittest

from Validation.Data_Parser.app.pipeline import unlocode


class TestDestinationResolver(unittest.TestCase):
    def setUp(self):
        unlocode._CACHE = {
            "ADALV": "Andorra la Vella",
            "SGSIN": "Singapore",
        }
        unlocode._NAME_CACHE = {
            unlocode._normalise_name("Andorra la Vella"): "Andorra la Vella",
            unlocode._normalise_name("Singapore"): "Singapore",
        }

    def tearDown(self):
        unlocode._CACHE = None
        unlocode._NAME_CACHE = None

    def test_unlocode_without_space(self):
        self.assertEqual(unlocode.resolve_destination("ADALV"), "Andorra la Vella")

    def test_unlocode_with_space(self):
        self.assertEqual(unlocode.resolve_destination("AD ALV"), "Andorra la Vella")

    def test_destination_name_is_canonicalized(self):
        self.assertEqual(unlocode.resolve_destination("  singapore  "), "Singapore")

    def test_unknown_free_text_is_preserved(self):
        self.assertEqual(unlocode.resolve_destination("MY CUSTOM DESTINATION"), "MY CUSTOM DESTINATION")


if __name__ == "__main__":
    unittest.main()
