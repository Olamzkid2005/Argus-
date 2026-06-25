"""MCP server that crashes immediately on startup.

Used to test the reconnection path when the worker process dies
before sending any valid response. The server exits with code 1
to simulate a crash.
"""

import sys

if __name__ == "__main__":
    sys.stderr.write("MCP crash server: exiting immediately with code 1\n")
    sys.exit(1)
