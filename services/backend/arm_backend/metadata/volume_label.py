"""Turn a disc's raw volume label into a search title and a release year."""

import re
import unicodedata

# A release year at the end of the label (`THE_MATRIX_1999`, `Movie (2010)`). Capped at 2029, like the disc-hint
# year in `metadata.dispatcher`, so a title ending in a later number (BLADE_RUNNER_2049) keeps it. A number
# earlier in the label (2001_A_SPACE_ODYSSEY) is part of the title, never the year.
_YEAR_SUFFIX_RE = re.compile(r"[\s_\-.]*\(?(?<!\d)(19\d{2}|20[0-2]\d)\)?\s*$")
# DVDs commonly bake the broadcast standard into the volume label
# (e.g. `THE_MATRIX_NTSC` or `MOVIE_NTSC_1999`). It's noise for title
# matching — strip it before the underscore-to-space pass so OMDB/TMDB
# searches don't see "MATRIX NTSC".
_NTSC_TOKEN_RE = re.compile(r"_NTSC(?=[_.\s\-]|$)", re.IGNORECASE)
# Blu-rays bake disc-format branding into the title/label the same way.
# v2 stripped a fixed set of "Blu-rayTM" suffixes off the BDMV disc title
# (see arm/ripper/main/identify.py); reproduce that here generically so a
# label like `MOVIE_BLU_RAY`, `Movie - Blu-rayTM`, or `BLURAY` loses the
# branding before lookup. The optional `tm|™` covers the trademark glyph
# in either pre- or post-ASCII-normalised form.
_BLURAY_BRANDING_RE = re.compile(r"[\s_\-]*blu[\s_\-]?ray(?:\s*(?:tm|™))?", re.IGNORECASE)
# `_BD` (Blu-ray Disc) token, mirroring the `_NTSC` treatment.
_BD_TOKEN_RE = re.compile(r"_BD(?=[_.\s\-]|$)", re.IGNORECASE)


def normalize_volume_label(label: str) -> tuple[str, int | None]:
    # Fold compatibility glyphs WITHOUT dropping non-ASCII: NFKC turns
    # "Blu-ray™" → "Blu-rayTM" and full-width forms → half-width, but keeps
    # accents and non-Latin scripts intact ("Amélie", "Война и мир", "君の名は"
    # all survive) so worldwide titles still reach the providers. This is
    # deliberately NOT the NFKD→ASCII strip `slugify` uses — that targets
    # ASCII filename tokens; here we must preserve the real searchable title.
    cleaned = unicodedata.normalize("NFKC", label)
    cleaned = _NTSC_TOKEN_RE.sub("", cleaned)
    cleaned = _BD_TOKEN_RE.sub("", cleaned)
    cleaned = _BLURAY_BRANDING_RE.sub("", cleaned)
    cleaned = cleaned.replace("_", " ").replace(".", " ").strip()
    cleaned, year = _split_year(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned, year


def _split_year(cleaned: str) -> tuple[str, int | None]:
    """Split a release year off the end of `cleaned`. A label that is nothing but a year (`1917`) is the title."""
    m = _YEAR_SUFFIX_RE.search(cleaned)
    if m is None:
        return cleaned, None
    title = cleaned[: m.start()].strip()
    if not title:
        return cleaned, None
    return title, int(m.group(1))
