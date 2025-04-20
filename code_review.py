import os
import requests
from openai import OpenAI

# 환경 변수
repo = os.getenv('GITHUB_REPOSITORY')
pr_number = os.getenv('GITHUB_REF').split('/')[-2]
github_token = os.getenv('GITHUB_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

# get diff from github api directly (or use example diff for testing)
# when actually calling GitHub API
headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3.diff'  # diff 형식으로 요청
}
try:
    # try to get diff from github api
    diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    response = requests.get(diff_url, headers=headers)
    if response.status_code == 200:
        diff = response.text
    else:
        # if failed to get diff from github api, use example diff
        print(f"Failed to get diff from github api (status code: {response.status_code}). Use example diff.")
        diff = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
- print('Hello')
+ print('Hello, World!')"""
except Exception as e:
    print(f"Error occurred: {e}. Use example diff.")
    diff = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
- print('Hello')
+ print('Hello, World!')"""

print(f"Review target diff:\n{diff}")

# OpenAI client

prompt = f"Review the following code changes and provide feedback on security, performance, and quality:\n\n{diff}"
response = openai_client.chat.completions.create(
    model="gpt-4.1",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=500
)
review_comment = response.choices[0].message.content

# post comment to github
comment_headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}
comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
comment_data = {'body': review_comment}
comment_response = requests.post(comment_url, headers=comment_headers, json=comment_data)
print(f"Comment posting result: {comment_response.status_code}") 