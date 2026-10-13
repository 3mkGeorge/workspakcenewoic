"""Background Job Monitoring Service for StorePro.

Maintains a centralized registry of background workers and scheduled tasks,
tracking operational status, run frequencies, execution durations, and error telemetry.
"""

import threading
import time
from contextlib import contextmanager
from datetime import datetime


class BackgroundJobRecord:
    def __init__(self, name, description="", frequency="Manual"):
        self.name = name
        self.description = description
        self.frequency = frequency
        self.status = "Idle"  # "Idle", "Running", "Completed", "Failed"
        self.last_run = None
        self.next_run = None
        self.last_duration_ms = 0.0
        self.run_count = 0
        self.failure_count = 0
        self.last_error = ""

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "frequency": self.frequency,
            "status": self.status,
            "last_run": self.last_run.strftime("%Y-%m-%d %H:%M:%S") if self.last_run else "Never",
            "next_run": self.next_run.strftime("%Y-%m-%d %H:%M:%S") if self.next_run else "—",
            "last_duration_ms": round(self.last_duration_ms, 1),
            "run_count": self.run_count,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
        }


class JobMonitorRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}

    def register(self, name, description="", frequency="Manual"):
        with self._lock:
            if name not in self._jobs:
                self._jobs[name] = BackgroundJobRecord(name, description, frequency)
            else:
                if description:
                    self._jobs[name].description = description
                if frequency:
                    self._jobs[name].frequency = frequency
            return self._jobs[name]

    def set_next_run(self, name, next_dt):
        with self._lock:
            job = self._jobs.get(name)
            if job:
                self.job = job
                job.next_run = next_dt

    @contextmanager
    def track(self, name, description="", frequency=None):
        with self._lock:
            if name not in self._jobs:
                self._jobs[name] = BackgroundJobRecord(name, description, frequency or "Manual")
            job = self._jobs[name]
            job.status = "Running"
            start_time = time.perf_counter()

        error_occurred = None
        try:
            yield job
        except Exception as exc:
            error_occurred = exc
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            with self._lock:
                job.last_run = datetime.now()
                job.last_duration_ms = elapsed_ms
                job.run_count += 1
                if error_occurred:
                    job.status = "Failed"
                    job.failure_count += 1
                    job.last_error = str(error_occurred)[:300]
                else:
                    job.status = "Completed"
                    job.last_error = ""

    def get_job(self, name):
        with self._lock:
            job = self._jobs.get(name)
            return job.to_dict() if job else None

    def get_all_jobs(self):
        with self._lock:
            return [job.to_dict() for job in self._jobs.values()]


# Global singleton instance
job_monitor = JobMonitorRegistry()
