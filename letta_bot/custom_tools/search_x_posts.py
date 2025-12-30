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
                'tweet.fields': 'created_at,public_metrics,text,conversation_id,referenced_tweets,in_reply_to_user_id,lang,entities',
                'expansions': 'author_id,referenced_tweets.id,referenced_tweets.id.author_id',
                'user.fields': 'username,name,public_metrics,verified,verified_type',
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
        user['id']: {
            'username': user['username'],
            'followers': user.get('public_metrics', {}).get('followers_count', 0),
            'verified': user.get('verified', False),
            'verified_type': user.get('verified_type', ''),
        }
        for user in data.get('includes', {}).get('users', [])
        if user.get('id') and user.get('username')
    }

    # Map referenced tweets for context
    referenced_tweets_map = {
        tweet['id']: tweet
        for tweet in data.get('includes', {}).get('tweets', [])
        if tweet.get('id')
    }

    lines = [f"Found {result_count} post(s) for query '{query}' (last {hours_ago}h):\n"]

    for i, post in enumerate(posts, 1):
        author_id = post.get('author_id', '')
        author_info = users_map.get(author_id, {
            'username': 'unknown', 'followers': 0, 'verified': False, 'verified_type': ''
        })
        username = author_info['username']
        followers = author_info['followers']
        verified = author_info['verified']
        verified_type = author_info['verified_type']
        metrics = post.get('public_metrics', {})

        if created_at := post.get('created_at'):
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                timestamp = dt.strftime('%Y-%m-%d %H:%M UTC')
            except (ValueError, TypeError):
                timestamp = created_at
        else:
            timestamp = 'Unknown time'

        # Parse referenced tweets for reply/quote detection
        refs = post.get('referenced_tweets', [])
        reply_to_id = next((r['id'] for r in refs if r.get('type') == 'replied_to'), None)
        quote_of_id = next((r['id'] for r in refs if r.get('type') == 'quoted'), None)
        is_retweet = any(r.get('type') == 'retweeted' for r in refs)

        # Build post type indicator
        post_type = ''
        if is_retweet:
            post_type = '[RT] '
        elif reply_to_id:
            post_type = '[Reply] '
        elif quote_of_id:
            post_type = '[Quote] '

        # Build verified badge
        if verified:
            # verified_type can be: 'blue', 'business', 'government', or empty
            badge = ' ✓' if verified_type == 'blue' else ' ☑️'
        else:
            badge = ''

        # Build header with followers count and verified badge
        header = f'--- Post {i} {post_type}by @{username}{badge} ({followers:,} followers) ({timestamp}) ---'

        lines.append(header)
        lines.append(post.get('text', ''))

        # Extract hashtags and mentions from entities
        entities = post.get('entities', {})
        hashtags = [f"#{h['tag']}" for h in entities.get('hashtags', [])]
        mentions = [f"@{m['username']}" for m in entities.get('mentions', [])]

        if hashtags or mentions:
            entity_parts = []
            if hashtags:
                entity_parts.append(f"Tags: {', '.join(hashtags)}")
            if mentions:
                entity_parts.append(f"Mentions: {', '.join(mentions)}")
            lines.append(f"[{' | '.join(entity_parts)}]")

        # Show thread/conversation info
        if conversation_id := post.get('conversation_id'):
            if conversation_id != post.get('id'):
                lines.append(f'[Thread: {conversation_id}]')

        # Show what this is replying to
        if reply_to_id and (ref_tweet := referenced_tweets_map.get(reply_to_id)):
            ref_author_id = ref_tweet.get('author_id', '')
            ref_author = users_map.get(ref_author_id, {}).get('username', 'unknown')
            ref_text = ref_tweet.get('text', '')[:100]
            if len(ref_tweet.get('text', '')) > 100:
                ref_text += '...'
            lines.append(f'↳ Replying to @{ref_author}: "{ref_text}"')

        # Show what this is quoting
        if quote_of_id and (ref_tweet := referenced_tweets_map.get(quote_of_id)):
            ref_author_id = ref_tweet.get('author_id', '')
            ref_author = users_map.get(ref_author_id, {}).get('username', 'unknown')
            ref_text = ref_tweet.get('text', '')[:100]
            if len(ref_tweet.get('text', '')) > 100:
                ref_text += '...'
            lines.append(f'↳ Quoting @{ref_author}: "{ref_text}"')

        lines.extend([
            f"[Likes: {metrics.get('like_count', 0)} | "
            f"Retweets: {metrics.get('retweet_count', 0)} | "
            f"Replies: {metrics.get('reply_count', 0)}]",
            f"Link: https://x.com/{username}/status/{post.get('id', '')}",
            '',
        ])

    return '\n'.join(lines)
