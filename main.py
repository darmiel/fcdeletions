from telegram.client import Telegram

from redis import Redis
from redis import ConnectionError

from datetime import datetime

from ah_settings import settings
from ah_settings import bmodes

from termcolor import colored

import json
import random

# Settings
s = settings['del-edit-detector']

#
#
#

def pretty_print(mode: str, msg: str):
    mode_color = 'white'
    if mode == bmodes.FWD:
        mode_color = 'green'
    elif mode == bmodes.DETECTOR:
        mode_color = 'yellow'
    elif mode == bmodes.DBG:
        mode_color = 'blue'
    print(colored('[', 'white') + colored(mode, mode_color) + colored(']: ', 'white') + colored(msg, 'white'))

if settings['del-edit-detector']['enable']:
    # Redis stuff
    redis = Redis(
        s['redis']['host'], 
        port=s['redis']['port'], 
        db=s['redis']['db'], 
        password=s['redis']['password']
    )

    try:
        redis.ping()
    except ConnectionError as e:
        pretty_print(bmodes.DETECTOR, colored('ERROR', 'red') + colored('Redis connection error:', 'white'))
        print(e)
        exit()

#
#
#

# initialize telegram client
tg = Telegram(
    settings['telegram']['api-key'],
    settings['telegram']['api-hash'],
    database_encryption_key=settings['telegram']['database-encryption-key'],
    phone=settings['telegram']['phone']
)

# login to telegram, you may have to input a 2fa-key
tg.login()

#
#
#

class User:
    def __init__(self, id = None, first_name = None, last_name = None, username = None, phone_number = None):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.phone_number = phone_number

def user_by_id(user_id: int) -> User:
    global tg

    user_req = tg.get_user(user_id)
    user_req.wait()

    res = user_req.update

    if not 'username' in res:
        return None

    return User(
        id=res['id'], 
        first_name=res['first_name'], 
        last_name=res['last_name'], 
        username=res['username'], 
        phone_number=res['phone_number']
    )

class Message:
    def __init__(self, msg_id = None, chat_id = None, date = None, author_id = None, content_type = None, content_text = None, edit_date = None, message_raw = None):
        self.msg_id = msg_id
        self.chat_id = chat_id
        self.date = date
        self.author_id = author_id
        self.content_type = content_type
        self.content_text = content_text
        self.edit_date = edit_date
        self.message_raw = message_raw
    
    def get_redis_key(self):
        return f"{self.chat_id}-{self.msg_id}"

    def valid_chat(self, chat_id):
        return self.chat_id == chat_id

    def save_redis(self):
        global redis, s

        # insert into redis
        redis.set(self.get_redis_key(), json.dumps(self.message_raw))

        # expire after 7 days (7 * 86400)
        redis.expire(self.get_redis_key(), s['redis']['ttl'])

def message_by_update(update) -> Message:

    if update == None:
        return None

    # create message
    m = Message(message_raw=update, msg_id=update['id'], chat_id=update['chat_id'])

    # get meta data from message
    m.author_id = m.message_raw['sender_user_id']
    m.date = m.message_raw['date']
    
    m.edit_date = m.message_raw['edit_date']

    # get content
    m.content_type = "n/a"
    if 'content' in m.message_raw:
        m.content_type = m.message_raw['content']['@type']
        m.content_text = get_message_as_text(m.message_raw)

    return m

def message_by_id(chat_id, msg_id) -> Message:
    global tg

    msg_req = tg.get_message(chat_id, msg_id)
    msg_req.wait()

    res = msg_req.update

    print(res)

    return message_by_update(res)

def message_by_redis(chat_id, msg_id) -> Message:
    global redis

    m = Message(chat_id=chat_id, msg_id=msg_id)
    res = redis.get(m.get_redis_key())
    if res == None:
        return None
    
    return message_by_update(json.loads(res.decode("UTF-8")))

def get_message_as_text(message):
    msg_content_text = "n/a"
    if 'content' in message:
        content = message['content']

        if 'text' in content:
            msg_content_text = content['text']['text']

        # if the message contains an image,
        # the content is in the caption section
        if 'caption' in content:
            msg_content_text = content['caption']['text']
    
    if len(msg_content_text.strip()) == 0:
        msg_content_text = "n/a"

    return msg_content_text

"""
This event is executed as soon as a message is received. 
We need this event to temporarily store all messages in the redis for about 7 days, 
so that the content can still be played back when the message is deleted. 
"""
def detector_on_message(update):
    if not 'message' in update:
        return

    msg = message_by_update(update['message'])

    if msg == None or not msg.valid_chat(s['checking-chat']):
        return

    # save message to redis
    msg.save_redis()

"""
This event is executed when messages are deleted. 
The cached message, if any, 
will be pulled out of the redis and sent to the channel if it is not a cached-deletion.
"""
def detector_on_messages_delete(update):

    # check if 'chat_id' is in update
    if not 'chat_id' in update:
        print("Dbg: chat_id not in update")
        return

    # chat id of deleted message
    msg_chat_id = update['chat_id']
    
    # Check for chat id
    if msg_chat_id != s['checking-chat']:
        return
    
    if update['from_cache'] != False:
        return

    # print update to console
    pretty_print(bmodes.DETECTOR, colored('Deleted: ', 'cyan') + colored(update, 'white'))

    # check if there are any deleted messages (there should!)
    if not 'message_ids' in update:
        return
    
    # message ids to check
    msg_ids = update['message_ids']

    for m_id in msg_ids:
        check_and_send_deleted_message(msg_chat_id, m_id)

