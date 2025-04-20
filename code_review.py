import os
import requests
import re
from openai import OpenAI
import json
import time

# 환경 변수
repo = os.getenv('GITHUB_REPOSITORY')
pr_number = os.getenv('GITHUB_REF').split('/')[-2]
github_token = os.getenv('GITHUB_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

# 봇 식별자 - 리뷰에 추가될 태그
BOT_SIGNATURE = "<!-- auto-review-bot -->"

# 디버그 모드 - 자세한 로깅을 위한 설정
DEBUG_MODE = True

# GitHub API 헤더
github_headers = {
    'Authorization': f'Bearer {github_token}',
    'Accept': 'application/vnd.github.v3+json'
}

# 로깅 함수
def log_info(message):
    print(f"INFO: {message}")

def log_debug(message):
    if DEBUG_MODE:
        print(f"DEBUG: {message}")

def log_error(message):
    print(f"ERROR: {message}")

# PR 정보 가져오기 (commit SHA 포함)
def get_pr_info():
    pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    log_debug(f"Fetching PR info from: {pr_url}")
    
    response = requests.get(pr_url, headers=github_headers)
    if response.status_code == 200:
        pr_data = response.json()
        log_debug(f"Successfully retrieved PR info. Head SHA: {pr_data['head']['sha']}")
        return {
            'head_sha': pr_data['head']['sha'],
            'base_sha': pr_data['base']['sha']
        }
    else:
        log_error(f"Failed to get PR info (status code: {response.status_code})")
        log_debug(f"Response: {response.text}")
        return None

# diff 가져오기
def get_diff():
    diff_headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3.diff'
    }
    diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    log_debug(f"Fetching diff from: {diff_url}")
    
    response = requests.get(diff_url, headers=diff_headers)
    if response.status_code == 200:
        log_debug("Successfully retrieved diff")
        return response.text
    else:
        log_error(f"Failed to get diff (status code: {response.status_code})")
        log_debug(f"Response: {response.text}")
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
    
    # 섹션이 없는 경우 또는 파싱에 실패한 경우 대안 방법 시도
    if not issues:
        log_debug("Regular section parsing failed, trying alternative method")
        # 여기에 대안 파싱 방법 추가 가능
    
    return issues

# 이슈 요약 생성 함수
def generate_summary(issues):
    if not issues:
        return f"{BOT_SIGNATURE}\n\n# 코드 리뷰 요약\n\n코드 리뷰 완료: 이슈가 발견되지 않았습니다."
    
    issue_types = {}
    for issue in issues:
        category = issue['type'].split(' - ')[0]
        if category in issue_types:
            issue_types[category] += 1
        else:
            issue_types[category] = 1
    
    summary = f"{BOT_SIGNATURE}\n\n# 코드 리뷰 요약\n\n"
    summary += "다음과 같은 이슈가 발견되었습니다:\n\n"
    
    for category, count in issue_types.items():
        summary += f"- **{category}**: {count}개 이슈\n"
    
    summary += "\n각 이슈에 대한 상세 내용은 인라인 코멘트를 참조하세요."
    return summary

# 모든 기존 PR 코멘트 가져오기 (삭제 대상)
def get_all_comments():
    comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    log_debug(f"Fetching all PR comments from: {comments_url}")
    
    all_comments = []
    page = 1
    per_page = 100
    
    while True:
        params = {'per_page': per_page, 'page': page}
        response = requests.get(comments_url, headers=github_headers, params=params)
        
        if response.status_code != 200:
            log_error(f"Failed to get comments (status code: {response.status_code})")
            log_debug(f"Response: {response.text}")
            break
        
        comments = response.json()
        all_comments.extend(comments)
        
        if len(comments) < per_page:
            break
            
        page += 1
    
    log_info(f"Retrieved {len(all_comments)} total PR comments")
    return all_comments

# 모든 기존 PR 리뷰 가져오기 (삭제 대상)
def get_all_reviews():
    reviews_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    log_debug(f"Fetching all PR reviews from: {reviews_url}")
    
    all_reviews = []
    page = 1
    per_page = 100
    
    while True:
        params = {'per_page': per_page, 'page': page}
        response = requests.get(reviews_url, headers=github_headers, params=params)
        
        if response.status_code != 200:
            log_error(f"Failed to get reviews (status code: {response.status_code})")
            log_debug(f"Response: {response.text}")
            break
        
        reviews = response.json()
        all_reviews.extend(reviews)
        
        if len(reviews) < per_page:
            break
            
        page += 1
    
    log_info(f"Retrieved {len(all_reviews)} total PR reviews")
    return all_reviews

# 봇 코멘트인지 확인
def is_bot_comment(comment):
    return BOT_SIGNATURE in comment.get('body', '')

# 봇 코멘트 전체 삭제
def delete_all_bot_comments():
    all_comments = get_all_comments()
    log_info(f"Checking {len(all_comments)} comments for deletion")
    
    deleted_count = 0
    for comment in all_comments:
        comment_id = comment.get('id')
        if comment_id and is_bot_comment(comment):
            log_debug(f"Deleting bot comment {comment_id}")
            
            delete_url = f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"
            response = requests.delete(delete_url, headers=github_headers)
            
            if response.status_code == 204:  # 204 No Content는 성공적인 삭제를 의미
                log_info(f"Successfully deleted comment {comment_id}")
                deleted_count += 1
            else:
                log_error(f"Failed to delete comment {comment_id} (status code: {response.status_code})")
                log_debug(f"Response: {response.text}")
    
    log_info(f"Deleted {deleted_count} bot comments")
    return deleted_count

