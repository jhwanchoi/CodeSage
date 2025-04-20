import os
import requests
import re
from openai import OpenAI
import json

# 환경 변수
repo = os.getenv('GITHUB_REPOSITORY')
pr_number = os.getenv('GITHUB_REF').split('/')[-2]
github_token = os.getenv('GITHUB_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

# GitHub API 헤더
github_headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}

# PR 정보 가져오기 (commit SHA 포함)
def get_pr_info():
    pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    response = requests.get(pr_url, headers=github_headers)
    if response.status_code == 200:
        pr_data = response.json()
        return {
            'head_sha': pr_data['head']['sha'],
            'base_sha': pr_data['base']['sha']
        }
    else:
        print(f"Failed to get PR info (status code: {response.status_code})")
        return None

# diff 가져오기
def get_diff():
    diff_headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3.diff'
    }
    diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    response = requests.get(diff_url, headers=diff_headers)
    if response.status_code == 200:
        return response.text
    else:
        print(f"Failed to get diff (status code: {response.status_code})")
        return None

# diff 파싱하여 파일별 변경 라인 정보 추출
def parse_diff(diff_text):
    if not diff_text:
        return {}
    
    file_changes = {}
    current_file = None
    file_diff_lines = []
    
    # diff 텍스트를 줄 단위로 분석
    lines = diff_text.split('\n')
    for i, line in enumerate(lines):
        # 새 파일 시작 감지
        if line.startswith('diff --git'):
            # 이전 파일 정보 저장
            if current_file and file_diff_lines:
                file_changes[current_file] = analyze_file_diff(file_diff_lines)
            
            # 새 파일 이름 추출 (b/ 이후 부분)
            match = re.search(r'b/(.+)$', line)
            if match:
                current_file = match.group(1)
                file_diff_lines = []
        
        # 현재 파일의 diff 라인 수집
        if current_file:
            file_diff_lines.append(line)
    
    # 마지막 파일 정보 저장
    if current_file and file_diff_lines:
        file_changes[current_file] = analyze_file_diff(file_diff_lines)
    
    return file_changes

# 파일 diff 분석하여, 변경 위치 매핑
def analyze_file_diff(diff_lines):
    changes = {
        'added': {},   # {diff_position: original_line}
        'deleted': {}, # {diff_position: original_line}
        'changed': {}  # {diff_position: original_line}
    }
    
    in_hunk = False
    diff_position = 0
    original_line = 0
    new_line = 0
    
    for i, line in enumerate(diff_lines):
        diff_position = i + 1
        
        # 헤더 라인은 건너뛰기
        if line.startswith('diff --git') or line.startswith('index ') or line.startswith('---') or line.startswith('+++'):
            continue
        
        # 청크 헤더 파싱 (@@ -original_start,original_count +new_start,new_count @@)
        if line.startswith('@@'):
            in_hunk = True
            match = re.search(r'@@ -(\d+),\d+ \+(\d+),\d+ @@', line)
            if match:
                original_line = int(match.group(1)) - 1  # 헤더 이후 라인부터 시작
                new_line = int(match.group(2)) - 1
            continue
        
        if in_hunk:
            if line.startswith('+'):
                new_line += 1
                changes['added'][diff_position] = new_line
            elif line.startswith('-'):
                original_line += 1
                changes['deleted'][diff_position] = original_line
            else:
                original_line += 1
                new_line += 1
                changes['changed'][diff_position] = new_line
    
    return changes

