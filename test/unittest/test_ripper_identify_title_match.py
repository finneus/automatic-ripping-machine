"""
Metadata search: a result is only used when its title matches the disc title.

Regression test for THE_DARK_KNIGHT being named "Batman - 80 Years of the Dark
Knight (DCAU)": the year of a Blu-ray is the date of its bdmt_eng.xml (2019 here),
OMDb then only returned films of 2019 and the first one was taken blindly.
The OMDb answers below were recorded from the real service.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, '/opt/arm')
from arm.ripper import identify  # noqa: E402


def omdb(*films):
    """Build an OMDb search response from (title, year) pairs."""
    return {'Search': [{'Title': title, 'Year': year, 'imdbID': f'tt{index}', 'Type': 'movie', 'Poster': 'N/A'}
                       for index, (title, year) in enumerate(films)],
            'Response': 'True', 'background_url': None}


# What OMDb returns for the query "The Dark Knight", per year filter
OMDB_DARK_KNIGHT = {
    '2019': omdb(('The Dark Red Knight Rises', '2019'), ('Batman - 80 Years of the Dark Knight (DCAU)', '2019')),
    '2018': omdb(('The Dark Knight: The Ballad of the N Word', '2018'), ('Batman: The Dark Knight', '2018')),
    '': omdb(('The Dark Knight', '2008'), ('The Dark Knight Rises', '2012'),
             ('Batman: The Dark Knight Returns, Part 1', '2012')),
}


def make_job(title, year):
    return SimpleNamespace(title=title, year=year, label=title, hasnicetitle=False, imdb_id=None,
                           video_type=None, poster_url=None)


def fake_database_updater(args, job, *_args, **_kwargs):
    for key, value in args.items():
        setattr(job, key, value)
    return True


class TestSelectMatchingResults(unittest.TestCase):

    def test_unrelated_results_are_dropped(self):
        """CHECK nothing is returned when no result carries the searched title"""
        self.assertIsNone(identify.select_matching_results(OMDB_DARK_KNIGHT['2019'], 'The+Dark+Knight', '2019'))

    def test_best_match_comes_first(self):
        """CHECK the exact title is moved in front of earlier sequels"""
        result = identify.select_matching_results(omdb(('Alien Resurrection', '1997'), ('Alien', '1979')),
                                                  'Alien', '')
        self.assertEqual(result['Search'][0]['Title'], 'Alien')

    def test_continuation_only_without_year(self):
        """CHECK "Title: Subtitle" counts only when the search was not filtered by a year"""
        found = omdb(('Lord of the Rings: The Return of the King', '2003'))
        self.assertIsNone(identify.select_matching_results(found, 'Lord+of+the+Rings', '2003'))
        found = omdb(('Lord of the Rings: The Return of the King', '2003'))
        self.assertIsNotNone(identify.select_matching_results(found, 'Lord+of+the+Rings', ''))

    def test_response_without_results_is_passed_on(self):
        """CHECK None and answers without a result list are not changed"""
        self.assertIsNone(identify.select_matching_results(None, 'x', ''))
        self.assertEqual(identify.select_matching_results({'Error': 'x'}, 'x', ''), {'Error': 'x'})


class TestIdentifyLoopTitleMatch(unittest.TestCase):

    def identify_with_omdb(self, job, answers):
        """Run identify_loop with a fake OMDb and return the years that were searched."""
        searched = []

        def fake_omdb(title, year):
            searched.append(year)
            return answers.get('' if year == 'None' else year)

        with patch.dict(identify.cfg.arm_config, {'METADATA_PROVIDER': 'omdb'}), \
                patch.object(identify.ui_utils, 'call_omdb_api', side_effect=fake_omdb), \
                patch.object(identify.utils, 'database_updater', side_effect=fake_database_updater):
            identify.get_video_details(job)
        return searched

    def test_dark_knight_with_bluray_xml_year(self):
        """CHECK the wrong disc year does not replace The Dark Knight (2008)"""
        job = make_job('The Dark Knight', '2019')
        searched = self.identify_with_omdb(job, OMDB_DARK_KNIGHT)
        self.assertEqual(job.title, 'The-Dark-Knight')
        self.assertEqual(job.year, '2008')
        self.assertEqual(searched, ['2019', '2018', 'None'])  # ARM sends str(None) when searching without a year

    def test_right_year_is_used_directly(self):
        """CHECK a correct year still finds the film in the first search"""
        job = make_job('The Dark Knight', '2008')
        answers = {'2008': omdb(('The Dark Knight', '2008'), ('Batman: The Dark Knight', '2008'))}
        searched = self.identify_with_omdb(job, answers)
        self.assertEqual(job.year, '2008')
        self.assertEqual(searched, ['2008'])

    def test_nothing_matching_keeps_the_disc_title(self):
        """CHECK a title no result matches stays as it is instead of being replaced by a guess"""
        job = make_job('Obscure Home Video', '2019')
        answers = {'': omdb(('Something Else Entirely', '2019'))}
        self.identify_with_omdb(job, answers)
        self.assertEqual(job.title, 'Obscure Home Video')
        self.assertFalse(job.hasnicetitle)


if __name__ == '__main__':
    unittest.main()
