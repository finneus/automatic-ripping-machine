"""
Blu-ray year: the year ARM reads for a Blu-ray is the date of its bdmt_eng.xml, i.e. when the
disc was made. With it as a search filter an exact title of that year won, even an unknown one:
a Heat (1995) reissue from 2017 became "Heat (2017)", a Dune (2021) disc from 2022 "Dune (2022)".
Now a Blu-ray is first searched without year and the disc year is only a hint
(title_match.pick_by_disc_year). OMDb answers recorded from the real service on 2026-11-18.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, '/opt/arm')
from arm.ripper import identify, title_match  # noqa: E402


def omdb(*films):
    return {'Search': [{'Title': title, 'Year': year, 'imdbID': f'tt{index}', 'Type': 'movie', 'Poster': 'N/A'}
                       for index, (title, year) in enumerate(films)],
            'Response': 'True', 'background_url': None}


# (query as ARM sends it, year as ARM sends it) -> recorded answer; 'None' = search without year
OMDB = {
    ('Heat', 'None'): omdb(('Heat', '1995'), ('The Heat', '2013'), ('In the Heat of the Night', '1967'),
                           ('Red Heat', '1988'), ('Body Heat', '1981'), ('White Heat', '1949')),
    ('Heat', '2017'): omdb(('The Lions in Heat', '2017'), ('Nascar Heat 2', '2017'),
                           ('Dior: Poison Club - Rise the Heat - Stage 3', '2017'), ('Heat Lightning!', '2017'),
                           ('Heat', '2017'), ('Garage Heat', '2017')),
    ('RoboCop', 'None'): omdb(('RoboCop', '1987'), ('RoboCop', '2014'), ('RoboCop 2', '1990'), ('RoboCop 3', '1993'),
                              ('RoboCop: Prime Directives', '2001'), ('RoboCop', '1994'), ('RoboCop', '1988')),
    ('RoboCop', '2014'): omdb(('RoboCop', '2014'), ('Our RoboCop Remake', '2014'), ('Robocop - Omnicorp', '2014')),
    ('Point-Break', 'None'): omdb(('Point Break', '1991'), ('Point Break', '2015'),
                                  ('RiffTrax Live: Point Break', '2024'), ('Point Break', '2006')),
    ('Dune', 'None'): omdb(('Dune', '2021'), ('Dune: Part Two', '2024'), ('Dune', '1984'),
                           ('Dune: Prophecy', '2024–'), ("Jodorowsky's Dune", '2016'), ('Dune', '2000')),
    ('Dune', '2022'): omdb(('Rifftrax: Dune 2021', '2022'), ('DUNE the end of earth', '2022'),
                           ('Desert to Dune', '2022'), ('Dune', '2022'), ('A ridosso delle dune', '2022')),
}


def make_job(title, year, disctype='bluray'):
    return SimpleNamespace(title=title, year=year, label=title.upper().replace('-', '_'), disctype=disctype,
                           hasnicetitle=False, imdb_id=None, video_type=None, poster_url=None)


def fake_database_updater(args, job, *_args, **_kwargs):
    for key, value in args.items():
        setattr(job, key, value)
    return True


class TestPickByDiscYear(unittest.TestCase):

    def pick(self, key, query, disc_year):
        found = title_match.pick_by_disc_year(OMDB[key]['Search'], query, disc_year)
        return found and (found['Title'], found['Year'])

    def test_reissue_takes_the_known_film(self):
        self.assertEqual(self.pick(('Heat', 'None'), 'Heat', 2017), ('Heat', '1995'))

    def test_remake_disc_takes_the_remake(self):
        self.assertEqual(self.pick(('RoboCop', 'None'), 'RoboCop', 2014), ('RoboCop', '2014'))
        self.assertEqual(self.pick(('Point-Break', 'None'), 'Point Break', 2016), ('Point Break', '2015'))

    def test_old_disc_takes_the_original(self):
        self.assertEqual(self.pick(('RoboCop', 'None'), 'RoboCop', 2008), ('RoboCop', '1987'))

    def test_nothing_newer_than_the_disc(self):
        self.assertEqual(self.pick(('Dune', 'None'), 'Dune', 2022), ('Dune', '2021'))
        self.assertEqual(self.pick(('Dune', 'None'), 'Dune', 1995), ('Dune', '1984'))

    def test_no_exact_title(self):
        self.assertIsNone(self.pick(('Heat', 'None'), 'Heat Wave', 2017))

    def test_first_year(self):
        self.assertEqual(title_match.first_year('2017–2020'), 2017)
        self.assertEqual(title_match.first_year('2024–'), 2024)
        self.assertIsNone(title_match.first_year('N/A'))


class TestIdentifyBlurayYear(unittest.TestCase):

    def identify(self, job):
        searched = []

        def fake_omdb(title, year):
            searched.append((title, year))
            return OMDB.get((title, year))

        with patch.dict(identify.cfg.arm_config, {'METADATA_PROVIDER': 'omdb'}), \
                patch.object(identify.ui_utils, 'call_omdb_api', side_effect=fake_omdb), \
                patch.object(identify.utils, 'database_updater', side_effect=fake_database_updater):
            identify.get_video_details(job)
        return searched

    def test_heat_reissue(self):
        """CHECK Heat (1995) on a 2017 disc is not named after the unknown "Heat" (2017)"""
        job = make_job('Heat', '2017')
        searched = self.identify(job)
        self.assertEqual((job.title, job.year), ('Heat', '1995'))
        self.assertEqual(searched, [('Heat', 'None')])

    def test_dune_disc_2022(self):
        job = make_job('Dune', '2022')
        self.identify(job)
        self.assertEqual((job.title, job.year), ('Dune', '2021'))

    def test_remake_disc(self):
        """CHECK (control, also true before) a remake on a fresh disc stays the remake"""
        job = make_job('RoboCop', '2014')
        self.identify(job)
        self.assertEqual((job.title, job.year), ('RoboCop', '2014'))

    def test_falls_back_to_year_search(self):
        """CHECK a title that has no exact match without year still gets the year-filtered search"""
        job = make_job('Garage-Heat', '2017')
        answers = {('Garage-Heat', '2017'): omdb(('Garage Heat', '2017'))}
        with patch.dict(OMDB, answers):
            searched = self.identify(job)
        self.assertEqual(searched[:2], [('Garage-Heat', 'None'), ('Garage-Heat', '2017')])
        self.assertEqual((job.title, job.year), ('Garage-Heat', '2017'))

    def test_dvd_unchanged(self):
        """CHECK DVDs keep the year-first search (their year does not come from bdmt_eng.xml)"""
        job = make_job('Heat', '2017', disctype='dvd')
        searched = self.identify(job)
        self.assertEqual(searched[0], ('Heat', '2017'))


if __name__ == '__main__':
    unittest.main()
