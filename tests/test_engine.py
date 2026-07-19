import unittest

from scheduler import SchedulerEngine


class SchedulerEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SchedulerEngine(autostart=False, aging_factor=0.5)

    def test_shorter_job_preempts_running_job(self) -> None:
        first = self.engine.add_job("Video_A", 8)
        second = self.engine.add_job("Video_B", 3)

        self.assertEqual(self.engine.running_job.pid, second.pid)
        self.assertEqual(len(self.engine.ready_queue), 1)
        self.assertEqual(self.engine.ready_queue[0].pid, first.pid)

    def test_aging_guard_counts_shorter_cpu_entries_not_arrivals(self) -> None:
        long_job = self.engine.add_job("Long_Current", 12)

        short_one = self.engine.add_job("Short_One", 2)
        short_two = self.engine.add_job("Short_Two", 2)
        short_three = self.engine.add_job("Short_Three", 2)

        self.assertEqual(self.engine.running_job.pid, short_one.pid)
        self.assertFalse(long_job.is_aging_protected)
        self.assertEqual(long_job.shorter_job_entries, 1)

        self.engine.tick()
        self.engine.tick()

        self.assertEqual(self.engine.running_job.pid, short_two.pid)
        self.assertFalse(long_job.is_aging_protected)
        self.assertEqual(long_job.shorter_job_entries, 2)

        self.engine.tick()
        self.engine.tick()

        self.assertEqual(self.engine.running_job.pid, short_three.pid)
        self.assertTrue(long_job.is_aging_protected)
        self.assertEqual(long_job.shorter_job_entries, 3)

    def test_protected_job_is_not_preempted_by_later_short_job(self) -> None:
        long_job = self.engine.add_job("Long_Current", 12)
        self.engine.add_job("Short_One", 2)
        self.engine.add_job("Short_Two", 2)
        self.engine.add_job("Short_Three", 2)

        self.engine.tick()
        self.engine.tick()
        self.engine.tick()
        self.engine.tick()

        self.assertEqual(self.engine.running_job.pid, "VID-4")
        self.assertTrue(long_job.is_aging_protected)

        self.engine.add_job("Short_Four", 1)

        self.engine.tick()
        self.engine.tick()

        self.assertEqual(self.engine.running_job.pid, long_job.pid)
        self.assertTrue(self.engine.running_job.is_aging_protected)

    def test_completed_jobs_record_turnaround(self) -> None:
        job = self.engine.add_job("Tiny", 1)
        self.engine.tick()

        self.assertIsNone(self.engine.running_job)
        self.assertEqual(len(self.engine.completed_jobs), 1)
        self.assertEqual(self.engine.completed_jobs[0].pid, job.pid)
        self.assertEqual(self.engine.completed_jobs[0].turnaround_time, 1)


if __name__ == "__main__":
    unittest.main()