# 봇 리뷰 전체 삭제/dismiss
def dismiss_all_bot_reviews():
    all_reviews = get_all_reviews()
    log_info(f"Checking {len(all_reviews)} reviews for dismissal")
    
    dismissed_count = 0
    for review in all_reviews:
        review_id = review.get('id')
        if not review_id:
            continue
            
        # 리뷰 세부 정보 가져오기
        review_detail_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}"
        detail_response = requests.get(review_detail_url, headers=github_headers)
        
        if detail_response.status_code != 200:
            log_error(f"Failed to get review details for {review_id} (status code: {detail_response.status_code})")
            continue
            
        review_body = detail_response.json().get('body', '')
        
        # 봇 리뷰인지 확인
        if BOT_SIGNATURE in review_body:
            log_debug(f"Dismissing bot review {review_id}")
            
            dismiss_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews/{review_id}/dismissals"
            dismiss_data = {
                'message': '이전 자동 리뷰를 대체합니다.',
                'event': 'DISMISS'
            }
            
            response = requests.put(dismiss_url, headers=github_headers, json=dismiss_data)
            
            if response.status_code == 200:
                log_info(f"Successfully dismissed review {review_id}")
                dismissed_count += 1
            else:
                log_error(f"Failed to dismiss review {review_id} (status code: {response.status_code})")
                log_debug(f"Response: {response.text}")
    
    log_info(f"Dismissed {dismissed_count} bot reviews")
    return dismissed_count

# GitHub PR에 인라인 코멘트 남기기
def post_review_comments(commit_sha, issues, overall_comment):
    # 이전 봇 코멘트/리뷰 삭제
    log_info("Starting cleanup of previous bot comments and reviews")
    try:
        # 기존 봇 코멘트 모두 삭제
        deleted_comments = delete_all_bot_comments()
        log_info(f"Deleted {deleted_comments} bot comments")
        
        # 기존 봇 리뷰 모두 dismiss
        dismissed_reviews = dismiss_all_bot_reviews()
        log_info(f"Dismissed {dismissed_reviews} bot reviews")
        
        # 삭제 작업 후 약간의 대기 시간 추가 (GitHub API 반영 시간 고려)
        if deleted_comments > 0 or dismissed_reviews > 0:
            log_info("Waiting for GitHub API to process deletions...")
            time.sleep(2)
    except Exception as e:
        log_error(f"Error cleaning up previous comments/reviews: {str(e)}")
    
    # 리뷰 생성
    review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    log_debug(f"Creating review at: {review_url}")
    
    # 간략한 요약 생성
    summary = generate_summary(issues)
    
    # 인라인 코멘트 구성
    comments = []
    for issue in issues:
        if issue.get('file') and issue.get('line'):
            comment_body = f"{BOT_SIGNATURE}\n\n**{issue['type']}**\n\n"
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
    
    log_debug(f"Prepared {len(comments)} inline comments")
    
    # 리뷰 데이터 구성
    review_data = {
        'commit_id': commit_sha,
        'body': summary,  # 간략한 요약으로 변경
        'event': 'COMMENT',
        'comments': comments
    }
    
    # 인라인 코멘트가 없으면 일반 PR 코멘트로 대체
    if not comments:
        log_info("No inline comments to post, using regular PR comment instead")
        comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment_data = {'body': f"{BOT_SIGNATURE}\n\n{overall_comment}"}
        
        response = requests.post(comment_url, headers=github_headers, json=comment_data)
        log_info(f"Comment posting result: {response.status_code}")
        
        if response.status_code != 201:
            log_error(f"Failed to post comment: {response.text}")
        return
    
    # 리뷰 및 인라인 코멘트 게시
    log_debug(f"Posting review with {len(comments)} inline comments")
    response = requests.post(review_url, headers=github_headers, json=review_data)
    log_info(f"Review posting result: {response.status_code}")
    
    if response.status_code != 201:
        log_error(f"Error details: {response.text}")

# Main 실행 코드
try:
    log_info("Starting code review process")
    
    # PR 정보 및 diff 가져오기
    pr_info = get_pr_info()
    if not pr_info:
        raise Exception("Failed to get PR info")
    
    diff = get_diff()
    if not diff:
        raise Exception("Failed to get diff")
    
    log_debug(f"Review target diff:\n{diff}")
    
    # diff 파싱
    file_changes = parse_diff(diff)
    
    # OpenAI 리뷰 요청
    log_info("Requesting code review from OpenAI API")
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
    log_debug(f"OpenAI response:\n{review_comment}")
    
    # OpenAI 응답 파싱
    issues = parse_ai_response(review_comment, file_changes)
    log_info(f"Parsed {len(issues)} issues from OpenAI response")
    
    # 리뷰 코멘트 게시
    log_info("Posting review comments")
    post_review_comments(pr_info['head_sha'], issues, review_comment)
    
    log_info("Code review process completed successfully")
    
except Exception as e:
    log_error(f"Error: {str(e)}")
    
    # 오류 발생 시, 기존 방식으로 일반 코멘트 게시 (fallback)
    try:
        log_info("Attempting to post fallback comment")
        comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment_data = {'body': f"{BOT_SIGNATURE}\n\nCode review failed: {str(e)}\n\nIf available, here's the review:\n\n{review_comment if 'review_comment' in locals() else 'No review available'}"} 
        response = requests.post(comment_url, headers=github_headers, json=comment_data)
        log_info(f"Fallback comment posting result: {response.status_code}")
    except Exception as fallback_e:
        log_error(f"Fallback also failed: {str(fallback_e)}") 