#!/usr/bin/env python3
"""Direct API call to check identities."""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('LETTA_API_KEY')
project = os.getenv('LETTA_PROJECT')

# Letta API base URL
base_url = 'https://api.letta.com'

headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}

# Get project_id (same pattern as agent.py:325-334)
print(f'Fetching project_id for project: {project}...\n')
projects_response = httpx.get(
    f'{base_url}/v1/projects',
    headers=headers,
    params={'name': project}
)

if projects_response.status_code != 200:
    print(f'Failed to fetch project: {projects_response.status_code}')
    print(f'Response: {projects_response.text}')
    exit(1)

projects_data = projects_response.json()
projects_list = projects_data.get('projects', [])

if len(projects_list) == 0:
    print(f'Project "{project}" not found')
    exit(1)

if len(projects_list) > 1:
    print(f'Warning: Multiple projects found with name "{project}"')

project_id = projects_list[0]['id']
print(f'Found project_id: {project_id}\n')

# List identities without explicit project_id
print('Fetching identities from API (no project_id param)...\n')
response = httpx.get(
    f'{base_url}/v1/identities',
    headers=headers
)

print(f'Status: {response.status_code}')
print(f'Response: {response.text[:500]}...\n')

if response.status_code == 200:
    data = response.json()
    print(f'Type: {type(data)}')
    print(f'Keys: {data.keys() if isinstance(data, dict) else "N/A"}')

    if isinstance(data, dict) and 'identities' in data:
        identities = data['identities']
        print(f'\nFound {len(identities)} identities:')
        for identity in identities[:5]:  # Show first 5
            print(f'  - {identity.get("id")}: {identity.get("identifier_key")}')
    elif isinstance(data, list):
        print(f'\nFound {len(data)} identities:')
        for identity in data[:5]:
            print(f'  - {identity.get("id")}: {identity.get("identifier_key")}')
