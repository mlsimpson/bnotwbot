# bnotwbot
bnotwbot — Slack bot for bnotw Tumblr blog + acronym game.

## Instructions
Setup:
  `pip install slack-bolt pytumblr python-dotenv`

Required environment variables:
  - SLACK_BOT_TOKEN         — Bot token (xoxb-...)
  - SLACK_APP_TOKEN         — App-level token for Socket Mode (xapp-...)
  - TUMBLR_CONSUMER_KEY
  - TUMBLR_CONSUMER_SECRET
  - TUMBLR_OAUTH_TOKEN
  - TUMBLR_OAUTH_SECRET

Slack app configuration (at [api.slack.com/apps](https://api.slack.com/apps)):
  - Enable Socket Mode
  - Add slash commands: 
      - /bnotw
      - /acro
  - Bot Token Scopes:
      - commands
      - chat:write
      - im:history
      - channels:history
      - groups:history
      - app_mentions:read
  - Subscribe to bot events:
      - message.im
      - message.channels
      - message.groups
      - app_mention

## Usage
  `/acro` — start a game of Acronyms Against Humanity

  `/bnotw add <text>` — add a new bnotw. make it count!
  `/bnotw random` — get a random bnotw
  `/bnotw search <query>` — search for matching bnotws
  `/bnotw help` — show this message

