"""X/Twitter search tool for Letta agents.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to search recent posts on X/Twitter using flexible query
syntax with operators. Use this to monitor product mentions, track account mentions,
find trending content by hashtag, or any custom search query.
"""

import os
from datetime import datetime, timedelta, timezone

API_URL = 'https://api.x.com/2/tweets/search/recent'
MIN_HOURS, MAX_HOURS = 1, 168
MIN_RESULTS, MAX_RESULTS = 10, 100
REQUEST_TIMEOUT = 30


def search_x_posts(
    query: str,
    hours_ago: int = 24,
    max_results: int = 20,
) -> str:
    """Search recent posts on X/Twitter using flexible query syntax.

    Use this tool to search for posts matching a query with X API operators.
    Authenticates using OAuth 2.0 App-Only Bearer Token.

    Environment variables required:
    - X_API_KEY: X/Twitter Bearer Token for API authentication

    Args:
        query (str): Search query using X API operators. Examples:
            - "TzKT OR PyTezos" (posts containing either term)
            - "@BakingBad_Dev" (posts mentioning account)
            - "#Tezos min_faves:50 -is:retweet" (hashtag with filters)
            - "(privacy OR \"zero knowledge\") lang:en" (complex query)

            Supported operators:
            - Keywords: "word1 word2" (contains both)
            - Exact phrase: "\"exact phrase\""
            - From user: "from:username"
            - Mentions: "@username"
            - Hashtags: "#hashtag"
            - Exclude: "-term" or "-from:username"
            - Or: "term1 OR term2"
            - Grouping: "(term1 OR term2) -term3"
            - Exclude retweets: "-is:retweet"
            - Exclude replies: "-is:reply"
            - Minimum likes: "min_faves:50"
            - Minimum retweets: "min_retweets:10"
            - Language: "lang:en"

        hours_ago (int): How many hours back to search (default: 24, max: 168 / 7 days)
        max_results (int): Maximum number of posts to return (default: 20, range: 10-100)

    Returns:
        str: Formatted list of posts with timestamps, engagement metrics, and links
    """
    import requests

    if not (bearer_token := os.environ.get('X_API_KEY')):
        return 'Error: X_API_KEY environment variable is not set'

    if not query or not (query := query.strip()):
        return 'Error: query is required and cannot be empty'

    if not MIN_HOURS <= hours_ago <= MAX_HOURS:
        return f'Error: hours_ago must be between {MIN_HOURS} and {MAX_HOURS}, got {hours_ago}'

    if not MIN_RESULTS <= max_results <= MAX_RESULTS:
        return f'Error: max_results must be between {MIN_RESULTS} and {MAX_RESULTS}, got {max_results}'

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

    try:
        response = requests.get(
            API_URL,
            params={
                'query': query,
                'start_time': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'max_results': max_results,
                'sort_order': 'recency',
                'tweet.fields': 'created_at,public_metrics,text',
                'expansions': 'author_id',
                'user.fields': 'username,name',
            },
            headers={'Authorization': f'Bearer {bearer_token}'},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return 'Error: Request to X API timed out'
    except requests.exceptions.RequestException as e:
        return f'Error fetching posts from X API: {e}'

    match response.status_code:
        case 200:
            pass
        case 401:
            return 'Error: Invalid or expired X API Bearer Token'
        case 403:
            return 'Error: Access forbidden - check API permissions or rate limits'
        case 429:
            return 'Error: Rate limit exceeded - please try again later'
        case code:
            return f'Error: X API returned status {code} - {response.text}'

    try:
        data = response.json()
    except (KeyError, ValueError) as e:
        return f'Error parsing X API response: {e}'

    if not data.get('data'):
        return f"No posts found for query '{query}' in the last {hours_ago} hours."

    posts = data['data']
    result_count = data.get('meta', {}).get('result_count', len(posts))

    users_map = {
        user['id']: user['username']
        for user in data.get('includes', {}).get('users', [])
        if user.get('id') and user.get('username')
    }

    lines = [f"Found {result_count} post(s) for query '{query}' (last {hours_ago}h):\n"]

    for i, post in enumerate(posts, 1):
        username = users_map.get(post.get('author_id', ''), 'unknown')
        metrics = post.get('public_metrics', {})

        if created_at := post.get('created_at'):
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                timestamp = dt.strftime('%Y-%m-%d %H:%M UTC')
            except (ValueError, TypeError):
                timestamp = created_at
        else:
            timestamp = 'Unknown time'

        lines.extend([
            f'--- Post {i} by @{username} ({timestamp}) ---',
            post.get('text', ''),
            f"[Likes: {metrics.get('like_count', 0)} | "
            f"Retweets: {metrics.get('retweet_count', 0)} | "
            f"Replies: {metrics.get('reply_count', 0)}]",
            f"Link: https://x.com/{username}/status/{post.get('id', '')}",
            '',
        ])

    return '\n'.join(lines)
