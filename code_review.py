import os
import requests
import re
from openai import OpenAI
import json
import time

# 환경 변수
repo = os.getenv('GITHUB_REPOSITORY')
pr_number = os.getenv('GITHUB_REF', '').split('/')[-2] if os.getenv('GITHUB_REF') else None

# PR 번호가 없으면 직접 설정 (로컬 테스트용)
if not pr_number or not pr_number.isdigit():
    pr_number = "9"  # 실제 PR 번호로 변경하세요
    
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

# GitHub API 토큰 검증
def validate_github_token():
    test_url = f"https://api.github.com/repos/{repo}"
    log_debug(f"Validating GitHub token with test request to: {test_url}")
    
    response = requests.get(test_url, headers=github_headers)
    if response.status_code == 200:
        log_info("GitHub token is valid")
        return True
    else:
        log_error(f"GitHub token validation failed (status code: {response.status_code})")
        log_debug(f"Response: {response.text}")
        return False

# PR 정보 가져오기 (commit SHA 포함)
def get_pr_info():
    log_info(f"Working with repository: {repo}")
    log_info(f"Working with PR number: {pr_number}")
    
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
    issues = []
    
    # 패턴: 파일 및 라인 정보 추출
    file_line_pattern = r'(?:파일|File):\s*([^,\n]+)(?:,\s*(?:라인|Line):\s*(\d+))?'
    type_pattern = r'(?:유형|Type):\s*([^\n]+)'
    issue_pattern = r'(?:이슈|Issue):\s*([^\n]+)'
    fix_pattern = r'(?:해결|Fix):\s*([^\n]+)'
    
    log_debug(f"Starting to parse response text of length: {len(response_text)}")
    
    # 모든 이슈 항목 찾기 (- 또는 숫자로 시작하는 항목)
    issue_blocks = re.split(r'\n(?=-|\d+\.|\*)\s*', response_text)
    log_debug(f"Found {len(issue_blocks)} issue blocks")
    
    for i, block in enumerate(issue_blocks):
        if not block.strip():
            continue
            
        log_debug(f"Processing issue block {i+1}: {block[:100]}...")
        
        file_match = re.search(file_line_pattern, block, re.IGNORECASE)
        type_match = re.search(type_pattern, block, re.IGNORECASE)
        issue_match = re.search(issue_pattern, block, re.IGNORECASE)
        fix_match = re.search(fix_pattern, block, re.IGNORECASE)
        
        if file_match:
            file_path = file_match.group(1).strip()
            line_num = int(file_match.group(2)) if file_match.group(2) else None
            
            issue_type = type_match.group(1).strip() if type_match else "일반"
            description = issue_match.group(1).strip() if issue_match else None
            fix = fix_match.group(1).strip() if fix_match else None
            
            # 블록에서 파일/라인/유형 행을 제외한 나머지 텍스트를 설명으로 사용
            if not description:
                # 파일, 라인, 유형, 이슈, 해결 키워드로 시작하는 행을 제외한 나머지 텍스트
                description_lines = []
                for line in block.split('\n'):
                    line = line.strip()
                    if not line or re.match(r'^(?:파일|File|유형|Type|이슈|Issue|해결|Fix):', line, re.IGNORECASE):
                        continue
                    description_lines.append(line)
                
                if description_lines:
                    description = " ".join(description_lines)
            
            # 여전히 설명이 없는 경우, 이슈 유형에 따라 기본 설명 추가
            if not description:
                if issue_type.lower() in ["보안", "security"]:
                    description = "이 코드에 보안 취약점이 발견되었습니다. 입력 검증이나 안전하지 않은 함수 사용을 확인하세요."
                elif issue_type.lower() in ["성능", "performance"]:
                    description = "성능 이슈가 발견되었습니다. 비효율적인 연산이나 불필요한 반복이 있는지 확인하세요."
                elif issue_type.lower() in ["논리", "logical"]:
                    description = "논리적 오류가 발견되었습니다. 알고리즘 로직, 조건문, 반환값 등을 확인하세요."
                elif issue_type.lower() in ["품질", "quality"]:
                    description = "코드 품질 문제가 발견되었습니다. 중복 코드, 명명 규칙, 미사용 변수 등을 확인하세요."
                else:
                    description = "이 라인에 코드 이슈가 감지되었습니다. 구현 방식과 로직을 검토하세요."
            
            # 해결 방법이 없는 경우, 이슈 유형에 따라 기본 해결 방법 추가
            if not fix:
                if issue_type.lower() in ["보안", "security"]:
                    fix = "입력 데이터를 검증하고, 안전한 함수를 사용하세요. eval() 대신 ast.literal_eval()을 고려해 보세요."
                elif issue_type.lower() in ["성능", "performance"]:
                    fix = "중복 연산을 제거하고, 데이터 구조와 알고리즘을 최적화하세요."
                elif issue_type.lower() in ["논리", "logical"]:
                    fix = "알고리즘 로직을 검토하고, 조건문과 계산 순서가 올바른지 확인하세요."
                elif issue_type.lower() in ["품질", "quality"]:
                    fix = "코드 재사용을 고려하고, 명명 규칙을 따르며, 불필요한 변수와 코드를 제거하세요."
                else:
                    fix = "코드를 검토하고 발견된 문제를 수정하세요."
            
            log_debug(f"Parsed issue: file={file_path}, line={line_num}, type={issue_type}")
            log_debug(f"Description: {description[:100]}..." if len(description) > 100 else f"Description: {description}")
            
            issues.append({
                'type': issue_type,
                'description': description,
                'recommendation': fix,
                'file': file_path,
                'line': line_num
            })
    
    # 파일 및 라인 번호가 없는 경우 처리
    if not issues:
        log_debug("Failed to parse issues using primary method, trying alternative method")
        
        # 단순 텍스트 기반으로 이슈 분리 시도
        items = re.findall(r'\n\d+\.\s+(.*?)(?=\n\d+\.|\Z)', response_text, re.DOTALL)
        if not items:
            items = re.findall(r'\n-\s+(.*?)(?=\n-|\Z)', response_text, re.DOTALL)
        
        log_debug(f"Alternative method found {len(items)} items")
        
        for item in items:
            # 파일명과 라인 번호 추출 시도
            file_match = re.search(r'`([^`]+)`|"([^"]+)"|\'([^\']+)\'', item)
            line_match = re.search(r'line\s+(\d+)', item, re.IGNORECASE)
            
            file_path = file_match.group(1) if file_match else list(file_changes.keys())[0] if file_changes else None
            line_num = int(line_match.group(1)) if line_match else None
            
            # 텍스트 분석으로 이슈 유형 추론
            issue_type = "일반"
            if re.search(r'보안|security|취약|vulnerable|injection|eval|exec', item, re.IGNORECASE):
                issue_type = "보안"
            elif re.search(r'성능|performance|효율|효과|비효율|slow|느린|최적화|optimize', item, re.IGNORECASE):
                issue_type = "성능"
            elif re.search(r'논리|logic|계산|calculation|알고리즘|algorithm|조건|condition', item, re.IGNORECASE):
                issue_type = "논리"
            elif re.search(r'품질|quality|코드|code|중복|duplicate|명명|naming|변수|variable', item, re.IGNORECASE):
                issue_type = "품질"
                
            # 유형에 따른 설명과 해결책 생성
            description = item.strip()
            recommendation = ""
            
            if issue_type == "보안":
                recommendation = "보안 취약점을 해결하기 위해 입력 검증 및 안전한 API를 사용하세요."
            elif issue_type == "성능":
                recommendation = "알고리즘 최적화 및 불필요한 연산 제거를 통해 성능을 개선하세요."
            elif issue_type == "논리":
                recommendation = "조건문, 계산식, 알고리즘 로직을 검토하고 수정하세요."
            elif issue_type == "품질":
                recommendation = "코드 중복 제거, 명명 규칙 준수, 미사용 코드 정리 등으로 품질을 높이세요."
            else:
                recommendation = "코드를 검토하고 발견된 문제를 수정하세요."
            
            issues.append({
                'type': issue_type,
                'description': description,
                'recommendation': recommendation,
                'file': file_path,
                'line': line_num
            })
    
    return issues

