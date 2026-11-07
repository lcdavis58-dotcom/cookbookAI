"""
A conversation with the assistant that can mix asking, scaling and
matching, and follow up on what was said before.

    chat/terminal.py the terminal chat (chat.py): the loop, opening and
                     listing saved chats, answering a message left unanswered
    chat/turn.py     one turn: save her message, route it, run the action,
                     remember the result, word the reply, save again
    chat/router.py   which action a message is for and what it's about
                     (pending question, then rules, then the model)
    chat/state.py    what a chat remembers, and how each action's result
                     updates it
    chat/reply.py    the chat's wording of each result
    chat/store.py    saving chats to CHATS_DIR and loading them again
"""
