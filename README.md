# telegramwtf
*just ignore me*
plz don't judge me, I'm new to Pythonscre

## Docker
```
$ docker build . -t telegramwtf:v1
$ docker run -it --rm  -v "${PWD}/.tdlib":"/tmp/.tdlib_files" telegramwtf:v1 python ./auto_forward_messages.py
```