# 이슈 요약 생성 함수
def generate_summary(issues):
    if not issues:
        return f"{BOT_SIGNATURE}\n\n# 코드 리뷰 요약\n\n코드 리뷰 완료: 이슈가 발견되지 않았습니다."
    
    issue_types = {}
    for issue in issues:
        category = issue['type']
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
        if DEBUG_MODE and len(comments) > 0:
            log_debug(f"Sample comment data: {json.dumps(comments[0], indent=2)[:500]}...")
        
        all_comments.extend(comments)
        
        if len(comments) < per_page:
            break
            
        page += 1
    
    log_info(f"Retrieved {len(all_comments)} total PR comments")
    return all_comments

# 모든 인라인 코멘트(리뷰 코멘트) 가져오기
def get_all_review_comments():
    comments_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
    log_debug(f"Fetching all PR review comments from: {comments_url}")
    
    all_comments = []
    page = 1
    per_page = 100
    
    while True:
        params = {'per_page': per_page, 'page': page}
        response = requests.get(comments_url, headers=github_headers, params=params)
        
        if response.status_code != 200:
            log_error(f"Failed to get review comments (status code: {response.status_code})")
            log_debug(f"Response: {response.text}")
            break
        
        comments = response.json()
        if DEBUG_MODE and len(comments) > 0:
            log_debug(f"Sample review comment data: {json.dumps(comments[0], indent=2)[:500]}...")
        
        all_comments.extend(comments)
        
        if len(comments) < per_page:
            break
            
        page += 1
    
    log_info(f"Retrieved {len(all_comments)} total PR review comments")
    return all_comments