# OpenAI 응답 파싱 및 이슈-파일-라인 연결
def parse_ai_response(response_text, file_changes):
    # 간단한 패턴 매칭을 통한 파일 및 라인 번호 추출
    # 더 복잡한 경우에는 더 정교한 파싱이 필요
    issues = []
    
    # 번호가 있는 아이템 찾기 (예: "1. SECURITY ISSUES")
    section_pattern = r'(\d+)\.\s*([A-Z\s]+)'
    sections = re.finditer(section_pattern, response_text)
    
    # 섹션 및 하위 항목 추출
    current_section = None
    section_starts = []
    
    for match in sections:
        section_id = match.group(1)
        section_name = match.group(2).strip()
        section_starts.append((match.start(), section_id, section_name))
    
    # 섹션 범위 설정
    section_ranges = []
    for i, (start, section_id, section_name) in enumerate(section_starts):
        end = section_starts[i+1][0] if i+1 < len(section_starts) else len(response_text)
        section_ranges.append((section_id, section_name, start, end))
    
    # 각 섹션 내 하위 항목 처리
    for section_id, section_name, start, end in section_ranges:
        section_text = response_text[start:end]
        
        # 하위 항목 패턴 (예: "(a) Unsafe use of eval")
        item_pattern = r'\([a-z]\)\s+([^\n]+)'
        items = re.finditer(item_pattern, section_text)
        
        for item_match in items:
            item_title = item_match.group(1).strip()
            item_start = item_match.start() + start
            
            # 다음 아이템 또는 섹션 끝까지의 텍스트 추출
            next_item = re.search(item_pattern, section_text[item_match.end():])
            item_end = item_match.end() + next_item.start() if next_item else end
            item_text = response_text[item_start:item_end]
            
            # 파일 및 라인 번호 추출
            file_pattern = r'File:\s+([^,\n]+)(?:,\s*lines?\s*(\d+)(?:-(\d+))?)?'
            file_match = re.search(file_pattern, item_text)
            
            file_path = None
            line_num = None
            
            if file_match:
                file_path = file_match.group(1).strip()
                if file_match.group(2):  # 라인 번호가 있는 경우
                    line_num = int(file_match.group(2))
            
            # 문제 설명 추출
            issue_pattern = r'Issue:\s*\n\n([^W]+)(?:Why:|Recommendation:)'
            issue_match = re.search(issue_pattern, item_text, re.DOTALL)
            description = item_title
            if issue_match:
                description = issue_match.group(1).strip()
            
            # 문제 이유 추출
            why_pattern = r'Why:\s*\n\n([^R]+)(?:Recommendation:)'
            why_match = re.search(why_pattern, item_text, re.DOTALL)
            why = ""
            if why_match:
                why = why_match.group(1).strip()
            
            # 권장 해결책 추출
            recommendation_pattern = r'Recommendation:\s*\n\n([\s\S]+?)(?:# Example|$)'
            rec_match = re.search(recommendation_pattern, item_text)
            recommendation = ""
            if rec_match:
                recommendation = rec_match.group(1).strip()
            
            # 예제 코드 추출
            example_pattern = r'# Example[^#]*?```(?:python)?\s*([\s\S]+?)```'
            example_match = re.search(example_pattern, item_text)
            example = ""
            if example_match:
                example = example_match.group(1).strip()
            
            issues.append({
                'type': f"{section_name} - {item_title}",
                'description': description,
                'why': why,
                'recommendation': recommendation,
                'example': example,
                'file': file_path,
                'line': line_num
            })
    
    # 파일 및 라인 번호가 없는 경우, 코드 내용 기반으로 추측
    for issue in issues:
        if not issue.get('file') or not issue.get('line'):
            # 코드 내용 기반 추측
            description = issue['description'].lower()
            for file_path, changes in file_changes.items():
                # TODO: 코드 내용 기반 라인 번호 추측 로직 개선
                pass
    
    return issues

# 이슈 요약 생성 함수
def generate_summary(issues):
    if not issues:
        return "코드 리뷰 완료: 이슈가 발견되지 않았습니다."
    
    issue_types = {}
    for issue in issues:
        category = issue['type'].split(' - ')[0]
        if category in issue_types:
            issue_types[category] += 1
        else:
            issue_types[category] = 1
    
    summary = "# 코드 리뷰 요약\n\n"
    summary += "다음과 같은 이슈가 발견되었습니다:\n\n"
    
    for category, count in issue_types.items():
        summary += f"- **{category}**: {count}개 이슈\n"
    
    summary += "\n각 이슈에 대한 상세 내용은 인라인 코멘트를 참조하세요."
    return summary

