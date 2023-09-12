FROM python:3.10-slim

WORKDIR /home/whisper_ui

RUN apt update -y
RUN apt-get install -y ffmpeg

COPY static static
COPY templates templates
COPY app.py config.py entrypoint.sh requirements.txt ./

RUN pip install -r requirements.txt

RUN mkdir /data

ENV FLASK_APP app.py

RUN flask db init
RUN flask db migrate
RUN flask db upgrade

VOLUME /data
#EXPOSE 5000
#ENTRYPOINT ["sh","entrypoint.sh"]