# 봇 코멘트인지 확인
def is_bot_comment(comment):
    body = comment.get('body', '')
    user_login = comment.get('user', {}).get('login', '')
    # 디버그용 - 코멘트 본문 확인
    if len(body) > 0:
        log_debug(f"Checking comment body (first 100 chars): {body[:100]}")
        log_debug(f"Bot signature found: {BOT_SIGNATURE in body}")
    return (BOT_SIGNATURE in body) or (user_login == "github-actions" or user_login == "github-actions[bot]")

# 인라인 코멘트(리뷰 코멘트) 전체 삭제
def delete_all_bot_review_comments():
    all_comments = get_all_review_comments()
    log_info(f"Checking {len(all_comments)} review comments for deletion")
    
    deleted_count = 0
    for comment in all_comments:
        comment_id = comment.get('id')
        if comment_id and is_bot_comment(comment):
            log_debug(f"Deleting bot review comment {comment_id}")
            
            delete_url = f"https://api.github.com/repos/{repo}/pulls/comments/{comment_id}"
            response = requests.delete(delete_url, headers=github_headers)
            
            if response.status_code == 204:  # 204 No Content는 성공적인 삭제를 의미
                log_info(f"Successfully deleted review comment {comment_id}")
                deleted_count += 1
            else:
                log_error(f"Failed to delete review comment {comment_id} (status code: {response.status_code})")
                log_debug(f"Response: {response.text}")
    
    log_info(f"Deleted {deleted_count} bot review comments")
    return deleted_count

# 일반 PR 코멘트는 중복 처리 (Outdated로 표시)
def mark_comments_as_outdated():
    all_comments = get_all_comments()
    log_info(f"Checking {len(all_comments)} comments for marking as outdated")
    
    marked_count = 0
    for comment in all_comments:
        comment_id = comment.get('id')
        body = comment.get('body', '')
        
        if comment_id and is_bot_comment(comment) and "OUTDATED" not in body:
            log_debug(f"Marking bot comment {comment_id} as outdated")
            
            # 코멘트 본문에 "OUTDATED" 표시 추가
            updated_body = f"{body}\n\n**OUTDATED**: 새로운 리뷰가 생성되었습니다."
            
            update_url = f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"
            update_data = {'body': updated_body}
            
            response = requests.patch(update_url, headers=github_headers, json=update_data)
            
            if response.status_code == 200:
                log_info(f"Successfully marked comment {comment_id} as outdated")
                marked_count += 1
            else:
                log_error(f"Failed to mark comment {comment_id} as outdated (status code: {response.status_code})")
                log_debug(f"Response: {response.text}")
    
    log_info(f"Marked {marked_count} bot comments as outdated")
    return marked_count

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
        if DEBUG_MODE:
            log_debug(f"Reviews API response status: {response.status_code}")
            log_debug(f"Reviews API response length: {len(reviews)}")
            if len(reviews) > 0:
                log_debug(f"Sample review data: {json.dumps(reviews[0], indent=2)[:500]}...")
        
        all_reviews.extend(reviews)
        
        if len(reviews) < per_page:
            break
            
        page += 1
    
    log_info(f"Retrieved {len(all_reviews)} total PR reviews")
    return all_reviews

