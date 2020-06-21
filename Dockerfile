FROM python:3.8.3-buster

WORKDIR /usr/src/app

# Requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .