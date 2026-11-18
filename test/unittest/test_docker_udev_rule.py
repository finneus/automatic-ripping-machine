"""
The Docker udev rule must run after 60-cdrom_id.rules, otherwise ID_CDROM_MEDIA* are
unset when it is matched and every "change" event (tray opened, disc ejected after a
rip, repeated events) starts an ARM job ("Starting ARM for unknown disc type").
"""
import fnmatch
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
RULE_NAME = '99-docker-arm.rules'


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


def rule_line():
    lines = [line for line in read('setup', RULE_NAME).splitlines() if line.strip() and not line.startswith('#')]
    assert len(lines) == 1, lines
    return lines[0]


class TestDockerUdevRule(unittest.TestCase):

    def test_runs_after_cdrom_id(self):
        self.assertGreater(RULE_NAME, '60-cdrom_id.rules')
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'setup', '51-docker-arm.rules')))

    def test_dockerfile_installs_this_rule(self):
        self.assertIn(f'/opt/arm/setup/{RULE_NAME} /lib/udev/rules.d/', read('Dockerfile'))
        self.assertNotIn('51-docker-arm.rules', read('Dockerfile'))

    def test_ignores_eject_and_empty_drive(self):
        line = rule_line()
        self.assertIn('ENV{DISK_EJECT_REQUEST}!="1"', line)
        self.assertIn('ENV{ID_CDROM_MEDIA}=="1"', line)
        self.assertIn('ENV{ID_CDROM_MEDIA_STATE}!="blank"', line)

    def test_matches_ten_and_more_drives(self):
        kernel = re.search(r'KERNEL=="([^"]+)"', rule_line()).group(1)
        for name in ('sr0', 'sr9', 'sr10', 'sr15'):
            self.assertTrue(fnmatch.fnmatchcase(name, kernel), name)
        self.assertFalse(fnmatch.fnmatchcase('sda', kernel))


if __name__ == '__main__':
    unittest.main()
