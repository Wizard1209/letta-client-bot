"""Get recent posts from a specific X/Twitter account.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to retrieve recent posts from any public X/Twitter
account by username. Use this to review account activity, check posting
frequency, analyze engagement, or monitor specific accounts.
"""

import os
from datetime import datetime, timezone

USERS_API_URL = 'https://api.x.com/2/users/by/username'
TIMELINE_API_URL = 'https://api.x.com/2/users/{user_id}/tweets'
MIN_RESULTS, MAX_RESULTS = 5, 100
MAX_MEDIA_RESULTS = 10
REQUEST_TIMEOUT = 30


def _resolve_user_id(username, bearer_token):
    """Resolve X username to user ID."""
    import requests

    response = requests.get(
        f'{USERS_API_URL}/{username}',
        headers={'Authorization': f'Bearer {bearer_token}'},
        params={'user.fields': 'public_metrics,verified,verified_type'},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        return None, f'Error: X API returned status {response.status_code} when looking up @{username}'

    data = response.json()

    # X API returns 200 with errors array when user not found
    if data.get('errors') and not data.get('data'):
        return None, f'Error: User @{username} not found'

    user_data = data.get('data')
    if not user_data:
        return None, f'Error: User @{username} not found'

    return user_data, None


def get_account_timeline(
    username: str,
    max_results: int = 10,
    exclude_replies: bool = False,
    exclude_retweets: bool = False,
    attach_media: bool = False,
    next_token: str = '',
) -> str:
    """Get recent posts from a specific X/Twitter account by username.

    Retrieves the latest posts from a public account's timeline. Use this to
    review what an account has been posting, check engagement metrics, or
    monitor account activity.

    Environment variables required:
    - X_API_KEY: X/Twitter Bearer Token for API authentication

    Args:
        username (str): X/Twitter username without @ symbol (e.g., "BakingBad_Dev")
        max_results (int): Number of posts to return (default: 10, range: 5-100)
        exclude_replies (bool): If True, exclude reply posts from results (default: False)
        exclude_retweets (bool): If True, exclude retweets from results (default: False)
        attach_media (bool): If True, sends post images and video thumbnails
            to the agent as visual context via a separate async message.
            When enabled, max_results is capped at 10 posts.
            Defaults to False (text-only results).
        next_token (str): Pagination token from a previous result to get the
            next batch. Shown at end of results as "Next page token: <token>".
            Defaults to empty string (start from beginning).

    Returns:
        str: Formatted list of posts with timestamps, engagement metrics, and links

    Examples:
        get_account_timeline("BakingBad_Dev")
        get_account_timeline("aztaborern", max_results=20, exclude_retweets=True)
        get_account_timeline("BakingBad_Dev", attach_media=True)
    """
    import requests

    if not (bearer_token := os.environ.get('X_API_KEY')):
        return 'Error: X_API_KEY environment variable is not set'

    if not username or not (username := username.strip().lstrip('@')):
        return 'Error: username is required and cannot be empty'

    if not MIN_RESULTS <= max_results <= MAX_RESULTS:
        return f'Error: max_results must be between {MIN_RESULTS} and {MAX_RESULTS}, got {max_results}'

    if attach_media:
        max_results = min(max_results, MAX_MEDIA_RESULTS)

    # Step 1: Resolve username to user ID
    user_data, error = _resolve_user_id(username, bearer_token)
    if error:
        return error

    user_id = user_data['id']
    user_followers = user_data.get('public_metrics', {}).get('followers_count', 0)
    user_verified = user_data.get('verified', False)
    user_verified_type = user_data.get('verified_type', '')

    # Step 2: Build timeline request
    exclude = []
    if exclude_replies:
        exclude.append('replies')
    if exclude_retweets:
        exclude.append('retweets')

    expansions = 'author_id,referenced_tweets.id,referenced_tweets.id.author_id'
    if attach_media:
        expansions += ',attachments.media_keys'

    params = {
        'max_results': max_results,
        'tweet.fields': 'created_at,public_metrics,text,conversation_id,referenced_tweets,in_reply_to_user_id,entities',
        'expansions': expansions,
        'user.fields': 'username,name,public_metrics,verified,verified_type',
    }

    if exclude:
        params['exclude'] = ','.join(exclude)

    if attach_media:
        params['media.fields'] = 'preview_image_url,url,type'

    if next_token:
        params['pagination_token'] = next_token

    # Step 3: Fetch timeline
    try:
        response = requests.get(
            TIMELINE_API_URL.format(user_id=user_id),
            params=params,
            headers={'Authorization': f'Bearer {bearer_token}'},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return 'Error: Request to X API timed out'
    except requests.exceptions.RequestException as e:
        return f'Error fetching timeline from X API: {e}'

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
        filters = []
        if exclude_replies:
            filters.append('replies excluded')
        if exclude_retweets:
            filters.append('retweets excluded')
        filter_note = f" ({', '.join(filters)})" if filters else ''
        return f'No posts found from @{username}{filter_note}.'

    posts = data['data']
    result_count = data.get('meta', {}).get('result_count', len(posts))

    # Map included users (for referenced tweet authors)
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

    # Build media map
    media_map = {}
    if attach_media:
        for media in data.get('includes', {}).get('media', []):
            media_key = media.get('media_key')
            media_type = media.get('type', '')
            if not media_key:
                continue
            image_url = media.get('url') if media_type == 'photo' else media.get('preview_image_url')
            if image_url:
                media_map[media_key] = {'url': image_url, 'type': media_type}

    # Build verified badge for account
    if user_verified:
        badge = ' \u2713' if user_verified_type == 'blue' else ' \u2611\ufe0f'
    else:
        badge = ''

    lines = [f'Found {result_count} post(s) from @{username}{badge} ({user_followers:,} followers):\n']
    post_media_items = []

    for i, post in enumerate(posts, 1):
        metrics = post.get('public_metrics', {})

        if created_at := post.get('created_at'):
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                timestamp = dt.strftime('%Y-%m-%d %H:%M UTC')
            except (ValueError, TypeError):
                timestamp = created_at
        else:
            timestamp = 'Unknown time'

        # Parse referenced tweets for reply/quote/RT detection
        refs = post.get('referenced_tweets', [])
        reply_to_id = next((r['id'] for r in refs if r.get('type') == 'replied_to'), None)
        quote_of_id = next((r['id'] for r in refs if r.get('type') == 'quoted'), None)
        is_retweet = any(r.get('type') == 'retweeted' for r in refs)

        post_type = ''
        if is_retweet:
            post_type = '[RT] '
        elif reply_to_id:
            post_type = '[Reply] '
        elif quote_of_id:
            post_type = '[Quote] '

        header = f'--- Post {i} {post_type}({timestamp}) ---'
        lines.append(header)
        lines.append(post.get('text', ''))

        # Extract hashtags and mentions
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

        # Show thread info
        if conversation_id := post.get('conversation_id'):
            if conversation_id != post.get('id'):
                lines.append(f'[Thread: {conversation_id}]')

        # Show reply context
        if reply_to_id and (ref_tweet := referenced_tweets_map.get(reply_to_id)):
            ref_author_id = ref_tweet.get('author_id', '')
            ref_author = users_map.get(ref_author_id, {}).get('username', 'unknown')
            ref_text = ref_tweet.get('text', '')[:100]
            if len(ref_tweet.get('text', '')) > 100:
                ref_text += '...'
            lines.append(f'\u21b3 Replying to @{ref_author}: "{ref_text}"')

        # Show quote context
        if quote_of_id and (ref_tweet := referenced_tweets_map.get(quote_of_id)):
            ref_author_id = ref_tweet.get('author_id', '')
            ref_author = users_map.get(ref_author_id, {}).get('username', 'unknown')
            ref_text = ref_tweet.get('text', '')[:100]
            if len(ref_tweet.get('text', '')) > 100:
                ref_text += '...'
            lines.append(f'\u21b3 Quoting @{ref_author}: "{ref_text}"')

        # Collect media
        if attach_media and media_map:
            for media_key in post.get('attachments', {}).get('media_keys', []):
                if media_info := media_map.get(media_key):
                    post_media_items.append((i, username, media_info['type'], media_info['url']))

        lines.extend([
            f"[Likes: {metrics.get('like_count', 0)} | "
            f"Retweets: {metrics.get('retweet_count', 0)} | "
            f"Replies: {metrics.get('reply_count', 0)}]",
            f"Link: https://x.com/{username}/status/{post.get('id', '')}",
            '',
        ])

    # Send media to agent via async message
    if attach_media and post_media_items:
        agent_id = os.environ.get('LETTA_AGENT_ID')
        if agent_id:
            media_labels = []
            image_parts = []
            for post_idx, author, media_type, image_url in post_media_items:
                media_labels.append(f'<media from="@{author}" post="{post_idx}" type="{media_type}" />')
                image_parts.append({
                    'type': 'image',
                    'source': {'type': 'url', 'url': image_url},
                })
            reminder_text = (
                '<system-reminder>'
                f'\nMedia delivery from your get_account_timeline call for @{username}.'
                '\nYou are in SILENT mode \u2014 user cannot see this. Use notify_via_telegram() to share results.'
                f'\n{chr(10).join(media_labels)}'
                '\n</system-reminder>'
            )
            content_parts = [
                {'type': 'text', 'text': reminder_text},
                *image_parts,
            ]

            try:
                client.agents.messages.create_async(
                    agent_id=agent_id,
                    messages=[{'role': 'user', 'content': content_parts}],
                )
                lines.append(f'[Media: {len(post_media_items)} image(s) arriving in next message]')
            except Exception:
                lines.append(f'[Media: failed to attach {len(post_media_items)} image(s)]')

    # Pagination token
    if next_token_value := data.get('meta', {}).get('next_token'):
        lines.append(f'Next page token: {next_token_value}')

    return '\n'.join(lines)
