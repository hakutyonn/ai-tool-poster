#!/usr/bin/env python3
"""
ai_tool_poster.py

This script assembles a short post introducing a new AI tool and optionally
generates a simple promotional image. It is designed to be run on a
schedule (for example via GitHub Actions) and to publish the resulting
message to X (formerly Twitter) using the v2 API.

The primary goal of this script is to provide a completely free solution.
Therefore it avoids relying on paid generative models and instead uses
predefined tool metadata from a CSV file and the Pillow library to
construct a simple card image. The script will:

1. Read a list of AI tools from ``ai_tools.csv``. Each row should contain:
   ``name``, ``tagline``, ``description`` and ``url``.
2. Select the next tool to publish. By default it simply pops the first
   entry; you can customise this selection logic.
3. Compose a message that fits within the 140‑character limit imposed by
   X. If the combined content would exceed the limit, the description is
   truncated with an ellipsis.
4. Generate a 1200×675 pixel promotional card using Pillow. The card
   displays the tool name, tagline and URL on a light background.
5. Attempt to post the message (with image attached) to X using the
   v2 ``media/upload`` and ``tweets`` endpoints. You must supply the
   required API credentials via environment variables.

To run locally:

    pip install pillow requests requests-oauthlib
    export TWITTER_API_KEY=...      # from developer portal
    export TWITTER_API_SECRET=...
    export TWITTER_ACCESS_TOKEN=...
    export TWITTER_ACCESS_SECRET=...
    python ai_tool_poster.py

When deploying via GitHub Actions, store these credentials as
repository secrets and rely on the provided workflow to expose them to
the script.

"""

import csv
import datetime
import os
import textwrap
from typing import Dict, List

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("Pillow is required for image generation. Install with 'pip install pillow'.") from exc

try:
    import requests
except ImportError as exc:
    raise SystemExit("The requests library is required to post to X. Install with 'pip install requests'.") from exc

# We'll also need OAuth1 for authentication
try:
    from requests_oauthlib import OAuth1
except ImportError as exc:
    raise SystemExit("requests-oauthlib is required to authenticate with X. Install with 'pip install requests-oauthlib'.") from exc

CSV_FILENAME = os.getenv("AI_TOOL_CSV", "ai_tools.csv")


def read_ai_tools(csv_path: str) -> List[Dict[str, str]]:
    """Read a CSV file of AI tools and return a list of dictionaries."""
    tools: List[Dict[str, str]] = []
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Cannot find tools list: {csv_path}")
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if not row.get("name"):
                continue
            tools.append(row)
    if not tools:
        raise ValueError("No tools found in CSV file")
    return tools


def select_next_tool(tools: List[Dict[str, str]]) -> Dict[str, str]:
    """Select the next tool to post. Currently returns the first item."""
    return tools[0]


def compose_post(tool: Dict[str, str]) -> str:
    """Compose a tweet-style post within 140 characters from tool metadata."""
    template = "🆕{name}：{tagline}。{short_desc} 詳しくはこちら 👉 {url} #AI #AIツール"
    name = tool.get("name", "")
    tagline = tool.get("tagline", "")
    description = tool.get("description", "")
    url = tool.get("url", "")

    # Compute available space for description
    static_text = f"🆕{name}：{tagline}。 詳しくはこちら 👉 {url} #AI #AIツール"
    static_length = len(static_text)
    max_total_length = 140
    available_for_desc = max_total_length - static_length
    short_desc = description.strip()
    if available_for_desc > 0:
        if len(short_desc) > available_for_desc:
            short_desc = textwrap.shorten(short_desc, width=available_for_desc, placeholder="…")
    else:
        short_desc = ""
    return template.format(name=name, tagline=tagline, short_desc=short_desc, url=url)


def generate_image(tool: Dict[str, str], output_path: str) -> None:
    """Generate a simple promotional card for the tool."""
    width, height = 1200, 675
    bg_color = (255, 255, 255)
    text_color = (30, 30, 30)

    image = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(image)

    # Attempt to load a custom font if provided
    font_path = os.getenv("AI_TOOL_FONT")
    try:
        if font_path and os.path.exists(font_path):
            title_font = ImageFont.truetype(font_path, size=60)
            subtitle_font = ImageFont.truetype(font_path, size=36)
            url_font = ImageFont.truetype(font_path, size=28)
        else:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            url_font = ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        url_font = ImageFont.load_default()

    name = tool.get("name", "")
    tagline = tool.get("tagline", "")
    url = tool.get("url", "")

    def center_draw(text: str, font, y: int):
        w, h = draw.textsize(text, font=font)
        x = (width - w) // 2
        draw.text((x, y), text, fill=text_color, font=font)

    center_draw(name, title_font, int(height * 0.25))
    center_draw(tagline, subtitle_font, int(height * 0.45))
    center_draw(url, url_font, int(height * 0.65))

    image.save(output_path)


def post_to_x(status_text: str, image_path: str) -> None:
    """Post the status and image to X via the v2 API.

    This uses OAuth1 authentication. Provide credentials through env vars.
    If any credential is missing, the tweet is not posted; instead the
    composed status is printed to stdout and the image path is displayed.
    """
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        print("Missing Twitter API credentials. Printing instead:")
        print(status_text)
        print(f"(Image saved to {image_path})")
        return

    oauth = OAuth1(api_key, api_secret, access_token, access_secret)

    # Upload media
    with open(image_path, 'rb') as f:
        files = {'media': f}
        upload_url = "https://upload.twitter.com/1.1/media/upload.json"
        upload_resp = requests.post(upload_url, auth=oauth, files=files)
        upload_resp.raise_for_status()
        media_id = upload_resp.json().get('media_id_string')

    # Create tweet
    tweet_url = "https://api.twitter.com/2/tweets"
    payload = {
        "text": status_text,
        "media": {"media_ids": [media_id]},
    }
    headers = {'Content-Type': 'application/json'}
    resp = requests.post(tweet_url, auth=oauth, json=payload, headers=headers)
    if resp.status_code >= 400:
        print(f"Failed to post tweet: {resp.status_code} {resp.text}")
    else:
        print(f"Posted tweet successfully: {resp.json()}")


def main():
    tools = read_ai_tools(CSV_FILENAME)
    tool = select_next_tool(tools)
    status = compose_post(tool)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    image_filename = f"ai_tool_card_{timestamp}.png"
    generate_image(tool, image_filename)
    post_to_x(status, image_filename)


if __name__ == '__main__':
    main()
