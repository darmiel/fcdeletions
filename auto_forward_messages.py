from telegram.client import Telegram
from ah_settings import settings

s = settings['forwarder']

# initialize telegram client
tg = Telegram(
    settings['telegram']['api-key'],
    settings['telegram']['api-hash'],
    database_encryption_key=settings['telegram']['database-encryption-key'],
    phone=settings['telegram']['phone']
)

# login to telegram,
# you may have to input a 2fa-key
tg.login()

"""
This method is called when a new message is sent to the client.
"""
def new_message_handler(update):
    
    # check if message is in update
    if not 'message' in update:
        return

    # get message from update
    message = update['message']

    # get meta data from message
    msg_id = message['id']
    msg_chat_id = message['chat_id']
    msg_forward_ability = message['can_be_forwarded']
    msg_date = message['date']
    
    msg_content = "n/a"
    if 'content' in message:
        content = message['content']
        if 'text' in content:
            msg_content = content['text']['text']

        # if the message contains an image,
        # the content is in the caption section
        if 'caption' in content:
            msg_content = content['caption']['text']

    # check if this message is from ah's channel
    if msg_chat_id != s['chat-pull']:
        return

    print(message)

    # check if we can forward this message
    if not msg_forward_ability:
        print(f"[!] Found message, but can't forward message #{msg_id} ('{msg_content}')")
        return

    print(f"[D] '{msg_content}' at {msg_date}'")

    # call forwarding
    tg.call_method("forwardMessages", params={
        'chat_id': s['chat-publish'],
        'from_chat_id': msg_chat_id,
        'message_ids': [msg_id],
        'options': {},
        'as_album': False,
        'send_copy': False,
        'remove_caption': False
    })

    print("[D] -> Forwarding")

tg.add_message_handler(new_message_handler)
tg.idle()