# 봇 리뷰 전체 삭제/dismiss
def dismiss_all_bot_reviews():
    all_reviews = get_all_reviews()
    log_info(f"Checking {len(all_reviews)} reviews for dismissal")
    
    dismissed_count = 0
    for review in all_reviews:
        review_id = review.get('id')
        user_login = review.get('user', {}).get('login', '')
        review_body = review.get('body', '')
        review_state = review.get('state', '')
        
        log_debug(f"Review ID: {review_id}, User: {user_login}, State: {review_state}, Body starts with: {review_body[:50] if review_body else 'No body'}")
        
        if not review_id:
            continue
            
        # 봇 리뷰인지 확인 (GitHub Actions 봇 또는 시그니처로 식별)
        is_bot = (BOT_SIGNATURE in review_body) or (user_login == "github-actions" or user_login == "github-actions[bot]")
        
        # COMMENT 상태가 아닌 경우에만 dismiss 시도 (APPROVED 또는 REQUEST_CHANGES)
        if is_bot and review_state != "COMMENTED":
            log_debug(f"Dismissing bot review {review_id} from user {user_login}")
            
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
        elif is_bot:
            log_debug(f"Skipping COMMENT type review {review_id} - cannot dismiss")
    
    log_info(f"Dismissed {dismissed_count} bot reviews")
    return dismissed_count

