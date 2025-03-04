#!/usr/bin/env python

import os
import re
import random
import pytumblr
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

# setup

load_dotenv()

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

tumblr_client = pytumblr.TumblrRestClient(
    os.environ.get("TUMBLR_CONSUMER_KEY"),
    os.environ.get("TUMBLR_CONSUMER_SECRET"),
    os.environ.get("TUMBLR_OAUTH_TOKEN"),
    os.environ.get("TUMBLR_OAUTH_SECRET")
)

BLOG_NAME = "bnotw"

regexes = {"<.*?>": "", "&rsquo;": "'", "&lsquo;": "'"}

# helper functions

def multiple_replace(patterns, text):
    for pattern, replacement in patterns.items():
        text = re.sub(pattern, replacement, text)
    return text

def has_link(text):
    if re.search(r'https?://.*display_url', text):
        return True
    return False

def get_link(text):
    match = re.search(r'https?://.*display_url', text).group()
    return re.sub(r'&quot.*url', '', match)

def get_total_posts():
    """get number of total posts"""
    blog_info = tumblr_client.blog_info(BLOG_NAME)
    return blog_info['blog']['total_posts']

# commands

@app.command("/bnotw-add")
def post_to_tumblr(ack, command, say):
    """command to add a new bnotw"""
    ack()

    user_id = command['user_id']
    text = command['text']

    if not text:
        say("please provide a bnotw (`/bnotw-add new_bnotw`)")
        return

    try:
        response = tumblr_client.create_text(BLOG_NAME, state="published", title=text)

        post_url = f"https://bnotw.tumblr.com/{response['id']}"
        message = {
                "blocks":[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"<@{user_id}> added '<{post_url}|{text}>'"
                        }
                    }

                ]
        }

        say(message)

    except Exception as e:
        say(f"error posting bnotw: {str(e)}")

@app.command("/bnotw-get")
def get_random_post(ack, say):
    """command to get a random bnotw"""
    ack()

    total_posts = get_total_posts()

    try:
        random_offset = random.randint(0, total_posts - 1)
        posts = tumblr_client.posts(BLOG_NAME, limit=1, offset=random_offset)
        post = posts['posts'][0]

        if post['title']:
            content = multiple_replace(regexes, post.get('title'))
        elif post['body']:
            if has_link(post['body']):
                content = get_link(post['body'])
            else:
                content = multiple_replace(regexes, post.get('body'))
        else:
            pass

        message = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"bnotw: {content}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"<https://bnotw.tumblr.com/{post['id']}|view on bnotw.tumblr.com> • {post['date']}"
                        }
                    ]
                }
            ]
        }

        say(message)

    except Exception as e:
        say(f"error fetching posts: {str(e)}")

@app.command("/bnotw-search")
def get_searched_post(ack, command, say):
    """command to search for a bnotw"""
    ack()

    total_posts = get_total_posts()

    try:
        query = command['text']
        if not query:
            say('please add a search string')

        orig_bnotws = []
        lower_bnotws = []
        all_posts = tumblr_client.posts(BLOG_NAME, limit=total_posts)['posts']

        for post in all_posts:
            if post['title']:
                title = multiple_replace(regexes, post['title'])
                lower_bnotws.append(title.lower())
                orig_bnotws.append(title)
            elif post['body']:
                if has_link(post['body']):
                    body = get_link(post['body'])
                else:
                    body = multiple_replace(regexes, post.get('body'))
                lower_bnotws.append(body.lower())
                orig_bnotws.append(body)
            else:
                pass

        indices = [i for i, val in enumerate(lower_bnotws) if query in val]

        if indices:
            for i in indices:
                bnotw = orig_bnotws[i]
                post = all_posts[i]

                message = {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"bnotw: {bnotw}"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"<https://bnotw.tumblr.com/{post['id']}|view on bnotw.tumblr.com> • {post['date']}"
                                }
                            ]
                        }
                    ]
                }

                say(message)
        else:
            say("no matching bnotws")

    except Exception as e:
        say(f"error fetching posts: {str(e)}")

@app.event("app_mention")
def handle_mention(event, say):
    """print help to channel"""
    say("hot damn!\n`/bnotw-add [your text]` to add a new bnotw. make it count!\n`/bnotw-get` to get a random bnotw.")


if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    print("bnotwbot is alive!")
    handler.start()

