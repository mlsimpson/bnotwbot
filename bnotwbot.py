#!/usr/bin/env python3

"""
bnotwbot — Slack bot for bnotw Tumblr blog + acronym game.

Setup:
  pip install slack-bolt pytumblr python-dotenv

Required environment variables:
  SLACK_BOT_TOKEN         — Bot token (xoxb-...)
  SLACK_APP_TOKEN         — App-level token for Socket Mode (xapp-...)
  TUMBLR_CONSUMER_KEY
  TUMBLR_CONSUMER_SECRET
  TUMBLR_OAUTH_TOKEN
  TUMBLR_OAUTH_SECRET

Slack app configuration (at api.slack.com/apps):
  - Enable Socket Mode
  - Add slash commands: /bnotw, /acro  (no Request URL needed)
  - Bot Token Scopes: commands, chat:write, im:history,
                      channels:history, groups:history, app_mentions:read
  - Subscribe to bot events: message.im, message.channels, message.groups,
                              app_mention
"""

import json
import os
import pytumblr
import random
import threading
from collections import defaultdict
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Config ─────────────────────────────────────────────────────────────────────

load_dotenv()

tumblr_client = pytumblr.TumblrRestClient(
    os.environ.get("TUMBLR_CONSUMER_KEY"),
    os.environ.get("TUMBLR_CONSUMER_SECRET"),
    os.environ.get("TUMBLR_OAUTH_TOKEN"),
    os.environ.get("TUMBLR_OAUTH_SECRET")
)

# ── Constants ──────────────────────────────────────────────────────────────────

BLOG_NAME = "bnotw"
LIMIT = 50

SUBMISSION_WINDOW = 60   # seconds players have to submit an acronym
VOTING_WINDOW     = 30   # seconds players have to vote
LEADERBOARD_FILE  = "acro_leaderboard.json"

# Consonant-heavy pool so acronyms feel "real"
LETTER_POOL = list("BCDFGHJKLMNPQRSTVWXYZ") * 2 + list("AEIOU")

# ── App init ───────────────────────────────────────────────────────────────────

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# ── Leaderboard helpers ────────────────────────────────────────────────────────

def load_leaderboard() -> dict:
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE) as f:
            return json.load(f)
    return {}

def save_leaderboard(lb: dict) -> None:
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(lb, f, indent=2)

def increment_score(user_id: str, display_name: str) -> None:
    lb = load_leaderboard()
    entry = lb.get(user_id, {"name": display_name, "wins": 0})
    entry["name"]  = display_name   # keep name fresh
    entry["wins"] += 1
    lb[user_id] = entry
    save_leaderboard(lb)

def leaderboard_text() -> str:
    lb = load_leaderboard()
    if not lb:
        return "No wins recorded yet."
    ranked = sorted(lb.values(), key=lambda e: e["wins"], reverse=True)
    lines  = ["*🏆 All-Time Leaderboard*"]
    for i, entry in enumerate(ranked, 1):
        lines.append(f"{i}. {entry['name']} — {entry['wins']} win(s)")
    return "\n".join(lines)

# ── Tumblr helpers ─────────────────────────────────────────────────────────────

def get_total_posts() -> int:
    """Fetch the current total post count from the Tumblr API."""
    blog_info = tumblr_client.blog_info(BLOG_NAME)
    return blog_info['blog']['total_posts']

def format_post_message(summary: str, post_id: int, date: str) -> dict:
    """Format a Tumblr post as a Slack block message."""
    return {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"bnotw: {summary}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<https://bnotw.tumblr.com/{post_id}|view on bnotw.tumblr.com> • {date}"
                    }
                ]
            }
        ]
    }

def fetch_random_post() -> tuple | None:
    """Pick a random post via the API without loading all posts into memory."""
    total = get_total_posts()
    if total == 0:
        return None
    offset = random.randint(0, total - 1)
    posts = tumblr_client.posts(BLOG_NAME, limit=1, offset=offset).get('posts', [])
    if not posts:
        return None
    p = posts[0]
    return (p['summary'], p['id'], p['date'])

def search_posts(query: str):
    """Paginate through Tumblr posts and yield those matching the query."""
    offset = 0
    while True:
        batch = tumblr_client.posts(BLOG_NAME, limit=LIMIT, offset=offset).get('posts', [])
        if not batch:
            break
        for p in batch:
            if query.casefold() in p['summary'].casefold():
                yield (p['summary'], p['id'], p['date'])
        if len(batch) < LIMIT:
            break
        offset += LIMIT

# ── Acro game state ────────────────────────────────────────────────────────────

