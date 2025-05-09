from modelcontextprotocol import FastMCPServer
import json

class CodeSageMCPServer(FastMCPServer):
    async def get_diff(self, pr_number: str) -> str:
        # get diff from github api (example)
        diff = (
            "diff --git a/file.py b/file.py\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1 +1 @@\n"
            "- print('Hello')\n"
            "+ print('Hello, World!')"
        )
        return diff

server = CodeSageMCPServer()
server.register_resource("get_diff", server.get_diff)
server.run(host="localhost", port=8000) 