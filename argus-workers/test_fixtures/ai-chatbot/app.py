"""Flask test fixture for AI/LLM surface detection.

Simulates a web application with:
  - Intercom-style chatbot widget embedded in the homepage HTML
  - /api/chat endpoint (AI chat API)
  - /api/v1/completions endpoint (OpenAI-compatible completions API)
  - Response headers mimicking an LLM provider
  - /health endpoint for test infrastructure

This fixture is intentionally minimal — just enough surface area for the
ai_surface_detector to detect AI components and trigger advisory findings.
"""

from flask import Flask, jsonify, request

app = Flask(__name__)

# HTML with Intercom-style chatbot widget script tag
HOMEPAGE_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>AI Chat Support</title>
  <script>
    // Intercom-style widget initialization
    window.intercomSettings = {
      app_id: "abc123",
      api_base: "https://api-iam.intercom.io",
    };
  </script>
  <script src="https://widget.intercom.io/widget/abc123"></script>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <h1>Welcome to our AI-powered support</h1>
  <p>Get instant help from our intelligent chatbot.</p>
  <div id="chat-widget" data-provider="intercom"></div>
  <script>
    // Additional chatbot configuration
    Intercom("boot", { app_id: "abc123" });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    """Serve homepage with embedded Intercom chatbot widget HTML."""
    return HOMEPAGE_HTML, 200, {"Content-Type": "text/html"}


@app.route("/health")
def health():
    """Health check endpoint for test fixture infrastructure."""
    return "ok", 200, {"Content-Type": "text/plain"}


@app.route("/api/chat")
def api_chat():
    """AI chat API endpoint — returns mock streaming-like response.

    This endpoint mimics a basic LLM chat completion API.
    """
    message = request.args.get("message", "Hello")
    return jsonify({
        "response": f"You said: {message}",
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    })


@app.route("/api/v1/completions", methods=["POST"])
def completions():
    """OpenAI-compatible completions endpoint — returns mock LLM response."""
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    return jsonify({
        "id": "cmpl-mock123",
        "object": "text_completion",
        "choices": [{"text": f"Mock completion for: {prompt}", "index": 0}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app.run(host="127.0.0.1", port=port)
