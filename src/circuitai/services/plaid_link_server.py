"""Localhost HTTP server for the Plaid Link browser-based OAuth flow."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from circuitai.core.exceptions import AdapterError

_LINK_HTML = """<!DOCTYPE html>
<html>
<head><title>CircuitAI — Connect Bank</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; display: flex;
         justify-content: center; align-items: center; height: 100vh;
         margin: 0; background: #0a0a1a; color: #e0e0e0; }
  .container { text-align: center; max-width: 420px; }
  h1 { color: #6ee7b7; }
  p { color: #a0a0b0; }
  #status { margin-top: 24px; font-size: 1.1em; }
  .error { color: #f87171; }
</style>
</head>
<body>
<div class="container">
  <h1>CircuitAI</h1>
  <p>Connecting to your bank&hellip;</p>
  <div id="status">Loading Plaid Link&hellip;</div>
</div>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
  const handler = Plaid.create({
    token: '{{LINK_TOKEN}}',
    onSuccess: function(public_token, metadata) {
      document.getElementById('status').textContent = 'Connected! You can close this tab.';
      fetch('/plaid-callback?public_token=' + encodeURIComponent(public_token)
            + '&metadata=' + encodeURIComponent(JSON.stringify(metadata)))
        .then(function() { window.close(); });
    },
    onExit: function(err, metadata) {
      if (err) {
        document.getElementById('status').innerHTML =
          '<span class="error">Error: ' + err.display_message + '</span>';
      } else {
        document.getElementById('status').textContent = 'Cancelled. You can close this tab.';
      }
      fetch('/plaid-callback?cancelled=1');
    },
    onLoad: function() {
      handler.open();
    },
  });
</script>
</body>
</html>"""


def run_link_flow(link_token: str, port: int = 8765) -> dict[str, Any]:
    """Start a localhost server, open the browser for Plaid Link, and return the result.

    Returns a dict with ``public_token`` and ``metadata`` on success.
    Raises ``AdapterError`` if the user cancels or an error occurs.
    """
    result: dict[str, Any] = {}

    class LinkHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)

            if parsed.path == "/plaid-callback":
                qs = parse_qs(parsed.query)
                if "cancelled" in qs:
                    result["cancelled"] = True
                else:
                    result["public_token"] = qs.get("public_token", [""])[0]
                    meta_raw = qs.get("metadata", ["{}"])[0]
                    try:
                        result["metadata"] = json.loads(meta_raw)
                    except json.JSONDecodeError:
                        result["metadata"] = {}
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"ok")
                # Shut down in a daemon thread so we don't deadlock
                threading.Thread(target=server.shutdown, daemon=True).start()
                return

            # Serve the Link HTML page
            html = _LINK_HTML.replace("{{LINK_TOKEN}}", link_token)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        def log_message(self, format: str, *args: Any) -> None:
            # Suppress request logs
            pass

    server = HTTPServer(("127.0.0.1", port), LinkHandler)
    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)
    server.serve_forever()

    if result.get("cancelled"):
        raise AdapterError("Plaid Link flow was cancelled by the user.")
    if not result.get("public_token"):
        raise AdapterError("No public token received from Plaid Link.")

    return result
