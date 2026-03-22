"""Get X/Twitter account profile information (batch-capable).

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to look up public profile data for one or more
X/Twitter accounts in a single API call. Use this to check follower counts,
verify account status, read bios, or research accounts before engaging.
"""

import os
from datetime import datetime, timezone

BATCH_API_URL = 'https://api.x.com/2/users/by'
REQUEST_TIMEOUT = 30
MAX_USERNAMES = 100  # X API limit


def _format_user(user: dict, pinned_tweets_map: dict) -> str:
    """Format a single user object into a readable profile string.

    Args:
        user: User data dict from X API response.
        pinned_tweets_map: Mapping of tweet ID to tweet data for pinned tweets.

    Returns:
        Formatted profile string for this user.
    """
    username = user.get('username', '???')
    metrics = user.get('public_metrics', {})
    verified = user.get('verified', False)
    verified_type = user.get('verified_type', '')

    # Build verified badge
    if verified:
        if verified_type == 'blue':
            badge = ' \u2713 (Blue verified)'
        elif verified_type == 'business':
            badge = ' \u2611\ufe0f (Business verified)'
        elif verified_type == 'government':
            badge = ' \u2611\ufe0f (Government verified)'
        else:
            badge = ' \u2611\ufe0f (Verified)'
    else:
        badge = ''

    # Format creation date
    created_at = user.get('created_at', '')
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_str = dt.strftime('%B %d, %Y')
        except (ValueError, TypeError):
            created_str = created_at
    else:
        created_str = 'Unknown'

    lines = [
        f'Account: @{username}{badge}',
        f'Name: {user.get("name", "N/A")}',
        f'Followers: {metrics.get("followers_count", 0):,}',
        f'Following: {metrics.get("following_count", 0):,}',
        f'Posts: {metrics.get("tweet_count", 0):,}',
        f'Listed: {metrics.get("listed_count", 0):,}',
        f'Likes given: {metrics.get("like_count", 0):,}',
        f'Media posted: {metrics.get("media_count", 0):,}',
    ]

    if description := user.get('description', ''):
        lines.append(f'Bio: {description}')

    # Org affiliation
    if affiliation := user.get('affiliation'):
        aff_desc = affiliation.get('description', '')
        if aff_desc:
            lines.append(f'Affiliated with: {aff_desc}')

    if location := user.get('location', ''):
        lines.append(f'Location: {location}')

    # Resolve expanded URL from entities if available
    if entities := user.get('entities', {}):
        url_entities = entities.get('url', {}).get('urls', [])
        if url_entities:
            expanded = url_entities[0].get('expanded_url', '')
            if expanded:
                lines.append(f'Website: {expanded}')
            elif url := user.get('url', ''):
                lines.append(f'Website: {url}')
    elif url := user.get('url', ''):
        lines.append(f'Website: {url}')

    lines.append(f'Created: {created_str}')

    # Account flags
    flags = []
    if user.get('protected'):
        flags.append('Protected (private)')
    if user.get('parody'):
        flags.append('Parody account')
    if user.get('is_identity_verified'):
        flags.append('Identity verified')
    sub_type = user.get('subscription_type', 'None')
    if sub_type and sub_type != 'None':
        flags.append(f'Subscription: {sub_type}')
    if flags:
        lines.append(f'Flags: {", ".join(flags)}')

    lines.append(f'Profile URL: https://x.com/{username}')

    # Show pinned tweet if available
    pinned_id = user.get('pinned_tweet_id')
    if pinned_id and pinned_id in pinned_tweets_map:
        pinned = pinned_tweets_map[pinned_id]
        pinned_text = pinned.get('text', '')[:200]
        if len(pinned.get('text', '')) > 200:
            pinned_text += '...'
        pinned_metrics = pinned.get('public_metrics', {})
        lines.append('')
        lines.append(f'Pinned post: "{pinned_text}"')
        lines.append(
            f'[Likes: {pinned_metrics.get("like_count", 0)} | '
            f'Retweets: {pinned_metrics.get("retweet_count", 0)} | '
            f'Replies: {pinned_metrics.get("reply_count", 0)}]'
        )

    return '\n'.join(lines)


def get_users_info(usernames: list) -> str:
    """Get public profile information for one or more X/Twitter accounts.

    Retrieves account metadata including follower/following counts, bio,
    verification status, location, and account creation date. Accepts up
    to 100 usernames in a single batch API call.

    Environment variables required:
    - X_API_KEY: X/Twitter Bearer Token for API authentication

    Args:
        usernames (list): List of X/Twitter usernames without @ symbol.

    Returns:
        str: Formatted account profile information for all found users.

    Examples:
        get_users_info(usernames=["BakingBad_Dev"])
        get_users_info(usernames=["zksync", "Scroll_ZKP", "TACEO_IO"])
    """
    import requests

    if not (bearer_token := os.environ.get('X_API_KEY')):
        return 'Error: X_API_KEY environment variable is not set'

    # Validate input
    if not usernames or not isinstance(usernames, list):
        return 'Error: usernames must be a non-empty list of strings'

    # Clean and validate each username
    cleaned = []
    for item in usernames:
        if not isinstance(item, str):
            return f'Error: each username must be a string, got {type(item).__name__}'
        name = item.strip().lstrip('@')
        if name:
            cleaned.append(name)

    if not cleaned:
        return 'Error: no valid usernames provided after cleaning'

    if len(cleaned) > MAX_USERNAMES:
        return f'Error: maximum {MAX_USERNAMES} usernames per request (got {len(cleaned)})'

    try:
        response = requests.get(
            BATCH_API_URL,
            headers={'Authorization': f'Bearer {bearer_token}'},
            params={
                'usernames': ','.join(cleaned),
                'user.fields': 'public_metrics,verified,verified_type,description,location,created_at,profile_image_url,url,pinned_tweet_id,affiliation,most_recent_tweet_id,is_identity_verified,parody,subscription_type,entities,protected,profile_banner_url',
                'expansions': 'pinned_tweet_id',
                'tweet.fields': 'text,created_at,public_metrics',
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return 'Error: Request to X API timed out'
    except requests.exceptions.RequestException as e:
        return f'Error fetching user info from X API: {e}'

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

    users = data.get('data', [])
    errors = data.get('errors', [])

    # All users not found
    if not users:
        not_found = [e.get('value', '?') for e in errors]
        return f'Error: No users found. Not found: {", ".join(f"@{u}" for u in not_found)}'

    # Build pinned tweets map: tweet_id -> tweet data
    pinned_tweets_map = {}
    for tweet in data.get('includes', {}).get('tweets', []):
        pinned_tweets_map[tweet.get('id')] = tweet

    # Format each found user
    sections = [_format_user(user, pinned_tweets_map) for user in users]
    result = '\n\n---\n\n'.join(sections)

    # Report not-found usernames at the end
    if errors:
        not_found = [e.get('value', '?') for e in errors if e.get('resource_type') == 'user']
        if not_found:
            result += f'\n\n[Not found: {", ".join(f"@{u}" for u in not_found)}]'

    return result
