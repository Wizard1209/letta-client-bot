"""Discover new accounts discussing specific topics on X/Twitter.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to find conversations happening outside their
monitored feeds. It searches for topic keywords while filtering out known
accounts, surfacing new voices and parallel conversations you might be missing.
"""

import os
from datetime import datetime, timedelta, timezone

API_URL = 'https://api.x.com/2/tweets/search/recent'
MIN_RESULTS, MAX_RESULTS = 10, 100
REQUEST_TIMEOUT = 30


def discover_topics(
    keywords: str,
    exclude_accounts: str = '',
    hours_ago: int = 24,
    min_likes: int = 5,
    max_results: int = 20,
    next_token: str = '',
) -> str:
    """Find new accounts discussing specific topics outside your known feeds.

    Searches for posts matching topic keywords while excluding accounts you
    already track, to discover new voices and conversations in your space.

    Results are grouped by author to highlight who is talking, not just what.

    Environment variables required:
    - X_API_KEY: X/Twitter Bearer Token for API authentication

    Args:
        keywords (str): Topic search terms, space-separated for AND, use OR for alternatives.
            Examples:
            - "privacy wallet" (posts containing both words)
            - "ZK proof OR zero knowledge" (posts containing either)
            - '"aztec network" privacy' (exact phrase + keyword)

        exclude_accounts (str): Comma-separated usernames to exclude from results
            (accounts you already track). Without @ symbol.
            Example: "BakingBad_Dev,aztecnetwork,azguardwallet"
            Defaults to empty string (no exclusions).

        hours_ago (int): How many hours back to search (default: 24, max: 168 / 7 days)
        min_likes (int): Minimum likes to filter low-quality posts (default: 5, set to 0 for all)
        max_results (int): Maximum posts to return (default: 20, range: 10-100)
        next_token (str): Pagination token from previous result for next batch.

    Returns:
        str: Posts grouped by author, showing new accounts discussing your topics

    Examples:
        discover_topics("privacy wallet", exclude_accounts="BakingBad_Dev,aztecnetwork")
        discover_topics("ZK proof OR zero knowledge", hours_ago=48, min_likes=10)
        discover_topics("tezos baking", max_results=30)
    """
    import requests

    if not (bearer_token := os.environ.get('X_API_KEY')):
        return 'Error: X_API_KEY environment variable is not set'

    if not keywords or not (keywords := keywords.strip()):
        return 'Error: keywords is required and cannot be empty'

    if not MIN_RESULTS <= max_results <= MAX_RESULTS:
        return f'Error: max_results must be between {MIN_RESULTS} and {MAX_RESULTS}, got {max_results}'

    hours_ago = max(1, min(168, hours_ago))

    # Build query with exclusions
    query_parts = [keywords]

    # Exclude known accounts
    if exclude_accounts:
        for account in exclude_accounts.split(','):
            account = account.strip().lstrip('@')
            if account:
                query_parts.append(f'-from:{account}')

    # Exclude retweets for original content only
    query_parts.append('-is:retweet')

    # Note: min_faves operator requires elevated API access,
    # so we filter by likes post-fetch using min_likes param

    # English language default (most useful for discovery)
    query_parts.append('lang:en')

    query = ' '.join(query_parts)

    # X API query limit is 512 chars
    if len(query) > 512:
        return f'Error: Built query is {len(query)} chars (max 512). Reduce keywords or exclude_accounts list.'

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

    params = {
        'query': query,
        'start_time': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'max_results': max_results,
        'sort_order': 'relevancy',
        'tweet.fields': 'created_at,public_metrics,text,entities,author_id',
        'expansions': 'author_id',
        'user.fields': 'username,name,public_metrics,verified,verified_type,description,created_at',
    }

    if next_token:
        params['next_token'] = next_token

    try:
        response = requests.get(
            API_URL,
            params=params,
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
            return 'Error: Access forbidden - check API permissions'
        case 429:
            return 'Error: Rate limit exceeded - please try again later'
        case code:
            return f'Error: X API returned status {code} - {response.text}'

    try:
        data = response.json()
    except (KeyError, ValueError) as e:
        return f'Error parsing X API response: {e}'

    if not data.get('data'):
        return f'No new posts found for "{keywords}" in the last {hours_ago}h (min {min_likes} likes).'

    posts = data['data']

    # Filter by min_likes (post-fetch since min_faves operator requires elevated access)
    if min_likes > 0:
        posts = [
            p for p in posts
            if p.get('public_metrics', {}).get('like_count', 0) >= min_likes
        ]
        if not posts:
            return f'No posts found for "{keywords}" meeting {min_likes}+ likes threshold in the last {hours_ago}h.'

    # Build users map
    users_map = {
        user['id']: {
            'username': user['username'],
            'name': user.get('name', ''),
            'followers': user.get('public_metrics', {}).get('followers_count', 0),
            'following': user.get('public_metrics', {}).get('following_count', 0),
            'tweets': user.get('public_metrics', {}).get('tweet_count', 0),
            'verified': user.get('verified', False),
            'verified_type': user.get('verified_type', ''),
            'description': user.get('description', ''),
            'created_at': user.get('created_at', ''),
        }
        for user in data.get('includes', {}).get('users', [])
        if user.get('id') and user.get('username')
    }

    # Group posts by author for discovery focus
    authors = {}  # username -> list of posts
    for post in posts:
        author_id = post.get('author_id', '')
        author_info = users_map.get(author_id)
        if not author_info:
            continue
        username = author_info['username']
        if username not in authors:
            authors[username] = {'info': author_info, 'posts': []}
        authors[username]['posts'].append(post)

    # Sort authors by follower count
    sorted_authors = sorted(
        authors.items(),
        key=lambda x: x[1]['info']['followers'],
        reverse=True,
    )

    result_count = data.get('meta', {}).get('result_count', len(posts))
    lines = [
        f'Found {result_count} post(s) from {len(authors)} new account(s) '
        f'discussing "{keywords}" (last {hours_ago}h, min {min_likes} likes):\n'
    ]

    for author_idx, (username, author_data) in enumerate(sorted_authors, 1):
        info = author_data['info']
        author_posts = author_data['posts']

        # Verified badge
        if info['verified']:
            badge = ' \u2713' if info['verified_type'] == 'blue' else ' \u2611\ufe0f'
        else:
            badge = ''

        lines.append(f'=== {author_idx}. @{username}{badge} ({info["followers"]:,} followers) ===')

        if info['description']:
            bio = info['description'][:150]
            if len(info['description']) > 150:
                bio += '...'
            lines.append(f'Bio: {bio}')

        lines.append(f'{len(author_posts)} matching post(s):')

        for post in author_posts:
            metrics = post.get('public_metrics', {})

            if created_at := post.get('created_at'):
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    timestamp = dt.strftime('%Y-%m-%d %H:%M UTC')
                except (ValueError, TypeError):
                    timestamp = created_at
            else:
                timestamp = 'Unknown time'

            text = post.get('text', '')
            if len(text) > 200:
                text = text[:200] + '...'

            lines.append(f'  ({timestamp}) "{text}"')
            lines.append(
                f'  [Likes: {metrics.get("like_count", 0)} | '
                f'RTs: {metrics.get("retweet_count", 0)} | '
                f'Replies: {metrics.get("reply_count", 0)}]'
            )
            lines.append(f'  Link: https://x.com/{username}/status/{post.get("id", "")}')

        lines.append('')

    # Pagination
    if next_token_value := data.get('meta', {}).get('next_token'):
        lines.append(f'Next page token: {next_token_value}')

    return '\n'.join(lines)
