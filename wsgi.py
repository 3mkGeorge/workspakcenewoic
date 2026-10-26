"""Production WSGI entry point.

Gunicorn loads ``wsgi:app``. The Windows launcher (``python app.py``) keeps
using its own Waitress entry point, so both platforms share ``create_app``.
"""

from app import create_app

app = create_app()
