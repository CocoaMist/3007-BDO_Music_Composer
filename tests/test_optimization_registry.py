import unittest

from optimization import (
    DEFAULT_ALGORITHM,
    OptimizationResult,
    get_algorithm,
    list_algorithms,
    optimize_tracks,
    register_algorithm,
    unregister_algorithm,
)


class OptimizationRegistryTests(unittest.TestCase):
    def test_builtin_algorithm_is_discoverable(self):
        self.assertEqual(get_algorithm(DEFAULT_ALGORITHM).name, DEFAULT_ALGORITHM)
        self.assertIn(DEFAULT_ALGORITHM, [item.name for item in list_algorithms()])

    def test_extension_dispatch_and_teardown(self):
        name = "test-extension"
        calls = []

        def runner(tracks, bpm, supported_articulations, config=None, time_sig=4):
            calls.append((tracks, bpm, supported_articulations, config, time_sig))
            return OptimizationResult(tracks=list(tracks), reports=[])

        register_algorithm(name, runner, title="Test Extension")
        try:
            source = [object()]
            result = optimize_tracks(source, 90, {}, time_sig=3, algorithm=name)
            self.assertEqual(result.tracks, source)
            self.assertEqual(calls[0][1:], (90, {}, None, 3))
        finally:
            unregister_algorithm(name)

    def test_duplicate_names_require_explicit_replace(self):
        with self.assertRaises(ValueError):
            register_algorithm(DEFAULT_ALGORITHM, lambda *args: None, title="Duplicate")


if __name__ == "__main__":
    unittest.main()
