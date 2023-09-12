#!/bin/sh

exec gunicorn -b :5000  -w 1 app:app
