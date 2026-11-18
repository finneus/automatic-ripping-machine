"""Choose which metadata search result actually matches the disc title.

OMDb / TMDB searches return a *list* of loosely related titles. The identify
code used to take the first entry blindly, so a wrong year filter or an
unlucky ordering turned "The Dark Knight" into "Batman - 80 Years of the Dark
Knight (DCAU)". This module is deliberately free of ARM imports so it can be
unit-tested on its own.
"""
import re
import unicodedata
from difflib import SequenceMatcher

# A result must be at least this similar to the searched title to be accepted
# when it is neither identical nor a continuation of it.
FUZZY_THRESHOLD = 0.92

_ARTICLES = ("the", "a", "an")


def normalize_title(title):
    """Lower-case, strip accents/punctuation, drop a leading article.

    "The Dark Knight", "THE_DARK_KNIGHT" and "the+dark+knight" all become
    "dark knight".
    """
    text = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    words = text.split()
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def title_score(query, candidate, allow_continuation=True):
    """Rate how well a search result title matches the searched title.

    :param allow_continuation: accept results that merely start with the query.
        Callers turn this off when the search was filtered by a year, because
        the year of a disc is unreliable and a half-matching title of that year
        is then more likely wrong than right.
    :return: 3 identical, 2 candidate starts with the query (sequel, subtitle
             or "Title: Subtitle"), 1 very similar, 0 unrelated
    """
    wanted = normalize_title(query)
    found = normalize_title(candidate)
    if not wanted or not found:
        return 0
    if wanted == found:
        return 3
    if allow_continuation and found.startswith(wanted + " "):
        return 2
    if SequenceMatcher(None, wanted, found).ratio() >= FUZZY_THRESHOLD:
        return 1
    return 0


def rank_results(results, query, allow_continuation=True):
    """Return the acceptable results, best first.

    Results with the same score keep the order of the search provider. Results
    that do not match the query at all are dropped, so a caller can fall back
    to another search (for example without the year) instead of guessing.

    :param results: list of dicts with a "Title" key (OMDb format)
    :param query: the title that was searched for
    :param allow_continuation: see title_score()
    """
    scored = [(title_score(query, item.get("Title", ""), allow_continuation), index, item)
              for index, item in enumerate(results or [])]
    scored = [entry for entry in scored if entry[0] > 0]
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [item for _, _, item in scored]


# Volume label words that describe the disc, not the film: DISC1, DISC, D1, CD2, SIDE1, BD, BLURAY, UHD, 4K, WS, FS ...
_LABEL_NOISE = re.compile(r"^(?:(?:disc|disk)\d*|(?:d|cd|side)\d+|bd|bluray|uhd|4k|ws|fs|widescreen|fullscreen)$")


def label_search_title(label):
    """Turn a volume label into a search query: DARK_KNIGHT_RISES_D1 -> "Dark+Knight+Rises".

    :return: the query, or "" for no label or the "not identified" placeholder
    """
    if normalize_title(label) in ("", "not identified"):
        return ""
    kept = []
    after_disc_marker = False
    for word in (word for word in re.split(r"[^A-Za-z0-9]+", str(label)) if word):
        if _LABEL_NOISE.match(word.lower()) or (after_disc_marker and word.isdigit()):
            # "DISC_3": the number belongs to the marker; a number elsewhere ("300") stays
            after_disc_marker = word.lower() in ("disc", "disk")
            continue
        after_disc_marker = False
        kept.append(word)
    return "+".join(word.capitalize() for word in kept)


def count_words(query):
    """Number of words in a search query, whatever separates them (space, +, -, _)."""
    return len([word for word in re.split(r"[\s+_-]+", str(query or "")) if word])


def min_words_after_shortening(word_count):
    """How many words a shortened query must keep: half of the original, never fewer than two.

    Shortening "Dark-Knight" to "Dark" finds the series "Dark" - one word matches far too much.
    """
    return max(2, (word_count + 1) // 2)
