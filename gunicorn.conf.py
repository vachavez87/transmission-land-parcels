# gunicorn.conf.py — Gunicorn configuration for Render deployment.
#
# preload_app=True: gunicorn imports server.py ONCE in the master process
# before forking workers. _run_pipeline() runs in master (~4 seconds), then
# workers are forked and inherit _state via copy-on-write. No threads needed.

workers = 1
timeout = 300
preload_app = True
