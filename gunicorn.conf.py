import os
bind = f"0.0.0.0:{os.getenv('WEB_PORT','8080')}"
workers = 1
threads = int(os.getenv("GUNICORN_THREADS","4"))
timeout = int(os.getenv("GUNICORN_TIMEOUT","90"))
accesslog = "logs/gunicorn.access.log"
errorlog = "logs/gunicorn.error.log"
loglevel = os.getenv("GUNICORN_LOGLEVEL","info")
