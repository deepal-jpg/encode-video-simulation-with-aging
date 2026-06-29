from __future__ import annotations

import threading
from typing import Any

from .models import Job


class SchedulerEngine:
    def __init__(
        self,
        tick_seconds: float = 1.0,
        aging_factor: float = 0.35,
        autostart: bool = True,
        max_logs: int = 200,
        max_shorter_job_entries: int = 3,
    ) -> None:
        self.tick_seconds = tick_seconds
        self.aging_factor = aging_factor
        self.max_logs = max_logs
        self.max_shorter_job_entries = max_shorter_job_entries
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._job_counter = 0
        self.clock_seconds = 0
        self._protected_job_pid: str | None = None
        self.running_job: Job | None = None
        self.ready_queue: list[Job] = []
        self.completed_jobs: list[Job] = []
        self.event_log: list[str] = []
        if autostart:
            self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.tick_seconds + 1)

    def reset(self) -> None:
        with self._lock:
            self._job_counter = 0
            self.clock_seconds = 0
            self._protected_job_pid = None
            self.running_job = None
            self.ready_queue.clear()
            self.completed_jobs.clear()
            self.event_log.clear()
            self._log_locked("System reset. Global clock returned to 00:00.")

    def add_job(self, name: str, burst_time: int) -> Job:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Job name is required.")
        if burst_time <= 0:
            raise ValueError("Burst time must be a positive integer.")

        with self._lock:
            self._job_counter += 1
            job = Job(
                pid=f"VID-{self._job_counter}",
                name=clean_name,
                arrival_time=self.clock_seconds,
                burst_time=burst_time,
                remaining_time=burst_time,
                aging_factor=self.aging_factor,
            )
            job.refresh_effective_priority()
            self.ready_queue.append(job)
            self._log_locked(
                f"[{self.format_clock(self.clock_seconds)}] Arrival -> {job.pid} "
                f"({job.name}) joined the ready queue with burst {job.burst_time}s."
            )
            self._maybe_preempt_for_new_arrival_locked(job)
            self._evaluate_schedule_locked()
            return job

    def tick(self) -> None:
        with self._lock:
            self.clock_seconds += 1
            for job in self.ready_queue:
                job.waiting_time += 1
                job.refresh_effective_priority()

            if self.running_job is not None:
                self.running_job.remaining_time = max(self.running_job.remaining_time - 1, 0)

            if self.running_job is not None and self.running_job.remaining_time == 0:
                completed_job = self.running_job
                completed_job.status = "completed"
                completed_job.completed_at = self.clock_seconds
                completed_job.turnaround_time = self.clock_seconds - completed_job.arrival_time
                completed_job.refresh_effective_priority()
                self._clear_aging_guard_locked(completed_job)
                self.completed_jobs.append(completed_job)
                self._log_locked(
                    f"[{self.format_clock(self.clock_seconds)}] Complete -> {completed_job.pid} "
                    f"finished in {completed_job.turnaround_time}s turnaround."
                )
                self.running_job = None

            self._evaluate_schedule_locked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ready_queue = sorted(self.ready_queue, key=self._priority_key)
            return {
                "clock_seconds": self.clock_seconds,
                "clock_label": self.format_clock(self.clock_seconds),
                "running_job": self.running_job.to_dict() if self.running_job else None,
                "ready_queue": [job.to_dict() for job in ready_queue],
                "completed_jobs": [job.to_dict() for job in self.completed_jobs[-5:]],
                "event_log": list(self.event_log),
                "stats": {
                    "total_jobs": self._job_counter,
                    "queue_size": len(self.ready_queue),
                    "completed_count": len(self.completed_jobs),
                    "cpu_state": "busy" if self.running_job else "idle",
                },
                "config": {
                    "aging_factor": self.aging_factor,
                    "tick_seconds": self.tick_seconds,
                    "max_shorter_job_entries": self.max_shorter_job_entries,
                },
            }

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.tick_seconds):
            self.tick()

    def _evaluate_schedule_locked(self) -> None:
        protected_job = self._get_protected_job_locked()

        if self.running_job is None:
            candidate = protected_job or self._best_ready_job_locked()
            if candidate is not None:
                reason = "aging" if candidate.is_aging_protected else "dispatch"
                self._dispatch_job_locked(candidate, reason=reason)
            return

        if protected_job is not None:
            return

    def _best_ready_job_locked(self) -> Job | None:
        if not self.ready_queue:
            return None
        return min(self.ready_queue, key=self._priority_key)

    def _dispatch_job_locked(self, job: Job, reason: str) -> None:
        self.ready_queue = [queued_job for queued_job in self.ready_queue if queued_job.pid != job.pid]
        job.status = "running"
        if not job.is_aging_protected:
            job.shorter_job_entries = 0
            job.shorter_job_pids_seen.clear()
        job.refresh_effective_priority()
        self.running_job = job
        if reason == "dispatch":
            verb = "Started"
        elif reason == "aging":
            verb = "Aging dispatch"
        else:
            verb = "Resumed"
        self._log_locked(
            f"[{self.format_clock(self.clock_seconds)}] {verb} -> {job.pid} "
            f"({job.name}) is now using the CPU."
        )
        self._track_shorter_cpu_entry_locked(job)

    def _track_shorter_cpu_entry_locked(self, running_job: Job) -> None:
        if running_job.is_aging_protected:
            return

        active_jobs = [job for job in self.ready_queue if job.pid != running_job.pid]
        protected_candidates: list[Job] = []

        for existing_job in active_jobs:
            if existing_job.is_aging_protected:
                continue
            if existing_job.arrival_time > running_job.arrival_time:
                continue
            if existing_job.remaining_time <= running_job.remaining_time:
                continue
            if running_job.pid in existing_job.shorter_job_pids_seen:
                continue

            existing_job.shorter_job_pids_seen.add(running_job.pid)
            existing_job.shorter_job_entries = len(existing_job.shorter_job_pids_seen)
            if existing_job.shorter_job_entries >= self.max_shorter_job_entries:
                protected_candidates.append(existing_job)

        if protected_candidates:
            job_to_protect = min(protected_candidates, key=lambda job: (job.arrival_time, job.pid))
            self._activate_aging_guard_locked(job_to_protect)

    def _maybe_preempt_for_new_arrival_locked(self, new_job: Job) -> None:
        if self.running_job is None:
            return

        if self.running_job.is_aging_protected:
            return

        if self._protected_job_pid is not None:
            return

        if new_job.remaining_time < self.running_job.remaining_time:
            self._preempt_with_job_locked(
                new_job,
                "Context switch -> a shorter newly arrived job takes the CPU.",
                reason="resume",
            )

    def _activate_aging_guard_locked(self, job: Job) -> None:
        if self._protected_job_pid == job.pid:
            return

        if self._protected_job_pid is not None:
            current_protected = self._get_protected_job_locked()
            if current_protected is not None:
                current_protected.is_aging_protected = False

        self._protected_job_pid = job.pid
        job.is_aging_protected = True
        self._log_locked(
            f"[{self.format_clock(self.clock_seconds)}] Aging guard -> {job.pid} "
            f"reached the limit of {self.max_shorter_job_entries} shorter CPU entries and will run next."
        )

    def _clear_aging_guard_locked(self, job: Job | None = None) -> None:
        if job is None:
            self._protected_job_pid = None
            return

        if self._protected_job_pid == job.pid:
            self._protected_job_pid = None
        job.is_aging_protected = False
        job.shorter_job_entries = 0
        job.shorter_job_pids_seen.clear()

    def _get_protected_job_locked(self) -> Job | None:
        if self._protected_job_pid is None:
            return None

        if self.running_job is not None and self.running_job.pid == self._protected_job_pid:
            return self.running_job

        for job in self.ready_queue:
            if job.pid == self._protected_job_pid:
                return job

        self._protected_job_pid = None
        return None

    def _preempt_with_job_locked(self, candidate: Job, context_message: str, reason: str) -> None:
        if self.running_job is None or self.running_job.pid == candidate.pid:
            self._dispatch_job_locked(candidate, reason=reason)
            return

        previous_job = self.running_job
        previous_job.status = "ready"
        previous_job.refresh_effective_priority()
        self.ready_queue.append(previous_job)
        self.running_job = None
        self._log_locked(
            f"[{self.format_clock(self.clock_seconds)}] {context_message} "
            f"{previous_job.pid} paused, {candidate.pid} takes the CPU."
        )
        self._dispatch_job_locked(candidate, reason=reason)

    def _priority_key(self, job: Job) -> tuple[float, int, str]:
        return (job.refresh_effective_priority(), job.arrival_time, job.pid)

    def _log_locked(self, message: str) -> None:
        self.event_log.append(message)
        if len(self.event_log) > self.max_logs:
            self.event_log = self.event_log[-self.max_logs :]

    @staticmethod
    def format_clock(seconds: int) -> str:
        minutes, remaining_seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{remaining_seconds:02d}"
