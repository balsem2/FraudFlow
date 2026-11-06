import unittest

import pandas as pd

from fraudflow.model import features, pipeline


class ModelContractTests(unittest.TestCase):
    def transaction(self, **changes):
        record = dict(amount=12.5, age="'3'", gender="'F'", step=180,
                      customer='new-customer', merchant='new-merchant',
                      zipcodeOri='28007', zipMerchant='28007',
                      category="'es_transportation'")
        record.update(changes)
        return pd.DataFrame([record])

    def test_label_is_excluded_and_identity_is_retained(self):
        clean = features(self.transaction(fraud=1, customer='customer-id'))
        self.assertNotIn('fraud', clean)
        self.assertEqual(clean.loc[0, 'customer'], 'customer-id')
        self.assertEqual(len(clean.columns), 9)
        self.assertEqual(clean.loc[0, 'age'], '3')

    def test_invalid_amount_is_rejected(self):
        for amount in [-1, float('inf'), float('nan')]:
            transaction = self.transaction()
            transaction['amount'] = amount
            with self.assertRaises(ValueError):
                features(transaction)

    def test_unseen_category_can_be_scored(self):
        training = pd.concat([
            self.transaction(amount=amount, step=i, customer='known-customer',
                             merchant='known-merchant', category='known')
            for i, amount in enumerate([1, 5, 100, 200])
        ], ignore_index=True)
        model = pipeline()
        model.fit(features(training), [0, 0, 1, 1])
        score = float(model.predict_proba(features(self.transaction()))[0, 1])
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 1)

    def test_invalid_step_is_rejected(self):
        for step in [-1, 0.5, float('inf'), float('nan')]:
            with self.assertRaises(ValueError):
                features(self.transaction(step=step))


if __name__ == '__main__':
    unittest.main()
