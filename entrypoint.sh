#!/bin/sh

exec gunicorn -b :5000 --worker-class eventlet -w 1 chat:app