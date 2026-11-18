import importlib.util
import os
import unittest

# Load the module by path: importing it as arm.ripper.title_match would pull in
# the whole ARM package (Flask, database, ...), which this pure logic does not need.
_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'arm', 'ripper', 'title_match.py')
_SPEC = importlib.util.spec_from_file_location('title_match', _PATH)
title_match = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(title_match)


def results(*titles):
    return [{'Title': title, 'Year': '2000'} for title in titles]


class TestNormalizeTitle(unittest.TestCase):

    def test_label_and_title_are_equal(self):
        for variant in ("THE_DARK_KNIGHT", "The Dark Knight", "the+dark+knight", "The-Dark-Knight"):
            self.assertEqual(title_match.normalize_title(variant), "dark knight")

    def test_accents_and_punctuation(self):
        self.assertEqual(title_match.normalize_title("Amélie: (2001)"), "amelie 2001")

    def test_single_word_article_is_kept(self):
        self.assertEqual(title_match.normalize_title("The"), "the")

    def test_empty(self):
        self.assertEqual(title_match.normalize_title(None), "")


class TestRankResults(unittest.TestCase):

    def test_dark_knight_with_wrong_year_matches_nothing(self):
        """The real failure: year 2019 filtered OMDb to unrelated films."""
        found = results("The Dark Red Knight Rises",
                        "Batman - 80 Years of the Dark Knight (DCAU)")
        self.assertEqual(title_match.rank_results(found, "THE DARK KNIGHT"), [])

    def test_dark_knight_without_year_picks_the_film(self):
        found = results("The Dark Knight Rises", "The Dark Knight",
                        "Batman: The Dark Knight Returns, Part 1")
        ranked = title_match.rank_results(found, "The Dark Knight")
        self.assertEqual(ranked[0]['Title'], "The Dark Knight")

    def test_exact_beats_earlier_sequel(self):
        found = results("Alien Resurrection", "Alien")
        ranked = title_match.rank_results(found, "Alien")
        self.assertEqual([r['Title'] for r in ranked], ["Alien", "Alien Resurrection"])

    def test_truncated_label_matches_longer_title(self):
        """identify_loop shortens a disc label word by word; the full title starts with it."""
        found = results("The Lord of the Rings: The Fellowship of the Ring")
        ranked = title_match.rank_results(found, "Lord of the Rings")
        self.assertEqual(len(ranked), 1)

    def test_continuation_refused_when_year_filtered(self):
        """"Title: Subtitle" of the wrong year must not win on a year-filtered search."""
        found = results("The Dark Knight: The Ballad of the N Word")
        self.assertEqual(title_match.rank_results(found, "The Dark Knight", allow_continuation=False), [])
        self.assertEqual(len(title_match.rank_results(found, "The Dark Knight")), 1)

    def test_similar_but_different_title_is_rejected(self):
        found = results("The Dark Red Knight Rises")
        self.assertEqual(title_match.rank_results(found, "Dark Knight Rises"), [])

    def test_contained_but_not_leading_is_rejected(self):
        found = results("Batman - 80 Years of the Dark Knight (DCAU)")
        self.assertEqual(title_match.rank_results(found, "Dark Knight"), [])

    def test_provider_order_kept_for_equal_scores(self):
        found = results("Heat", "Heat")
        found[0]['Year'], found[1]['Year'] = '1995', '1986'
        ranked = title_match.rank_results(found, "Heat")
        self.assertEqual([r['Year'] for r in ranked], ['1995', '1986'])

    def test_small_typo_is_accepted(self):
        found = results("Inception")
        self.assertEqual(len(title_match.rank_results(found, "Incepton")), 1)

    def test_empty_and_none(self):
        self.assertEqual(title_match.rank_results(None, "x"), [])
        self.assertEqual(title_match.rank_results([], "x"), [])
        self.assertEqual(title_match.rank_results(results("x"), ""), [])


if __name__ == '__main__':
    unittest.main()
