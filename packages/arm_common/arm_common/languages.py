"""ISO 639-2 audio language codes as ARM compares them.

MakeMKV and mkvmerge write a language as its bibliographic code (`ger`, `fre`), ffprobe and the settings as its
terminological one (`deu`, `fra`). `terminological` maps the first onto the second so both compare equal.
"""

# The ISO 639-2 languages whose bibliographic code differs from the terminological one.
_BIBLIOGRAPHIC_TO_TERMINOLOGICAL = {
    "alb": "sqi",
    "arm": "hye",
    "baq": "eus",
    "bur": "mya",
    "chi": "zho",
    "cze": "ces",
    "dut": "nld",
    "fre": "fra",
    "geo": "kat",
    "ger": "deu",
    "gre": "ell",
    "ice": "isl",
    "mac": "mkd",
    "mao": "mri",
    "may": "msa",
    "per": "fas",
    "rum": "ron",
    "slo": "slk",
    "tib": "bod",
    "wel": "cym",
}

# The audio languages the settings offer, terminological code -> name.
AUDIO_LANGUAGE_LABELS = {
    "deu": "German",
    "eng": "English",
    "fra": "French",
    "spa": "Spanish",
    "ita": "Italian",
    "nld": "Dutch",
    "por": "Portuguese",
    "pol": "Polish",
    "ces": "Czech",
    "hun": "Hungarian",
    "rus": "Russian",
    "tur": "Turkish",
    "swe": "Swedish",
    "dan": "Danish",
    "nor": "Norwegian",
    "fin": "Finnish",
    "jpn": "Japanese",
    "kor": "Korean",
    "zho": "Chinese",
}


def terminological(code: str) -> str:
    """The lowercase terminological ISO 639-2 code for `code` (a bibliographic one is mapped, any other kept)."""
    lowered = code.strip().lower()
    return _BIBLIOGRAPHIC_TO_TERMINOLOGICAL.get(lowered, lowered)


def preferred_languages(values: list[str] | None) -> list[str]:
    """The `preferred_audio_languages` setting as ARM uses it: terminological codes the settings offer, first
    occurrence kept, in the operator's order. Unknown and repeated codes are dropped, so a stale value never errors."""
    out: list[str] = []
    for code in (terminological(v) for v in values or []):
        if code in AUDIO_LANGUAGE_LABELS and code not in out:
            out.append(code)
    return out
