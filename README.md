# bnotwbot
slack bot for interacting with https://bno.tw

## Instructions
<<<<<<< HEAD
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

## Usage
  `/acro` — start a game of Acronyms Against Humanity

  `/bnotw add <text>` — add a new bnotw. make it count!
  `/bnotw random` — get a random bnotw
  `/bnotw search <query>` — search for matching bnotws
  `/bnotw help` — show this message

=======
1. ~~you lock the target~~ fill out `.env` with slack and tumblr api tokens
2. ~~you bait the line~~ fire up a `venv`
3. ~~you slowly spread the net, and~~ add dependencies via `requirements.txt`
4. ~~you catch tne man~~ launch `bnotwbot.py` (in the background if daemonized: `bnotwbot.py &`)
>>>>>>> d2cd6768e8eacc3b0d00c19a5e454ae41bad946d