# GitHub PR에 인라인 코멘트 남기기
def post_review_comments(commit_sha, issues, overall_comment):
    # 리뷰 생성
    review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    
    # 간략한 요약 생성
    summary = generate_summary(issues)
    
    # 인라인 코멘트 구성
    comments = []
    for issue in issues:
        if issue.get('file') and issue.get('line'):
            comment_body = f"**{issue['type']}**\n\n"
            comment_body += f"{issue['description']}\n\n"
            
            if issue.get('why'):
                comment_body += f"**Why it's a problem:**\n{issue['why']}\n\n"
            
            if issue.get('recommendation'):
                comment_body += f"**Recommended Fix:**\n{issue['recommendation']}"
            
            if issue.get('example'):
                comment_body += f"\n\n**Example:**\n```python\n{issue['example']}\n```"
            
            comments.append({
                'path': issue['file'],
                'position': issue['line'],  # 정확한 position 계산이 필요할 수 있음
                'body': comment_body
            })
    
    # 리뷰 데이터 구성
    review_data = {
        'commit_id': commit_sha,
        'body': summary,  # 간략한 요약으로 변경
        'event': 'COMMENT',
        'comments': comments
    }
    
    # 인라인 코멘트가 없으면 일반 PR 코멘트로 대체
    if not comments:
        comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment_data = {'body': overall_comment}
        response = requests.post(comment_url, headers=github_headers, json=comment_data)
        print(f"Comment posting result: {response.status_code}")
        return
    
    # 리뷰 및 인라인 코멘트 게시
    response = requests.post(review_url, headers=github_headers, json=review_data)
    print(f"Review posting result: {response.status_code}")
    if response.status_code != 201:
        print(f"Error details: {response.text}")

# Main 실행 코드
try:
    # PR 정보 및 diff 가져오기
    pr_info = get_pr_info()
    if not pr_info:
        raise Exception("Failed to get PR info")
    
    diff = get_diff()
    if not diff:
        raise Exception("Failed to get diff")
    
    print(f"Review target diff:\n{diff}")
    
    # diff 파싱
    file_changes = parse_diff(diff)
    
    # OpenAI 리뷰 요청
    openai_client = OpenAI(api_key=openai_api_key)
    prompt = f"""Review the following code changes thoroughly and critically. Look for ALL possible issues including:

1. SECURITY: Identify vulnerabilities like injection risks, unsafe functions (eval, exec), authentication issues, etc.

2. PERFORMANCE: Find inefficient code patterns, unnecessary operations, memory leaks, or resource management issues.

3. LOGICAL ERRORS: Detect incorrect algorithm implementations, parameter order issues, incorrect calculations or comparisons.

4. FUNCTIONAL CORRECTNESS: Check if implementations match their descriptions (docstrings), verify return values.

5. CODE STRUCTURE: Identify redundant code, opportunities for method reuse, excessive complexity.

6. CODE QUALITY: Find unused variables, naming issues, missing error handling, or incomplete implementations.

7. SUBTLE BUGS: Look for floating-point precision issues, off-by-one errors, or other non-obvious bugs.

For each issue, please use this EXACT format:
1. [CATEGORY NAME]
(a) [Issue title]

File: [path], lines [line number(s)]

Issue:

[Clear description of the problem]

Why:

[Why this is a problem]

Recommendation:

[Specific suggestion to fix it]

# Example if needed
```python
[Example code]
```

Be thorough, but focus on quality over quantity. Each issue should have concrete details and real problems.
IMPORTANT: For each issue, specify the file and line number where the issue is found.

Here are the code changes to review:

{diff}"""
    
    response = openai_client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000  # 더 많은 토큰을 허용하여 상세한 리뷰 생성
    )
    review_comment = response.choices[0].message.content
    
    # OpenAI 응답 파싱
    issues = parse_ai_response(review_comment, file_changes)
    
    # 리뷰 코멘트 게시
    post_review_comments(pr_info['head_sha'], issues, review_comment)
    
except Exception as e:
    print(f"Error: {str(e)}")
    
    # 오류 발생 시, 기존 방식으로 일반 코멘트 게시 (fallback)
    try:
        comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment_data = {'body': f"Code review failed: {str(e)}\n\nIf available, here's the review:\n\n{review_comment if 'review_comment' in locals() else 'No review available'}"} 
        response = requests.post(comment_url, headers=github_headers, json=comment_data)
        print(f"Fallback comment posting result: {response.status_code}")
    except Exception as fallback_e:
        print(f"Fallback also failed: {str(fallback_e)}") 