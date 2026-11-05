import tempfile
from pathlib import Path
import unittest
from memory_lifecycle import Memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [100]
        self.memory = Memory(clock=lambda: self.now[0])

    def tearDown(self):
        self.memory.close()

    def put(self, value, ttl=60):
        return self.memory.put('alice', 'docuctl', 'release', value, source='fixture user', ttl=ttl)

    def test_correction_does_not_reuse_the_old_value(self):
        self.put('release-41')
        self.put('release-42')
        self.assertEqual(self.memory.get('alice', 'docuctl', 'release')['value'], 'release-42')

    def test_other_principal_and_purpose_cannot_read_the_row(self):
        self.put('release-41')
        self.assertIsNone(self.memory.get('bob', 'docuctl', 'release'))
        self.assertIsNone(self.memory.get('alice', 'another-app', 'release'))

    def test_expired_correction_does_not_revive_old_memory(self):
        self.put('release-41', ttl=60)
        self.put('release-42', ttl=10)
        self.now[0] = 110
        self.assertIsNone(self.memory.get('alice', 'docuctl', 'release'))

    def test_deletion_removes_every_revision(self):
        self.put('release-41')
        self.put('release-42')
        self.assertEqual(self.memory.delete('alice', 'docuctl', 'release'), 2)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM memory').fetchone()[0], 0)

    def test_file_storage_survives_reopening(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'memory.db'
            a = Memory(path, clock=lambda: 100)
            a.put('alice', 'docuctl', 'release', 'release-42', source='fixture', ttl=60)
            a.close()
            b = Memory(path, clock=lambda: 100)
            try:
                self.assertEqual(b.get('alice', 'docuctl', 'release')['revision'], 1)
            finally:
                b.close()


if __name__ == '__main__':
    unittest.main()