class GameState:
    """A single shared instance guards against concurrent games."""

    def __init__(self):
        self.lock       = threading.Lock()
        self.active     = False     # True while a game is running
        self.phase      = None      # "submission" | "voting"
        self.channel    = None
        self.acronym    = ""
        # {user_id: {"name": str, "text": str}}
        self.submissions: dict = {}
        # ordered list of user_ids built when voting opens
        self.submission_order: list = []
        # {user_id: voted_index}  (1-based)
        self.votes: dict = {}
        self._timer: threading.Timer | None = None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def reset(self):
        self._cancel_timer()
        self.active     = False
        self.phase      = None
        self.channel    = None
        self.acronym    = ""
        self.submissions.clear()
        self.submission_order.clear()
        self.votes.clear()

    # ── game flow ─────────────────────────────────────────────────────────────

    def start(self, channel: str) -> bool:
        """Returns False if a game is already running."""
        with self.lock:
            if self.active:
                return False
            self.active  = True
            self.phase   = "submission"
            self.channel = channel
            length       = random.randint(3, 5)
            self.acronym = "".join(random.choices(LETTER_POOL, k=length))
            return True

    def add_submission(self, user_id: str, name: str, text: str) -> str:
        """Returns 'ok', 'duplicate', or 'wrong_phase'."""
        with self.lock:
            if self.phase != "submission":
                return "wrong_phase"
            if user_id in self.submissions:
                return "duplicate"
            self.submissions[user_id] = {"name": name, "text": text}
            return "ok"

    def open_voting(self) -> list:
        """Shuffle submissions and return ordered list for display."""
        with self.lock:
            order = list(self.submissions.keys())
            random.shuffle(order)
            self.submission_order = order
            self.phase = "voting"
            return order

    def add_vote(self, user_id: str, choice: int) -> str:
        """Returns 'ok', 'wrong_phase', 'already_voted', 'out_of_range',
           or 'own_submission'."""
        with self.lock:
            if self.phase != "voting":
                return "wrong_phase"
            if user_id in self.votes:
                return "already_voted"
            if choice < 1 or choice > len(self.submission_order):
                return "out_of_range"
            voted_for = self.submission_order[choice - 1]
            if voted_for == user_id:
                return "own_submission"
            self.votes[user_id] = choice
            return "ok"

    def tally_winner(self):
        """Returns (winner_user_id, winner_name, acronym_text, vote_count)
           or None if no votes were cast."""
        tally = defaultdict(int)
        for choice in self.votes.values():
            uid = self.submission_order[choice - 1]
            tally[uid] += 1
        if not tally:
            return None
        winner_id   = max(tally, key=tally.__getitem__)
        winner_info = self.submissions[winner_id]
        return (winner_id,
                winner_info["name"],
                winner_info["text"],
                tally[winner_id])


game = GameState()

# ── Slack helpers ──────────────────────────────────────────────────────────────

def post(channel: str, text: str) -> None:
    app.client.chat_postMessage(channel=channel, text=text)

def get_display_name(user_id: str) -> str:
    try:
        info = app.client.users_info(user=user_id)
        profile = info["user"]["profile"]
        return profile.get("display_name") or profile.get("real_name") or user_id
    except Exception:
        return user_id

# ── Timer callbacks ────────────────────────────────────────────────────────────

def end_submission_phase():
    channel = game.channel

    if not game.submissions:
        post(channel, "⏰ Time's up! No one submitted anything. Game over.")
        game.reset()
        return

    order = game.open_voting()

    lines = [f"⏰ *Time's up!* Here are the submissions for *{game.acronym}*:\n"]
    for i, uid in enumerate(order, 1):
        lines.append(f"  *{i}.* {game.submissions[uid]['text']}")
    lines.append(f"\nYou have *{VOTING_WINDOW} seconds* to vote! "
                 "Reply with the *number* of your favourite entry.\n"
                 "_(You cannot vote for your own submission.)_")
    post(channel, "\n".join(lines))

    with game.lock:
        game._timer = threading.Timer(VOTING_WINDOW, end_voting_phase)
        game._timer.start()


def end_voting_phase():
    channel = game.channel
    result  = game.tally_winner()

    if result is None:
        post(channel, "⏰ Voting closed — no votes were cast. No winner this round!")
    else:
        winner_id, winner_name, acronym_text, count = result
        increment_score(winner_id, winner_name)
        post(channel,
             f"🎉 *And the winner is… {winner_name}!*\n"
             f"Their entry for *{game.acronym}*:\n> {acronym_text}\n"
             f"_{count} vote(s)_\n\n{leaderboard_text()}")

    game.reset()

# ── Slash command: /acro ───────────────────────────────────────────────────────

@app.command("/acro")
def handle_acro(ack, command, say):
    ack()
    channel = command["channel_id"]

    started = game.start(channel)
    if not started:
        say("⚠️ A game is already in progress! Wait for it to finish.")
        return

    say(f"🎮 *The game has begun!*\n\n"
        f"Create an acronym for: *{game.acronym}*\n\n"
        f"You have *{SUBMISSION_WINDOW} seconds* to submit your entry by "
        f"*sending the bot a direct message*. Each word must start with the "
        f"letters above, in order. Your submission is secret until time's up!")

    with game.lock:
        game._timer = threading.Timer(SUBMISSION_WINDOW, end_submission_phase)
        game._timer.start()

# ── Message handler ────────────────────────────────────────────────────────────

