import os
import requests
from openai import OpenAI
from modelcontextprotocol import MCPClient

# 환경 변수
repo = os.getenv('GITHUB_REPOSITORY')
pr_number = os.getenv('GITHUB_REF').split('/')[-2]
github_token = os.getenv('GITHUB_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

# MCP 클라이언트
client = MCPClient("http://localhost:8000")
diff = client.call_resource("get_diff", pr_number)

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
headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}
comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
comment_data = {'body': review_comment}
requests.post(comment_url, headers=headers, json=comment_data) 