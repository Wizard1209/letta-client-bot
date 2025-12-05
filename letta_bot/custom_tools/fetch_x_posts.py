"""Twitter/X posts retrieval tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to fetch recent posts from a specific X/Twitter user
using the X API v2 search/recent endpoint.
"""

from datetime import datetime, timedelta, timezone
import os


def fetch_x_posts(username: str, hours_ago: int = 24, max_results: int = 10) -> str:
    """Retrieve recent posts from a specific X/Twitter user.

    This tool fetches posts from the X API v2 search/recent endpoint,
    filtering by username and time window. It authenticates using OAuth 2.0
    App-Only flow (generates bearer token from API key and secret).

    Environment variables required:
    - X_API_KEY: X/Twitter API Key (consumer key)
    - X_API_KEY_SECRET: X/Twitter API Key Secret (consumer secret)

    Args:
        username (str): X/Twitter username to fetch posts from (without @ symbol)
        hours_ago (int): How many hours back to search (default: 24, max: 168 / 7 days)
        max_results (int): Maximum number of posts to return (default: 10, range: 10-100)

    Returns:
        str: Formatted list of posts with timestamps and engagement metrics, or error message
    """
    import base64
    import requests

    # Get API credentials from environment
    api_key = os.environ.get('X_API_KEY')
    api_secret = os.environ.get('X_API_KEY_SECRET')

    if not api_key:
        return 'Error: X_API_KEY environment variable is not set'
    if not api_secret:
        return 'Error: X_API_KEY_SECRET environment variable is not set'

    # Validate parameters
    if not username:
        return 'Error: username is required'

    # Remove @ if provided
    username = username.lstrip('@')

    # Clamp hours_ago to API limit (7 days = 168 hours for recent search)
    if hours_ago < 1:
        hours_ago = 1
    elif hours_ago > 168:
        hours_ago = 168

    # Clamp max_results to API limits
    if max_results < 10:
        max_results = 10
    elif max_results > 100:
        max_results = 100

    # --- Step 1: Generate Bearer Token using OAuth 2.0 App-Only ---
    credentials = f'{api_key}:{api_secret}'
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    token_url = 'https://api.x.com/oauth2/token'
    token_headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
    }
    token_data = 'grant_type=client_credentials'

    try:
        token_response = requests.post(token_url, headers=token_headers, data=token_data, timeout=10)

        if token_response.status_code != 200:
            return f'Error obtaining bearer token: {token_response.status_code} - {token_response.text}'

        token_json = token_response.json()
        bearer_token = token_json.get('access_token')

        if not bearer_token:
            return 'Error: No access_token in OAuth response'

    except requests.exceptions.RequestException as e:
        return f'Error obtaining bearer token: {str(e)}'

    # --- Step 2: Fetch posts from X API ---
    now_utc = datetime.now(timezone.utc)
    start_time = now_utc - timedelta(hours=hours_ago)
    start_time_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    query = f'from:{username}'
    url = 'https://api.x.com/2/tweets/search/recent'

    params = {
        'query': query,
        'start_time': start_time_str,
        'max_results': max_results,
        'sort_order': 'recency',
        'tweet.fields': 'created_at,public_metrics,text',
        'expansions': 'author_id',
        'user.fields': 'username,name',
    }

    headers = {
        'Authorization': f'Bearer {bearer_token}',
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)

        if response.status_code == 401:
            return 'Error: Invalid or expired X API credentials'
        elif response.status_code == 403:
            return 'Error: Access forbidden - check API permissions or rate limits'
        elif response.status_code == 429:
            return 'Error: Rate limit exceeded - please try again later'
        elif response.status_code != 200:
            return f'Error: X API returned status {response.status_code} - {response.text}'

        data = response.json()

        if 'data' not in data or not data['data']:
            return f'No posts found from @{username} in the last {hours_ago} hours'

        posts = data['data']
        meta = data.get('meta', {})
        result_count = meta.get('result_count', len(posts))

        output_lines = [f'Found {result_count} post(s) from @{username} (last {hours_ago}h):\n']

        for i, post in enumerate(posts, 1):
            text = post.get('text', '')
            created_at = post.get('created_at', '')
            metrics = post.get('public_metrics', {})

            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    time_str = dt.strftime('%Y-%m-%d %H:%M UTC')
                except (ValueError, TypeError):
                    time_str = created_at
            else:
                time_str = 'Unknown time'

            likes = metrics.get('like_count', 0)
            retweets = metrics.get('retweet_count', 0)
            replies = metrics.get('reply_count', 0)

            output_lines.append(f'--- Post {i} ({time_str}) ---')
            output_lines.append(text)
            output_lines.append(f'[Likes: {likes} | Retweets: {retweets} | Replies: {replies}]')
            output_lines.append('')

        return '\n'.join(output_lines)

    except requests.exceptions.Timeout:
        return 'Error: Request to X API timed out'
    except requests.exceptions.RequestException as e:
        return f'Error fetching posts from X API: {str(e)}'
    except (KeyError, ValueError) as e:
        return f'Error parsing X API response: {str(e)}'
