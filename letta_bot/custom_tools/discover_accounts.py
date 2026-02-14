"""Discover related X/Twitter accounts via multiple exploration methods.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to break out of echo chambers by exploring account
relationships through multiple discovery methods: who amplifies content,
who discusses it, who shares list memberships, and who mentions the account.
"""

import os
from datetime import datetime, timezone

API_BASE = 'https://api.x.com/2'
USER_FIELDS = 'public_metrics,verified,verified_type,description,created_at,affiliation,entities,location'
REQUEST_TIMEOUT = 30


def _api_get(endpoint, params, bearer_token):
    """Make authenticated GET request to X API v2."""
    import requests

    try:
        response = requests.get(
            f'{API_BASE}/{endpoint}',
            headers={'Authorization': f'Bearer {bearer_token}'},
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return None, 'Error: Request to X API timed out'
    except requests.exceptions.RequestException as e:
        return None, f'Error: {e}'

    if response.status_code != 200:
        # Provide helpful error for known issues
        try:
            err = response.json()
            if err.get('reason') == 'client-not-enrolled':
                return None, 'Error: This method requires elevated API enrollment. Check X Developer Portal project settings.'
            if 'Unsupported Authentication' in err.get('detail', ''):
                return None, 'Error: This method requires OAuth 2.0 User Context (not App-Only Bearer Token).'
        except Exception:
            pass
        return None, f'Error: X API returned status {response.status_code} - {response.text[:200]}'

    data = response.json()
    if data.get('errors') and not data.get('data'):
        return None, f'Error: {data["errors"][0].get("detail", "Unknown error")}'

    return data, None


def _resolve_user(username, bearer_token):
    """Resolve username to user ID and basic info."""
    data, error = _api_get(
        f'users/by/username/{username}',
        {'user.fields': 'public_metrics,verified,verified_type'},
        bearer_token,
    )
    if error:
        return None, error
    if not data.get('data'):
        return None, f'Error: User @{username} not found'
    return data['data'], None


def _format_account(idx, acc, connection_note=''):
    """Format a single account entry for output."""
    username = acc.get('username', 'unknown')
    name = acc.get('name', '')
    metrics = acc.get('public_metrics', {})
    followers = metrics.get('followers_count', 0)
    following = metrics.get('following_count', 0)
    tweets = metrics.get('tweet_count', 0)
    likes_given = metrics.get('like_count', 0)
    media = metrics.get('media_count', 0)
    verified = acc.get('verified', False)
    verified_type = acc.get('verified_type', '')

    if verified:
        badge = ' \u2713' if verified_type == 'blue' else ' \u2611\ufe0f'
    else:
        badge = ''

    lines = [f'{idx}. @{username}{badge} ({followers:,} followers)']

    if name and name != username:
        lines.append(f'   Name: {name}')

    # Affiliation (org ties)
    if affiliation := acc.get('affiliation'):
        aff_desc = affiliation.get('description', '')
        if aff_desc:
            lines.append(f'   Org: {aff_desc}')

    if description := acc.get('description', ''):
        if len(description) > 160:
            description = description[:160] + '...'
        lines.append(f'   Bio: {description}')

    if location := acc.get('location', ''):
        lines.append(f'   Location: {location}')

    # Activity metrics
    activity_parts = [f'Following: {following:,}', f'Posts: {tweets:,}']
    if likes_given:
        activity_parts.append(f'Likes given: {likes_given:,}')
    if media:
        activity_parts.append(f'Media: {media:,}')
    lines.append(f'   {" | ".join(activity_parts)}')

    # Website from entities
    if entities := acc.get('entities', {}):
        url_entities = entities.get('url', {}).get('urls', [])
        if url_entities:
            expanded = url_entities[0].get('expanded_url', url_entities[0].get('display_url', ''))
            if expanded:
                lines.append(f'   Web: {expanded}')

    if connection_note:
        lines.append(f'   Connection: {connection_note}')

    lines.append('')
    return lines


def _filter_and_sort(accounts, min_followers):
    """Filter by min_followers and sort by follower count desc."""
    if min_followers > 0:
        accounts = [
            a for a in accounts
            if a.get('public_metrics', {}).get('followers_count', 0) >= min_followers
        ]
    accounts.sort(
        key=lambda a: a.get('public_metrics', {}).get('followers_count', 0),
        reverse=True,
    )
    return accounts


def _discover_retweeted_by(user_id, seed, bearer_token, max_results, min_followers):
    """Discover accounts that retweet the seed's content."""
    # Step 1: Get seed's recent posts sorted by retweet count
    data, error = _api_get(
        f'users/{user_id}/tweets',
        {
            'max_results': 10,
            'tweet.fields': 'public_metrics',
            'exclude': 'retweets,replies',
        },
        bearer_token,
    )
    if error:
        return error

    posts = data.get('data', [])
    if not posts:
        return f'No original posts found from @{seed} to analyze retweeters.'

    # Sort by retweet_count to find most amplified posts
    posts.sort(key=lambda p: p.get('public_metrics', {}).get('retweet_count', 0), reverse=True)

    # Step 2: Get retweeters from top post(s)
    seen_ids = set()
    all_accounts = []

    for post in posts[:3]:  # Check top 3 posts
        rt_count = post.get('public_metrics', {}).get('retweet_count', 0)
        if rt_count == 0:
            continue

        post_id = post['id']
        rt_data, rt_error = _api_get(
            f'tweets/{post_id}/retweeted_by',
            {'user.fields': USER_FIELDS, 'max_results': min(max_results, 100)},
            bearer_token,
        )
        if rt_error:
            continue

        for acc in rt_data.get('data', []):
            if acc['id'] not in seen_ids:
                seen_ids.add(acc['id'])
                acc['_connection'] = f'Retweeted post ({rt_count} RTs total)'
                all_accounts.append(acc)

        if len(all_accounts) >= max_results:
            break

    if not all_accounts:
        return f'No retweeters found for @{seed}\'s recent posts.'

    filtered = _filter_and_sort(all_accounts, min_followers)
    if not filtered:
        return f'No retweeters found meeting {min_followers}+ followers threshold.'

    lines = [f'Discovered {len(filtered)} account(s) retweeting @{seed}\'s content:\n']
    for i, acc in enumerate(filtered[:max_results], 1):
        lines.extend(_format_account(i, acc, acc.get('_connection', '')))

    return '\n'.join(lines)


def _discover_quote_tweets(user_id, seed, bearer_token, max_results, min_followers):
    """Discover accounts that quote-tweet the seed's content."""
    # Step 1: Get seed's recent posts sorted by quote count
    data, error = _api_get(
        f'users/{user_id}/tweets',
        {
            'max_results': 10,
            'tweet.fields': 'public_metrics',
            'exclude': 'retweets,replies',
        },
        bearer_token,
    )
    if error:
        return error

    posts = data.get('data', [])
    if not posts:
        return f'No original posts found from @{seed} to analyze quoters.'

    # Sort by quote_count
    posts.sort(key=lambda p: p.get('public_metrics', {}).get('quote_count', 0), reverse=True)

    # Step 2: Get quote tweets from top post(s) and extract authors
    seen_ids = set()
    all_accounts = []

    for post in posts[:3]:
        qt_count = post.get('public_metrics', {}).get('quote_count', 0)
        if qt_count == 0:
            continue

        post_id = post['id']
        qt_data, qt_error = _api_get(
            f'tweets/{post_id}/quote_tweets',
            {
                'expansions': 'author_id',
                'user.fields': USER_FIELDS,
                'tweet.fields': 'public_metrics',
                'max_results': max(10, min(max_results, 100)),  # API minimum is 10
            },
            bearer_token,
        )
        if qt_error:
            continue

        users_map = {
            u['id']: u for u in qt_data.get('includes', {}).get('users', [])
        }

        for qt in qt_data.get('data', []):
            author_id = qt.get('author_id', '')
            if author_id and author_id not in seen_ids and author_id in users_map:
                seen_ids.add(author_id)
                acc = users_map[author_id]
                qt_text = qt.get('text', '')[:80]
                acc['_connection'] = f'Quoted post ({qt_count} quotes total): "{qt_text}..."'
                all_accounts.append(acc)

        if len(all_accounts) >= max_results:
            break

    if not all_accounts:
        return f'No quote tweets found for @{seed}\'s recent posts.'

    filtered = _filter_and_sort(all_accounts, min_followers)
    if not filtered:
        return f'No quoters found meeting {min_followers}+ followers threshold.'

    lines = [f'Discovered {len(filtered)} account(s) quoting @{seed}\'s content:\n']
    for i, acc in enumerate(filtered[:max_results], 1):
        lines.extend(_format_account(i, acc, acc.get('_connection', '')))

    return '\n'.join(lines)


def _discover_list_peers(user_id, seed, bearer_token, max_results, min_followers):
    """Discover accounts that share X Lists with the seed account."""
    # Step 1: Get lists the seed account is on
    list_data, error = _api_get(
        f'users/{user_id}/list_memberships',
        {'list.fields': 'description,member_count,follower_count,owner_id', 'max_results': 20},
        bearer_token,
    )
    if error:
        return error

    lists = list_data.get('data', [])
    if not lists:
        return f'@{seed} is not a member of any public X Lists.'

    # Sort lists by member_count (smaller lists = more curated, higher signal)
    lists.sort(key=lambda l: l.get('member_count', 0))

    # Step 2: Get members from best lists (small curated > large generic)
    seen_ids = {user_id}  # Exclude seed account
    all_accounts = []
    lists_used = []

    for lst in lists:
        member_count = lst.get('member_count', 0)
        # Skip very large lists (generic) and tiny lists (1-2 members)
        if member_count > 200 or member_count < 3:
            continue

        list_id = lst['id']
        list_name = lst.get('name', 'unnamed')
        members_data, members_error = _api_get(
            f'lists/{list_id}/members',
            {'user.fields': USER_FIELDS, 'max_results': min(100, max_results * 2)},
            bearer_token,
        )
        if members_error:
            continue

        lists_used.append(f'"{list_name}" ({member_count} members)')

        for acc in members_data.get('data', []):
            if acc['id'] not in seen_ids:
                seen_ids.add(acc['id'])
                acc['_connection'] = f'Co-member of list "{list_name}" ({member_count} members)'
                all_accounts.append(acc)

        if len(all_accounts) >= max_results * 2:
            break

    if not all_accounts:
        return f'No list peers found for @{seed}. Lists checked: {len(lists)}'

    filtered = _filter_and_sort(all_accounts, min_followers)
    if not filtered:
        return f'No list peers found meeting {min_followers}+ followers threshold.'

    lines = [
        f'Discovered {len(filtered)} account(s) sharing lists with @{seed}',
        f'Lists analyzed: {", ".join(lists_used[:5])}',
        '',
    ]
    for i, acc in enumerate(filtered[:max_results], 1):
        lines.extend(_format_account(i, acc, acc.get('_connection', '')))

    return '\n'.join(lines)


def _discover_mentions(seed, bearer_token, max_results, min_followers):
    """Discover accounts that mention the seed account in posts."""
    from datetime import timedelta

    start_time = datetime.now(timezone.utc) - timedelta(hours=168)

    data, error = _api_get(
        'tweets/search/recent',
        {
            'query': f'@{seed} -from:{seed} -is:retweet',
            'start_time': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'max_results': min(max_results * 3, 100),  # Fetch extra for dedup
            'sort_order': 'relevancy',
            'tweet.fields': 'public_metrics,author_id,created_at',
            'expansions': 'author_id',
            'user.fields': USER_FIELDS,
        },
        bearer_token,
    )
    if error:
        return error

    if not data.get('data'):
        return f'No mentions of @{seed} found in the last 7 days.'

    # Build users map from includes
    users_map = {
        u['id']: u for u in data.get('includes', {}).get('users', [])
    }

    # Deduplicate by author, keep most engaged post
    seen_ids = set()
    all_accounts = []

    for post in data.get('data', []):
        author_id = post.get('author_id', '')
        if not author_id or author_id in seen_ids or author_id not in users_map:
            continue
        seen_ids.add(author_id)

        acc = users_map[author_id]
        post_text = post.get('text', '')[:80]
        post_likes = post.get('public_metrics', {}).get('like_count', 0)
        acc['_connection'] = f'Mentioned @{seed}: "{post_text}..." ({post_likes} likes)'
        all_accounts.append(acc)

    if not all_accounts:
        return f'No unique accounts found mentioning @{seed}.'

    filtered = _filter_and_sort(all_accounts, min_followers)
    if not filtered:
        return f'No mentioners found meeting {min_followers}+ followers threshold.'

    lines = [f'Discovered {len(filtered)} account(s) mentioning @{seed} (last 7 days):\n']
    for i, acc in enumerate(filtered[:max_results], 1):
        lines.extend(_format_account(i, acc, acc.get('_connection', '')))

    return '\n'.join(lines)


def _discover_followers(user_id, seed, bearer_token, max_results, min_followers, direction):
    """Discover accounts via follower/following relationship."""
    endpoint = f'users/{user_id}/{"followers" if direction == "followers" else "following"}'
    label = 'following' if direction == 'following' else 'followers of'

    data, error = _api_get(
        endpoint,
        {'user.fields': USER_FIELDS, 'max_results': min(max_results * 2, 1000)},
        bearer_token,
    )
    if error:
        return error

    accounts = data.get('data', [])
    if not accounts:
        return f'No {direction} found for @{seed}.'

    filtered = _filter_and_sort(accounts, min_followers)
    if not filtered:
        return f'No {direction} found meeting {min_followers}+ followers threshold.'

    total = len(accounts)
    shown = len(filtered[:max_results])
    lines = [
        f'Discovered {shown} account(s) {label} @{seed} '
        f'[from {total} fetched, {len(filtered)} after filtering]:\n'
    ]
    for i, acc in enumerate(filtered[:max_results], 1):
        conn = f'{"Follows" if direction == "followers" else "Followed by"} @{seed}'
        lines.extend(_format_account(i, acc, conn))

    if next_token := data.get('meta', {}).get('next_token'):
        lines.append(f'Next page token: {next_token}')

    return '\n'.join(lines)


def discover_accounts(
    seed_account: str,
    method: str = 'following',
    max_results: int = 20,
    min_followers: int = 100,
) -> str:
    """Discover accounts related to a seed account through multiple methods.

    Explores account relationships via content engagement, list memberships,
    and mentions. Each method reveals different relationship types, helping
    you find new accounts in the same space and break out of echo chambers.

    Environment variables required:
    - X_API_KEY: X/Twitter Bearer Token for API authentication

    Args:
        seed_account (str): Username to explore (without @). Example: "aztecnetwork"

        method (str): Discovery method. Options:
            - "following" (default): Accounts the seed follows. Usually curated
                and high-quality — reveals who the seed considers worth tracking.
                Best starting point for discovering peers and influences.
            - "list_peers": Accounts on the same curated X Lists as the seed.
                Finds peers grouped by topic experts. Checks lists the seed
                belongs to, then gets other members. Prioritizes small curated
                lists (3-200 members) over large generic ones.
            - "quote_tweets": Accounts that quote-tweet the seed's posts.
                Finds engaged discussants who add commentary. Higher-quality
                signal than retweets since it requires original thought.
            - "retweeted_by": Accounts that retweet the seed's posts.
                Finds amplifiers and supporters. Gets seed's most retweeted
                recent posts, then retrieves who retweeted them.
            - "mentions": Accounts that mention the seed in their posts (last 7 days).
                Finds accounts actively engaging with or discussing the seed.
                Excludes the seed's own posts and retweets.
            - "followers": Accounts that follow the seed. Broad but noisy —
                includes bots and low-quality accounts. Use min_followers to filter.

        max_results (int): Maximum accounts to return (default: 20, max: 50).
            Actual results may be less due to deduplication and filtering.

        min_followers (int): Minimum follower count to include (default: 100).
            Set to 0 to include all. Helps filter bots and inactive accounts.

    Returns:
        str: Formatted list of discovered accounts with profile details including:
            - Follower count, verification status, org affiliation
            - Bio, location, website
            - Activity metrics (following, posts, likes given, media count)
            - How they're connected to the seed account

    Examples:
        discover_accounts("aztecnetwork")
        discover_accounts("aztecnetwork", method="quote_tweets", min_followers=500)
        discover_accounts("BakingBad_Dev", method="list_peers")
        discover_accounts("aztecnetwork", method="mentions", max_results=30)
        discover_accounts("aztecnetwork", method="followers", min_followers=1000)
        discover_accounts("aztecnetwork", method="following")
    """
    if not (bearer_token := os.environ.get('X_API_KEY')):
        return 'Error: X_API_KEY environment variable is not set'

    if not seed_account or not (seed_account := seed_account.strip().lstrip('@')):
        return 'Error: seed_account is required and cannot be empty'

    valid_methods = ('retweeted_by', 'quote_tweets', 'list_peers', 'mentions', 'followers', 'following')
    if method not in valid_methods:
        return f'Error: method must be one of {valid_methods}, got "{method}"'

    max_results = max(5, min(50, max_results))

    # Mentions method doesn't need user_id resolution
    if method == 'mentions':
        return _discover_mentions(seed_account, bearer_token, max_results, min_followers)

    # All other methods need user_id
    user_data, error = _resolve_user(seed_account, bearer_token)
    if error:
        return error
    user_id = user_data['id']

    if method == 'retweeted_by':
        return _discover_retweeted_by(user_id, seed_account, bearer_token, max_results, min_followers)
    elif method == 'quote_tweets':
        return _discover_quote_tweets(user_id, seed_account, bearer_token, max_results, min_followers)
    elif method == 'list_peers':
        return _discover_list_peers(user_id, seed_account, bearer_token, max_results, min_followers)
    elif method in ('followers', 'following'):
        return _discover_followers(user_id, seed_account, bearer_token, max_results, min_followers, method)

    return f'Error: Unknown method "{method}"'
