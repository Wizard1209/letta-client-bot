"""General X/Twitter API v2 wrapper for flexible endpoint access.

NOTE: This file is excluded from linting/formatting and designed to be
loaded as a Letta custom tool via source_code registration.

This tool enables agents to make direct X API v2 calls when specific tools
don't exist yet. Use for experimentation, one-off queries, or accessing
endpoints not covered by other tools.
"""

import json
import os

API_BASE = 'https://api.x.com/2'
REQUEST_TIMEOUT = 30
MAX_RESPONSE_LENGTH = 4000


def x_api_request(
    endpoint: str,
    params: str = '',
    method: str = 'GET',
) -> str:
    """Make a direct request to any X API v2 endpoint.

    Flexible wrapper for X API v2 calls. Use when specific tools don't cover
    your needs, or for exploring new endpoints and experimenting with parameters.

    Environment variables required:
    - X_API_KEY: X/Twitter Bearer Token for API authentication

    Args:
        endpoint (str): API endpoint path (without base URL). Examples:
            - "users/by/username/BakingBad_Dev"
            - "tweets/search/recent"
            - "users/123456/tweets"
            - "tweets/123456789"
            - "tweets/counts/recent"

        params (str): Query parameters as JSON string. Examples:
            - '{"user.fields": "public_metrics,description"}'
            - '{"query": "from:BakingBad_Dev", "max_results": 10}'
            - '' (empty string for no params, this is the default)

        method (str): HTTP method - "GET" (default) or "POST".
            Most X API v2 read endpoints use GET.

    Returns:
        str: Formatted JSON response from the API (truncated if very large)

    Examples:
        x_api_request("users/by/username/BakingBad_Dev", '{"user.fields": "public_metrics,description"}')
        x_api_request("tweets/search/recent", '{"query": "tezos", "max_results": 10}')
        x_api_request("tweets/123456789", '{"tweet.fields": "public_metrics,created_at"}')
        x_api_request("tweets/counts/recent", '{"query": "from:BakingBad_Dev"}')
    """
    import requests

    if not (bearer_token := os.environ.get('X_API_KEY')):
        return 'Error: X_API_KEY environment variable is not set'

    if not endpoint or not (endpoint := endpoint.strip().lstrip('/')):
        return 'Error: endpoint is required and cannot be empty'

    if method not in ('GET', 'POST'):
        return f'Error: method must be "GET" or "POST", got "{method}"'

    # Parse params - accepts dict, JSON string, or Python dict repr
    query_params = {}
    if params:
        if isinstance(params, dict):
            query_params = params
        elif isinstance(params, str) and params.strip():
            raw = params.strip()
            # Try JSON first
            try:
                query_params = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                # Fallback: Python dict repr uses single quotes — convert to JSON
                try:
                    import ast
                    query_params = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    return f'Error: Could not parse params as JSON or Python dict: {raw[:100]}'
            if not isinstance(query_params, dict):
                return 'Error: params must be a dict, not a list or primitive'

    url = f'{API_BASE}/{endpoint}'
    headers = {'Authorization': f'Bearer {bearer_token}'}

    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, params=query_params, timeout=REQUEST_TIMEOUT)
        else:
            headers['Content-Type'] = 'application/json'
            response = requests.post(url, headers=headers, json=query_params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return f'Error: Request to {url} timed out'
    except requests.exceptions.RequestException as e:
        return f'Error making request to X API: {e}'

    # Build response info
    lines = [
        f'Endpoint: {method} /2/{endpoint}',
        f'Status: {response.status_code}',
    ]

    # Parse and format response body
    try:
        data = response.json()
        formatted = json.dumps(data, indent=2, ensure_ascii=False)

        if len(formatted) > MAX_RESPONSE_LENGTH:
            formatted = formatted[:MAX_RESPONSE_LENGTH] + '\n... [truncated]'

        lines.append(f'Response:\n{formatted}')

        # Add helpful metadata
        if meta := data.get('meta'):
            if result_count := meta.get('result_count'):
                lines.append(f'\nResult count: {result_count}')
            if next_token := meta.get('next_token'):
                lines.append(f'Next page token: {next_token}')

    except (ValueError, KeyError):
        # Not JSON - return raw text
        text = response.text[:MAX_RESPONSE_LENGTH]
        if len(response.text) > MAX_RESPONSE_LENGTH:
            text += '\n... [truncated]'
        lines.append(f'Response (raw):\n{text}')

    return '\n'.join(lines)
