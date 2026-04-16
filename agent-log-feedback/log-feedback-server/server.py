#!/usr/bin/env python3
"""
Slack slash command server for /log-feedback.
Receives the Slack webhook, constructs the thread URL, and opens
a new Terminal window running: claude "/log-feedback <thread_url>"
"""

import json
import subprocess
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

PORT = int(os.environ.get("PORT", 3000))


def build_thread_url(team_domain, channel_id, thread_ts):
    ts_clean = thread_ts.replace(".", "")
    return f"https://{team_domain}.slack.com/archives/{channel_id}/p{ts_clean}"


def open_claude(thread_url):
    """Open a new Terminal window running claude with the log-feedback skill."""
    # Escape any quotes in the URL (shouldn't happen, but safety first)
    safe_url = thread_url.replace('"', '\\"')
    cmd = f'claude "/log-feedback {safe_url}"'

    # Try iTerm2 first, fall back to Terminal.app
    iterm_script = f'''
        tell application "iTerm2"
            create window with default profile
            tell current session of current window
                write text "{cmd}"
            end tell
        end tell
    '''
    terminal_script = f'''
        tell application "Terminal"
            do script "{cmd}"
            activate
        end tell
    '''

    # Check if iTerm2 is running or installed
    iterm_check = subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "iTerm2"'],
        capture_output=True, text=True
    )
    use_iterm = iterm_check.stdout.strip() == "true"

    script = iterm_script if use_iterm else terminal_script
    subprocess.Popen(["osascript", "-e", script])


class SlackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{self.address_string()}] {format % args}")

    def do_POST(self):
        if self.path != "/log-feedback":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        params = parse_qs(body)

        def get(key):
            vals = params.get(key, [])
            return vals[0] if vals else ""

        team_domain = get("team_domain")
        channel_id = get("channel_id")
        thread_ts = get("thread_ts")
        text = get("text").strip()

        # Determine the thread URL
        if thread_ts:
            thread_url = build_thread_url(team_domain, channel_id, thread_ts)
        elif text.startswith("https://"):
            thread_url = text
        else:
            self._respond({
                "response_type": "ephemeral",
                "text": ":warning: Use `/log-feedback` inside a thread, or pass a Slack thread URL directly.\n"
                        "Example: `/log-feedback https://yourworkspace.slack.com/archives/C.../p...`"
            })
            return

        print(f"  Thread URL: {thread_url}")
        open_claude(thread_url)

        self._respond({
            "response_type": "ephemeral",
            "text": f":white_check_mark: Opening log-feedback for thread...\n`{thread_url}`"
        })

    def _respond(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), SlackHandler)
    print(f"log-feedback server running on port {PORT}")
    print(f"Waiting for Slack webhooks at POST /log-feedback")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
