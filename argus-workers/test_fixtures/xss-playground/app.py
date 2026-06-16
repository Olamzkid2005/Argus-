"""XSS Playground — intentionally vulnerable web app for XSS detection testing.

Endpoints:
  GET  /reflect?q=<text>    — Reflected XSS: input echoed unsanitized in HTML
  GET  /dom?name=<text>     — DOM-based XSS: input embedded in a script context
  GET  /stored              — Stored XSS: previous inputs rendered without escaping
  POST /stored              — Stored XSS: saves input to in-memory list
  GET  /health              — Health check

Fixture design principle: Make fixtures intentionally tiny, not realistic.
A good fixture is a single vulnerable endpoint in ~30 lines. The purpose is
regression detection, not vulnerability training.
"""

from flask import Flask, request

app = Flask(__name__)

# In-memory "database" for stored XSS
_stored_comments: list[str] = []


@app.route("/reflect")
def reflect():
    """Reflected XSS — user input echoed directly into HTML without escaping.

    This is the most common XSS pattern. Tools like dalfox, nuclei, and
    custom scanners should detect this immediately.
    """
    q = request.args.get("q", "")
    # Intentionally vulnerable — raw string interpolation in HTML
    return f"""<!DOCTYPE html>
<html>
<head><title>Search Results</title></head>
<body>
  <h1>Search Results</h1>
  <p>You searched for: {q}</p>
</body>
</html>"""


@app.route("/dom")
def dom():
    """DOM-based XSS — input embedded unsanitized inside a <script> block.

    The name parameter is placed directly into a JavaScript string literal
    without escaping. A closing </script> or quote breakout can execute
    arbitrary JS.
    """
    name = request.args.get("name", "Guest")
    # Intentionally vulnerable — raw interpolation in JS context
    return f"""<!DOCTYPE html>
<html>
<head><title>Welcome</title></head>
<body>
  <h1>Welcome</h1>
  <script>
    var userName = "{name}";
    document.write("Hello, " + userName);
  </script>
</body>
</html>"""


@app.route("/stored", methods=["GET", "POST"])
def stored():
    """Stored XSS — input saved and rendered without escaping on subsequent GET.

    POST saves a comment to an in-memory list. GET renders all saved comments
    without HTML escaping. This exercises persistent XSS detection.
    """
    if request.method == "POST":
        comment = request.form.get("comment", "")
        if comment:
            _stored_comments.append(comment)
        return "Comment saved", 201

    # Intentionally vulnerable — comments rendered without escaping
    comments_html = ""
    for c in _stored_comments:
        comments_html += f"<div class='comment'>{c}</div>"

    return f"""<!DOCTYPE html>
<html>
<head><title>Comments</title></head>
<body>
  <h1>Guestbook</h1>
  {comments_html or "<p>No comments yet.</p>"}
  <form method="POST">
    <input name="comment" placeholder="Leave a comment">
    <button type="submit">Submit</button>
  </form>
</body>
</html>"""


@app.route("/health")
def health():
    """Health check endpoint used by test fixtures to confirm the app is up."""
    return "ok"


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app.run(host="127.0.0.1", port=port)
