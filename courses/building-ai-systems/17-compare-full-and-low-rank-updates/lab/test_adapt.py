import copy
import unittest
from adapt import Model, base_weights, evaluate, experiment, features, validate_split
class AdaptTests(unittest.TestCase):
    def test_lora_starts_as_exact_base_and_freezes_it(self):
        base=base_weights();m=Model(base,1);self.assertEqual(m.effective(),base)
        m.train([{'text':'rotate key','label':'credentials'}],epochs=10)
        self.assertEqual(m.base,base);self.assertNotEqual(m.effective(),base)
    def test_parameter_counts_follow_matrix_shapes(self):
        self.assertEqual(Model(base_weights()).trainable,30)
        self.assertEqual(Model(base_weights(),1).trainable,13)
        self.assertEqual(Model(base_weights(),2).trainable,26)
    def test_training_reduces_loss_on_training_example(self):
        rows=[{'id':'example','text':'restore release','label':'rollback'}]
        for rank in [None,1,2]:
            m=Model(base_weights(),rank);before=evaluate(m,rows)['mean_cross_entropy']
            m.train(rows);self.assertLess(evaluate(m,rows)['mean_cross_entropy'],before)
    def test_unknown_label_and_empty_split_rejected(self):
        with self.assertRaises(ValueError):validate_split([],[])
        with self.assertRaises(ValueError):validate_split([{'text':'deploy','label':'unknown'}],[{'text':'release','label':'deployment'}])
    def test_split_leakage_rejected(self):
        row={'text':'deploy','label':'deployment'}
        with self.assertRaisesRegex(ValueError,'duplicate'):validate_split([row],[copy.deepcopy(row)])
    def test_different_text_with_the_same_features_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate model input'):
            validate_split([{'text':'restore release','label':'rollback'}],
                           [{'text':'please restore this release','label':'rollback'}])
    def test_invalid_rank_rejected(self):
        for rank in [0,4]:
            with self.assertRaises(ValueError):Model(base_weights(),rank)
    def test_repeated_experiments_match(self):self.assertEqual(experiment(),experiment())
if __name__ == '__main__':unittest.main()
