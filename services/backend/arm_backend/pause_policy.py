"""What the global pause does to a new job, the one rule every way a job starts follows."""

from arm_common import Config

PAUSED_DETAIL = "ripping is paused; no new jobs accepted"


def refuses_new_jobs(cfg: Config | None) -> bool:
    """Whether the pause turns a new job away: paused with the review hold off.

    With the hold on (the header's Pause toggle sets both), a paused machine still takes a disc, scans and identifies
    it, and parks it for review; the pause only stops the review countdown from starting the rip. A disc inserted, a
    Start rip on the drive card and an ISO rip all follow this one rule. No config row (not read yet) refuses nothing.
    """
    return cfg is not None and bool(cfg.ripping_paused) and not cfg.hold_for_review
