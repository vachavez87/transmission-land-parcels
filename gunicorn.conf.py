"""
gunicorn.conf.py — Gunicorn configuration for Render deployment.

The post_fork hook starts the pipeline background thread INSIDE each worker
process after gunicorn forks it. This is critical because gunicorn uses a
pre-fork model: any thread started in the master process is not visible to
worker processes (they get a separate copy of memory). Starting the thread
in post_fork ensures _pipeline_ready and _state are updated in the same
process that handles HTTP requests.
"""

workers = 1
timeout = 300


def post_fork(server, worker):
    """Called in each worker process immediately after forking."""
    from server import start_pipeline_thread
    start_pipeline_thread()
