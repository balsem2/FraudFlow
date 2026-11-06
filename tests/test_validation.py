import unittest
import numpy as np
import pandas as pd
from fraudflow.validation import chronological_split, select_threshold


class ValidationTests(unittest.TestCase):
    def test_split_is_chronological_disjoint_and_complete(self):
        steps = pd.Series([9, 0, 6, 4, 7, 8, 1, 5, 2, 3, 6, 9])
        train, validation, test = chronological_split(steps)
        self.assertTrue((train.astype(int) + validation.astype(int) + test.astype(int) == 1).all())
        self.assertLess(steps[train].max(), steps[validation].min())
        self.assertLess(steps[validation].max(), steps[test].min())
        self.assertEqual(steps[validation].min(), 6)
        self.assertEqual(steps[test].min(), 8)

    def test_threshold_can_recover_frauds_below_default(self):
        labels = np.array([0, 0, 1, 1])
        scores = np.array([0.05, 0.1, 0.2, 0.4])
        threshold = select_threshold(labels, scores)
        self.assertEqual(threshold, 0.2)
        np.testing.assert_array_equal(scores >= threshold, labels)

    def test_too_few_steps_rejected(self):
        with self.assertRaises(ValueError):
            chronological_split(pd.Series([0, 0, 1]))