def is_dm(message: dict) -> bool:
    """Returns True if the message arrived in a DM (im) channel."""
    return message.get("channel_type") == "im"

@app.message("")
def handle_message(message, say):
    # Ignore bot messages and edits
    if message.get("bot_id") or message.get("subtype"):
        return

    user_id = message.get("user")
    text    = message.get("text", "").strip()
    channel = message.get("channel")

    if not user_id or not text or not game.active:
        return

    phase           = game.phase
    in_dm           = is_dm(message)
    in_game_channel = (channel == game.channel)

    # ── Submission phase — only accept DMs ───────────────────────────────────
    if phase == "submission":
        if not in_dm:
            return  # silently ignore channel messages during submission

        words    = text.split()
        initials = "".join(w[0].upper() for w in words if w)
        if initials != game.acronym:
            say(f"❌ Your submission doesn't match *{game.acronym}* "
                f"(got initials: *{initials}*). Try again!")
            return

        name   = get_display_name(user_id)
        status = game.add_submission(user_id, name, text)
        if status == "ok":
            say("✅ Got it! Your entry has been recorded secretly. Good luck!")
        elif status == "duplicate":
            say("You've already submitted an entry for this round.")

    # ── Voting phase — only accept messages in the game channel ──────────────
    elif phase == "voting":
        if not in_game_channel:
            if in_dm:
                say("Voting happens in the channel — head there to cast your vote!")
            return

        try:
            choice = int(text)
        except ValueError:
            return   # ignore non-numeric messages silently

        status = game.add_vote(user_id, choice)
        if status == "ok":
            say(f"<@{user_id}> 🗳️ Vote recorded!")
        elif status == "already_voted":
            say(f"<@{user_id}> You've already voted this round.")
        elif status == "out_of_range":
            say(f"<@{user_id}> Please vote with a number between 1 and "
                f"{len(game.submission_order)}.")
        elif status == "own_submission":
            say(f"<@{user_id}> You can't vote for your own submission! 😄")

# ── Slash command: /bnotw ──────────────────────────────────────────────────────

HELP_TEXT = (
    "hot damn!\n\n"
    "`/bnotw add <text>` — add a new bnotw. make it count!\n"
    "`/bnotw random` — get a random bnotw\n"
    "`/bnotw search <query>` — search for matching bnotws\n"
    "`/bnotw help` — show this message\n"
    "`/acro` — start a game of Acronyms Against Humanity"
)

def bnotw_add(user_id: str, text: str, say, error_fn):
    if not text:
        error_fn("please provide a bnotw (`/bnotw add <text>`)")
        return
    try:
        response  = tumblr_client.create_text(BLOG_NAME, state="published", title=text)
        post_data = tumblr_client.posts(BLOG_NAME, id=response['id'])['posts'][0]
        post_url  = f"https://bnotw.tumblr.com/{post_data['id']}"
        say({
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<@{user_id}> added '<{post_url}|{text}>'"
                    }
                }
            ]
        })
    except Exception as e:
        error_fn(f"error posting bnotw: {str(e)}")

def bnotw_random(say, error_fn):
    try:
        p = fetch_random_post()
        if not p:
            error_fn("no posts found.")
            return
        say(format_post_message(*p))
    except Exception as e:
        error_fn(f"error fetching posts: {str(e)}")

def bnotw_search(query: str, say, error_fn):
    if len(query) < 3:
        error_fn("please add a search string 3 or more characters long")
        return
    try:
        found = False
        for match in search_posts(query):
            say(format_post_message(*match))
            found = True
        if not found:
            say("no matching bnotws")
    except Exception as e:
        error_fn(f"error fetching posts: {str(e)}")

def dispatch_bnotw(args: str, user_id: str, say, error_fn):
    """Parse and route a bnotw subcommand from either a slash command or mention."""
    parts      = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    arg        = parts[1].strip() if len(parts) > 1 else ""

    if subcommand == "add":
        bnotw_add(user_id, arg, say, error_fn)
    elif subcommand == "random":
        bnotw_random(say, error_fn)
    elif subcommand == "search":
        bnotw_search(arg, say, error_fn)
    elif subcommand in ("help", ""):
        error_fn(HELP_TEXT)
    else:
        error_fn(f"unknown subcommand `{subcommand}`.\n\n{HELP_TEXT}")

@app.command("/bnotw")
def handle_bnotw(ack, command, say, respond):
    ack()
    # respond() sends an ephemeral reply visible only to the caller;
    # used here so that errors and help text don't clutter the channel.
    dispatch_bnotw(command['text'], command['user_id'], say, respond)

# ── Mention handler ────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say):
    # Strip the leading @mention token to get the subcommand args
    text  = event.get('text', '')
    parts = text.split(None, 1)
    args  = parts[1].strip() if len(parts) > 1 else ""
    # Mentions have no response URL, so say() is used for both output and errors
    dispatch_bnotw(args, event['user'], say, say)

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    print("bnotwbot is alive!")
    handler.start()

