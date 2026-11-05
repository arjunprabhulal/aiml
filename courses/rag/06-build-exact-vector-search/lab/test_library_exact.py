import unittest
import numpy as np
from library_exact import cosine_distances
class ExactTests(unittest.TestCase):
    def test_scaling_a_vector_does_not_change_cosine_distance(self):
        np.testing.assert_allclose(cosine_distances([[1,0],[0,2]],[3,0]),[0,1])
    def test_wrong_dimension_is_refused(self):
        with self.assertRaisesRegex(ValueError,'dimensions'): cosine_distances([[1,0]],[1,0,0])
    def test_zero_vector_is_refused(self):
        with self.assertRaisesRegex(ValueError,'nonzero'): cosine_distances([[0,0]],[1,0])
    def test_nan_is_refused(self):
        with self.assertRaisesRegex(ValueError,'finite'): cosine_distances([[float('nan'),0]],[1,0])
if __name__=='__main__':unittest.main(verbosity=2)
