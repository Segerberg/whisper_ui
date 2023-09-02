FROM python:3.11.0-alpine

RUN adduser -D chat

WORKDIR /home/chat

COPY requirements.txt requirements.txt

RUN apk update

RUN apk add --no-cache --update \
  python3 \
  python3-dev \
  py3-gevent \
  uwsgi \
  uwsgi-python3 \
  uwsgi-http \
  uwsgi-gevent3 \
  make \
  libffi-dev \
  gcc \
  musl-dev \
  make \
  ffmpeg \

RUN pip install -r requirements.txt
RUN pip install eventlet
RUN pip install gunicorn

# COPY app app
# COPY files files
# COPY migrations migrations
# COPY chat.py config.py boot.sh create_superuser.py ./
# RUN chmod +x boot.sh

# ENV FLASK_APP chat.py
# ENV FLASK_APP_BRAND PRISE CHAT
# ENV SUPERUSER_NAME superuser
# ENV SUPERUSER_PASSWORD password


# RUN chown -R chat:chat ./
# USER chat

#RUN flask db init
#RUN flask db migrate
#RUN flask db upgrade
# RUN python create_superuser.py
# VOLUME /home/chat/files
EXPOSE 5000
ENTRYPOINT ["sh","boot.sh"]