import os
import requests
from openai import OpenAI

# 환경 변수
repo = os.getenv('GITHUB_REPOSITORY')
pr_number = os.getenv('GITHUB_REF').split('/')[-2]
github_token = os.getenv('GITHUB_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

# Github API로 직접 diff 가져오기 (또는 테스트용 하드코딩 diff)
# 실제 GitHub API 호출 시
headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3.diff'  # diff 형식으로 요청
}
try:
    # GitHub API로 PR diff 가져오기 시도
    diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    response = requests.get(diff_url, headers=headers)
    if response.status_code == 200:
        diff = response.text
    else:
        # API 호출에 실패하면 테스트용 예시 diff 사용
        print(f"GitHub API 호출 실패 (상태 코드: {response.status_code}). 예시 diff 사용.")
        diff = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
- print('Hello')
+ print('Hello, World!')"""
except Exception as e:
    print(f"오류 발생: {e}. 예시 diff 사용.")
    diff = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
- print('Hello')
+ print('Hello, World!')"""

print(f"리뷰 대상 diff:\n{diff}")

# OpenAI 클라이언트
openai_client = OpenAI(api_key=openai_api_key)
prompt = f"다음 코드 변경 사항을 검토하고 보안, 성능, 품질 측면에서 피드백을 제공하세요:\n\n{diff}"
response = openai_client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=500
)
review_comment = response.choices[0].message.content

# GitHub 코멘트 게시
comment_headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}
comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
comment_data = {'body': review_comment}
comment_response = requests.post(comment_url, headers=comment_headers, json=comment_data)
print(f"코멘트 게시 결과: {comment_response.status_code}") 