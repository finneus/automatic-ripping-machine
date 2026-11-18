"""
makemkv_info: the penalty after "makemkv info" (MANUAL_WAIT_TIME seconds) is only
needed when another job may still want a MakeMKV slot. A single disc used to wait
for nothing on every rip.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text

sys.path.insert(0, '/opt/arm')
from arm.ripper import makemkv  # noqa: E402
from arm.ui import app, db  # noqa: E402

OWN_JOB_ID = 990001
OTHER_JOB_ID = 990002


class TestOtherJobsMayNeedMakemkv(unittest.TestCase):
    """Runs the real query against the test database"""

    def setUp(self):
        self.context = app.app_context()
        self.context.push()
        db.create_all()
        self.remove_jobs()
        self.add_job(OWN_JOB_ID, "waiting")

    def tearDown(self):
        self.remove_jobs()
        self.context.pop()

    @staticmethod
    def add_job(job_id, status):
        db.session.execute(text("INSERT INTO job (job_id, status) VALUES (:id, :status)"),
                           {"id": job_id, "status": status})
        db.session.commit()

    @staticmethod
    def remove_jobs():
        db.session.execute(text("DELETE FROM job WHERE job_id IN (:a, :b)"), {"a": OWN_JOB_ID, "b": OTHER_JOB_ID})
        db.session.commit()

    def check(self):
        return makemkv.other_jobs_may_need_makemkv(SimpleNamespace(job_id=OWN_JOB_ID))

    def test_alone(self):
        """CHECK the own job alone needs no penalty"""
        self.assertFalse(self.check())

    def test_other_job_waiting(self):
        """CHECK a job waiting for a slot or the manual override keeps the penalty"""
        self.add_job(OTHER_JOB_ID, "waiting")
        self.assertTrue(self.check())

    def test_other_job_starting(self):
        """CHECK a job that is still being set up keeps the penalty"""
        self.add_job(OTHER_JOB_ID, "active")
        self.assertTrue(self.check())

    def test_other_job_reading_disc(self):
        self.add_job(OTHER_JOB_ID, "info")
        self.assertTrue(self.check())

    def test_finished_or_ripping_jobs_do_not_count(self):
        """CHECK jobs that no longer ask for an info slot are ignored"""
        for status in ("success", "fail", "ripping", "transcoding"):
            with self.subTest(status=status):
                self.remove_jobs()
                self.add_job(OWN_JOB_ID, "waiting")
                self.add_job(OTHER_JOB_ID, status)
                self.assertFalse(self.check())

    def test_database_error_keeps_penalty(self):
        """CHECK the old behaviour (penalty) when the database cannot be asked"""
        with patch.object(makemkv, "Job") as job_model:
            job_model.query.filter.side_effect = RuntimeError("database is locked")
            self.assertTrue(self.check())


class TestMakemkvInfoPenalty(unittest.TestCase):

    def run_info(self, others_waiting):
        job = SimpleNamespace(job_id=OWN_JOB_ID, status=None,
                              config=SimpleNamespace(MANUAL_WAIT_TIME=60, MINLENGTH=600))
        with patch.dict(makemkv.cfg.arm_config, {"MAX_CONCURRENT_MAKEMKVINFO": 1}), \
                patch.object(makemkv, "run", return_value=iter(())), \
                patch.object(makemkv.utils, "sleep_check_process"), \
                patch.object(makemkv, "db"), \
                patch.object(makemkv, "other_jobs_may_need_makemkv", return_value=others_waiting), \
                patch.object(makemkv, "sleep") as sleep:
            list(makemkv.makemkv_info(job))
        return sleep

    def test_no_penalty_when_alone(self):
        self.run_info(others_waiting=False).assert_not_called()

    def test_penalty_when_others_wait(self):
        self.run_info(others_waiting=True).assert_called_once_with(60)


if __name__ == '__main__':
    unittest.main()
