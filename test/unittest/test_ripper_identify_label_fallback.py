"""
Title search: don't shorten the title down to one word, and search the volume label
when the disc title finds nothing.

Real case (2.24.4 + title matching): Blu-ray with label DARK_KNIGHT_RISES and a disc
title that starts with "Dark Knight", year 2017 (date of bdmt_eng.xml of the reissue).
The full title found nothing, identify_loop() shortened it word by word, "Dark-Knight"
(2017) only found unrelated titles, and "Dark" (2017) matched the series "Dark"
(2017-2020) exactly. The label as words finds "The Dark Knight Rises" (2012).
The OMDb answers below were recorded from the real service on 2026-11-18.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, '/opt/arm')
from arm.ripper import identify, title_match  # noqa: E402


def omdb(*films):
    return {'Search': [{'Title': title, 'Year': year, 'imdbID': f'tt{index}', 'Type': kind, 'Poster': 'N/A'}
                       for index, (title, year, kind) in enumerate(films)],
            'Response': 'True', 'background_url': None}


# (query as ARM sends it, year as ARM sends it) -> recorded OMDb answer; anything else: not found
OMDB = {
    ('Dark-Knight', '2017'): omdb(('Arkham: Tales of the Dark Knight', '2017–', 'series'),
                                  ('Gimbago the Dark Knight', '2017', 'movie')),
    ('Dark', '2017'): omdb(('Dark', '2017–2020', 'series'), ('The Dark Tower', '2017', 'movie'),
                           ('Super Dark Times', '2017', 'movie')),
    ('Dark+Knight+Rises', 'None'): omdb(('The Dark Knight Rises', '2012', 'movie'),
                                        ('The Fire Rises: The Creation and Impact of the Dark Knight Trilogy',
                                         '2013', 'movie'),
                                        ('The Dark Knight Rises', '2012', 'game')),
}


def make_job(title, year, label):
    return SimpleNamespace(title=title, year=year, label=label, hasnicetitle=False, imdb_id=None,
                           video_type=None, poster_url=None)


def fake_database_updater(args, job, *_args, **_kwargs):
    for key, value in args.items():
        setattr(job, key, value)
    return True


class TestLabelSearchTitle(unittest.TestCase):

    def test_words_from_label(self):
        self.assertEqual(title_match.label_search_title('DARK_KNIGHT_RISES'), 'Dark+Knight+Rises')

    def test_disc_markers_are_dropped(self):
        self.assertEqual(title_match.label_search_title('INCEPTION_D1'), 'Inception')
        self.assertEqual(title_match.label_search_title('LOST_S2_DISC_3'), 'Lost+S2')
        self.assertEqual(title_match.label_search_title('AVATAR_BLURAY_UHD'), 'Avatar')
        self.assertEqual(title_match.label_search_title('300_DISC_2'), '300')

    def test_no_label(self):
        for label in (None, '', 'not identified', '___'):
            with self.subTest(label=label):
                self.assertEqual(title_match.label_search_title(label), '')


class TestShortening(unittest.TestCase):

    def test_word_count(self):
        self.assertEqual(title_match.count_words('Dark-Knight+Rises'), 3)
        self.assertEqual(title_match.count_words(''), 0)

    def test_keep_half_and_at_least_two(self):
        self.assertEqual(title_match.min_words_after_shortening(2), 2)
        self.assertEqual(title_match.min_words_after_shortening(3), 2)
        self.assertEqual(title_match.min_words_after_shortening(5), 3)
        self.assertEqual(title_match.min_words_after_shortening(8), 4)


class TestIdentifyWithLabelFallback(unittest.TestCase):

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

    def test_dark_knight_rises(self):
        """CHECK the series "Dark" is not taken and the label finds The Dark Knight Rises"""
        job = make_job('Dark-Knight-Feature-Presentation', '2017', 'DARK_KNIGHT_RISES')
        searched = self.identify(job)
        self.assertNotIn(('Dark', '2017'), searched)
        self.assertEqual((job.title, job.year, job.video_type), ('The-Dark-Knight-Rises', '2012', 'movie'))

    def test_shortened_title_keeps_two_words(self):
        """CHECK no query is shortened below two words"""
        job = make_job('Dark-Knight-Feature-Presentation', '2017', 'DARK_KNIGHT_RISES')
        searched = self.identify(job)
        self.assertTrue(all(title_match.count_words(query) >= 2 for query, _ in searched), searched)

    def test_label_not_searched_when_title_found(self):
        """CHECK the label is only a fallback"""
        job = make_job('Dark Knight Rises', '', 'SOMETHING_ELSE')
        searched = self.identify(job)
        self.assertEqual(searched, [('Dark+Knight+Rises', 'None')])
        self.assertEqual(job.title, 'The-Dark-Knight-Rises')

    def test_label_same_as_title_not_searched_twice(self):
        job = make_job('Unknown Home Movie', '', 'UNKNOWN_HOME_MOVIE')
        searched = self.identify(job)
        self.assertEqual([q for q, _ in searched].count('Unknown+Home+Movie'), 1)
        self.assertFalse(job.hasnicetitle)


if __name__ == '__main__':
    unittest.main()