# GitHub PR에 인라인 코멘트 남기기
def post_review_comments(commit_sha, issues, overall_comment):
    # 이전 봇 코멘트/리뷰 삭제
    log_info("Starting cleanup of previous bot comments and reviews")
    try:
        # 기존 봇 인라인 코멘트(리뷰 코멘트) 모두 삭제
        deleted_review_comments = delete_all_bot_review_comments()
        log_info(f"Deleted {deleted_review_comments} bot review comments")
        
        # 기존 일반 코멘트는 중복으로 표시
        marked_comments = mark_comments_as_outdated()
        log_info(f"Marked {marked_comments} bot comments as outdated")
        
        # 기존 봇 리뷰 모두 dismiss
        dismissed_reviews = dismiss_all_bot_reviews()
        log_info(f"Dismissed {dismissed_reviews} bot reviews")
        
        # 삭제 작업 후 약간의 대기 시간 추가 (GitHub API 반영 시간 고려)
        if deleted_review_comments > 0 or dismissed_reviews > 0 or marked_comments > 0:
            log_info("Waiting for GitHub API to process changes...")
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
            
            # 설명이 없거나 비어있는 경우 기본 메시지 사용
            description = issue.get('description', '').strip()
            if not description:
                if issue['type'].lower() in ["보안", "security"]:
                    description = "이 코드에 보안 취약점이 발견되었습니다. 입력 검증이나 안전하지 않은 함수 사용을 확인하세요."
                elif issue['type'].lower() in ["성능", "performance"]:
                    description = "성능 이슈가 발견되었습니다. 비효율적인 연산이나 불필요한 반복이 있는지 확인하세요."
                elif issue['type'].lower() in ["논리", "logical"]:
                    description = "논리적 오류가 발견되었습니다. 알고리즘 로직, 조건문, 반환값 등을 확인하세요."
                elif issue['type'].lower() in ["품질", "quality"]:
                    description = "코드 품질 문제가 발견되었습니다. 중복 코드, 명명 규칙, 미사용 변수 등을 확인하세요."
                else:
                    description = "이 라인에 코드 이슈가 감지되었습니다. 구현 방식과 로직을 검토하세요."
            
            comment_body += f"{description}\n\n"
            
            recommendation = issue.get('recommendation', '').strip()
            if recommendation:
                comment_body += f"**해결 방법:**\n{recommendation}"
            else:
                if issue['type'].lower() in ["보안", "security"]:
                    comment_body += "**해결 방법:**\n입력 데이터를 검증하고, 안전한 함수를 사용하세요. eval() 대신 ast.literal_eval()을 고려해 보세요."
                elif issue['type'].lower() in ["성능", "performance"]:
                    comment_body += "**해결 방법:**\n중복 연산을 제거하고, 데이터 구조와 알고리즘을 최적화하세요."
                elif issue['type'].lower() in ["논리", "logical"]:
                    comment_body += "**해결 방법:**\n알고리즘 로직을 검토하고, 조건문과 계산 순서가 올바른지 확인하세요."
                elif issue['type'].lower() in ["품질", "quality"]:
                    comment_body += "**해결 방법:**\n코드 재사용을 고려하고, 명명 규칙을 따르며, 불필요한 변수와 코드를 제거하세요."
                else:
                    comment_body += "**해결 방법:**\n코드를 면밀히 검토하고 발견된 문제를 수정하세요."
            
            comments.append({
                'path': issue['file'],
                'position': issue['line'],  # 정확한 position 계산이 필요할 수 있음
                'body': comment_body
            })
    
    log_debug(f"Prepared {len(comments)} inline comments")
    for i, comment in enumerate(comments):
        log_debug(f"Comment {i+1} - Path: {comment['path']}, Position: {comment['position']}")
        log_debug(f"Comment body preview: {comment['body'][:150]}...")
    
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
    log_info(f"Working with repository: {repo}")
    log_info(f"Working with PR number: {pr_number}")
    
    # GitHub 토큰 검증
    if not validate_github_token():
        raise Exception("GitHub token validation failed")
    
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
    
    # 간결한 프롬프트로 변경
    prompt = f"""코드 변경 사항을 리뷰하고 중요한 문제점만 간결하게 알려주세요:

1. 각 문제점에 대해 다음 형식을 사용하세요:
- 파일: [파일명], 라인: [라인번호]
- 유형: [보안/성능/논리/품질] 중 선택
- 이슈: [문제에 대한 상세한 설명 - 무엇이 문제인지, 왜 문제인지 설명]
- 해결: [구체적인 해결 방법 - 어떻게 수정해야 하는지 명확히 설명]

2. 중요도 순서로 최대 5개 이슈만 알려주세요.
3. 장황한 설명이나 여러 코드 예제는 필요 없습니다.
4. 파일명과 라인 번호를 꼭 명시해 주세요.
5. 모든 이슈에 구체적인 설명과 실용적인 해결 방법을 필수로 작성해 주세요.
6. 단순히 "이슈가 있습니다"와 같은 모호한 설명은 피하고 구체적으로 적어주세요.

다음 코드 변경 사항을 리뷰하세요:

{diff}"""
    
    response = openai_client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000
    )
    review_comment = response.choices[0].message.content
    log_debug(f"OpenAI response:\n{review_comment}")
    
    # OpenAI 응답 파싱
    issues = parse_ai_response(review_comment, file_changes)
    log_info(f"Parsed {len(issues)} issues from OpenAI response")
    
    # 각 이슈 정보 로깅
    for i, issue in enumerate(issues):
        log_debug(f"Issue {i+1}:")
        log_debug(f"  File: {issue.get('file')}")
        log_debug(f"  Line: {issue.get('line')}")
        log_debug(f"  Type: {issue.get('type')}")
        log_debug(f"  Description: {issue.get('description')[:100]}..." if issue.get('description') and len(issue.get('description')) > 100 else f"  Description: {issue.get('description')}")
        log_debug(f"  Recommendation: {issue.get('recommendation')[:100]}..." if issue.get('recommendation') and len(issue.get('recommendation')) > 100 else f"  Recommendation: {issue.get('recommendation')}")
    
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