def check_and_send_deleted_message(chat_id, message_id):
    global redis

    msg = message_by_redis(chat_id, message_id)
    if msg == None:
        pretty_print(bmodes.DETECTOR, 
            colored(message_id, 'magenta') + 
            colored(' in ', 'white') + 
            colored(chat_id, 'magenta') + 
            colored(' deleted, but not cached.', 'white'))
        return

    user = user_by_id(msg.author_id)
    
    # ignore messageChat(Add|Remove)Members
    if not 'Text' in msg.content_type:
        return

    # Build message
    m = ""

    # Author
    m += random.choice(s['people-emojis']) + " " # emoji
    if user == None:
        m += f"User **#{msg.author_id}**:\n"
    else:
        m += f"{user.first_name} {user.last_name} [@{user.username}]:\n"
        
    # Date
    m += str(datetime.utcfromtimestamp(msg.date).strftime('%Y-%m-%d %H:%M:%S')) + str("\n")

    # hr
    m += str("\n")

    # content as text
    m += f'🗑️ **@{msg.content_type}**: {msg.content_text}'
    
    res = tg.send_message(s['sending-chat'], m)
    res.wait()

    # add to redis for statistical purposes
    redis.set(f"deleted-{chat_id}-{message_id}", json.dumps(msg.message_raw))

def on_message_edit(update):

    if not 'chat_id' in update:
        return

    msg_chat_id = update['chat_id']
    
    # Check for chat id
    if msg_chat_id != s['checking-chat']:
        return

    if not 'message_id' in update:
        return
    
    msg_id = update['message_id']
    
    nm = message_by_id(msg_chat_id, msg_id)

    if nm == None:
        return

    om = message_by_redis(msg_chat_id, msg_id)
    if om == None:
        return
    
    # save new version
    nm.save_redis()
    
    new_text = nm.content_text
    old_text = om.content_text

    print(new_text, old_text)

    if old_text == new_text or old_text == None or new_text == None or new_text == "n/a":
        return
    
    # ignore messageChat(Add|Remove)Members
    if 'Member' in om.content_type:
        return

    u = user_by_id(nm.author_id)

    # Build message
    m = ""

    # Author
    m += random.choice(s['people-emojis']) + " " # emoji
    if u == None:
        m += f"User **#{nm.author_id}**:\n"
    else:
        m += f"{u.first_name} {u.last_name} [@{u.username}]:\n"
        
    # Date
    m += str(datetime.utcfromtimestamp(nm.edit_date).strftime('%Y-%m-%d %H:%M:%S')) + str("\n")

    # hr
    m += str("\n")

    # content as text
    m += f'✏️ **@{om.content_type}**: {om.content_text}\n'
    m += f'to\n'
    m += f'✏️ **@{nm.content_type}**: {nm.content_text}\n'
    
    pretty_print(bmodes.DETECTOR, "Found editied message: " + colored(f'#{nm.msg_id}', 'magenta') + colored(' | sending ...', 'white'))

    res = tg.send_message(s['sending-chat'], m)
    res.wait()

def forwarder_on_message(update):

    # check if message is in update
    if not 'message' in update:
        return

    # get message from update
    message = update['message']

    # get meta data from message
    msg_id = message['id']
    msg_chat_id = message['chat_id']
    msg_forward_ability = message['can_be_forwarded']
    msg_content = get_message_as_text(message)

    # check if this message is from ah's channel
    if msg_chat_id != settings['forwarder']['chat-pull']:
        return

    pretty_print(bmodes.FWD, f'Found message in pull-channel: {colored(f"#{msg_id}", "magenta")} {colored("« ", "white")}{colored(msg_content, "yellow")}{colored(" »", "white")}')

    # check if we can forward this message
    if not msg_forward_ability:
        pretty_print(bmodes.FWD, colored('Warning: ', 'yellow') + colored(f"Found message, but can't forward message #{msg_id} ('{msg_content}')", 'white'))
        return

    # call forwarding
    res = tg.call_method("forwardMessages", params={
        'chat_id': settings['forwarder']['chat-publish'],
        'from_chat_id': msg_chat_id,
        'message_ids': [msg_id],
        'options': {},
        'as_album': False,
        'send_copy': False,
        'remove_caption': False
    })
    res.wait()

    print(settings['forwarder']['chat-publish'])

    if res.error:
        pretty_print(bmodes.FWD, colored(' -> ', 'white') + colored('Error: ', 'red') + colored(res.error_info, 'white'))
    else:
        pretty_print(bmodes.FWD, ' -> Forwarded')

def command_on_message(update):
    # check if message is in update
    if not 'message' in update:
        return

    # get message from update
    message = update['message']

    msg_id = message['id']
    msg_chat_id = message['chat_id']
    msg_content = get_message_as_text(message)

    if msg_content == '.chat':
        pretty_print(bmodes.DBG, f"Chat: {colored(f'#{msg_chat_id}', 'magenta')}, Message: {colored(f'#{msg_id}', 'magenta')}")

if settings['del-edit-detector']['enable']['delete'] or s['del-edit-detector']['enable']['edit']:
    tg.add_message_handler(detector_on_message)
    tg.add_update_handler('updateDeleteMessages', detector_on_messages_delete)
    tg.add_update_handler('updateMessageEdited', on_message_edit)

if settings['forwarder']['enable']:
    tg.add_message_handler(forwarder_on_message)

tg.add_message_handler(command_on_message)
tg.idle()