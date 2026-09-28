"""Repository configuration invariants; no Docker daemon or secrets needed."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_database_is_private_and_passwords_are_required(self):
        compose = yaml.safe_load((ROOT / 'docker-compose.yml').read_text(encoding='utf-8'))
        db = compose['services']['db']
        backend = compose['services']['backend']
        self.assertNotIn('ports', db)
        self.assertIn(':?', db['environment']['MYSQL_ROOT_PASSWORD'])
        self.assertIn(':?', db['environment']['MYSQL_PASSWORD'])
        self.assertTrue(any(item.startswith('DB_PASSWORD=${MYSQL_PASSWORD:?') for item in backend['environment']))
        self.assertEqual(backend['depends_on']['db']['condition'], 'service_healthy')

    def test_example_has_no_default_destinations_or_passwords(self):
        example = dict(line.split('=', 1) for line in (ROOT / '.env.example').read_text(encoding='utf-8').splitlines()
                       if line and not line.startswith('#'))
        for key in ['URLS', 'DASHBOARD_URL', 'TG_BOT_TOKEN', 'TG_CHAT_ID', 'MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD']:
            self.assertEqual(example[key], '')


if __name__ == '__main__':
    unittest.main()
