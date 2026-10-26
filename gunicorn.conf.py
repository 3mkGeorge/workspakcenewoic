"""Gunicorn configuration for the Render deployment.

One worker is intentional: the application owns a SQLite database, background
backup/maintenance threads and a persistent disk that cannot be shared between
instances. Concurrency inside that single process comes from threads.
"""

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("STOREPRO_THREADS", "4"))
timeout = int(os.environ.get("STOREPRO_REQUEST_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("STOREPRO_LOG_LEVEL", "info")
