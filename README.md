# FCDeletions
a really really small, quick'n'dirty telegram bot that sends deleted messages from a group to another channel

## Docker
```
# docker build . -t fcdeletions:v1
$ docker run -it --rm  -v "${PWD}/.tdlib":"/tmp/.tdlib_files" fcdeletions:v1 python <script>.py
```
