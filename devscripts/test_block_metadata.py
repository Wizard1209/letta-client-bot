"""Test block metadata create/read/update operations.

Usage:
    uv run python -m devscripts.test_block_metadata <agent_id>

This script tests:
1. Create a block with metadata
2. Read block and verify metadata
3. Update block with new metadata
4. Read again and verify update worked
5. Cleanup (delete test block)
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from letta_client import Letta

# Load .env from project root
load_dotenv()

# Constants
TEST_BLOCK_LABEL = 'test_metadata_block'
TEST_BLOCK_VALUE = 'Test block content'
INITIAL_VERSION = '1.0.0'
UPDATED_VERSION = '2.0.0'


def get_client() -> Letta:
    """Create sync Letta client from env."""
    api_key = os.getenv('LETTA_API_KEY')
    project_id = os.getenv('LETTA_PROJECT_ID')
    if not api_key:
        print('❌ LETTA_API_KEY not found in environment')
        sys.exit(1)
    if not project_id:
        print('❌ LETTA_PROJECT_ID not found in environment')
        sys.exit(1)
    return Letta(api_key=api_key, project_id=project_id)


def test_block_metadata(agent_id: str) -> None:
    """Test block metadata operations."""
    client = get_client()

    print(f'\n📋 Testing block metadata for agent: {agent_id}\n')

    # Step 1: Create block with metadata
    print('1️⃣  Creating block with metadata...')
    try:
        block = client.blocks.create(
            label=TEST_BLOCK_LABEL,
            value=TEST_BLOCK_VALUE,
            description='Test block for metadata verification',
            metadata={'version': INITIAL_VERSION, 'test': True},
        )
        print(f'   ✅ Created block: {block.id}')
        print(f'   📦 Response metadata field: {block.metadata}')
    except Exception as e:
        print(f'   ❌ Failed to create block: {e}')
        return

    block_id = block.id

    # Step 2: Read block and verify metadata
    print('\n2️⃣  Reading block back...')
    try:
        read_block = client.blocks.retrieve(block_id=block_id)
        print(f'   📦 Read metadata: {read_block.metadata}')

        if read_block.metadata:
            version = read_block.metadata.get('version')
            print(f'   📌 Version from metadata: {version}')
            if version == INITIAL_VERSION:
                print(f'   ✅ Version matches: {version}')
            else:
                print(f'   ❌ Version mismatch! Expected {INITIAL_VERSION}, got {version}')
        else:
            print('   ❌ metadata is None or empty!')
    except Exception as e:
        print(f'   ❌ Failed to read block: {e}')

    # Step 3: Attach to agent
    print(f'\n3️⃣  Attaching block to agent {agent_id}...')
    try:
        client.agents.blocks.attach(agent_id=agent_id, block_id=block_id)
        print('   ✅ Attached')
    except Exception as e:
        print(f'   ❌ Failed to attach: {e}')

    # Step 4: List agent blocks and find our block
    print('\n4️⃣  Listing agent blocks to verify metadata...')
    try:
        found = False
        for b in client.agents.blocks.list(agent_id=agent_id):
            if b.label == TEST_BLOCK_LABEL:
                found = True
                print(f'   📦 Found block, metadata: {b.metadata}')
                if b.metadata:
                    version = b.metadata.get('version')
                    print(f'   📌 Version: {version}')
                else:
                    print('   ❌ metadata is None on listed block!')
                break
        if not found:
            print('   ❌ Block not found in agent blocks!')
    except Exception as e:
        print(f'   ❌ Failed to list blocks: {e}')

    # Step 5: Update block with new metadata
    print(f'\n5️⃣  Updating block metadata to version {UPDATED_VERSION}...')
    try:
        updated_block = client.blocks.update(
            block_id=block_id,
            metadata={'version': UPDATED_VERSION, 'test': True, 'updated': True},
        )
        print(f'   📦 Updated response metadata: {updated_block.metadata}')
    except Exception as e:
        print(f'   ❌ Failed to update block: {e}')

    # Step 6: Read again and verify update
    print('\n6️⃣  Reading block after update...')
    try:
        final_block = client.blocks.retrieve(block_id=block_id)
        print(f'   📦 Final metadata: {final_block.metadata}')

        if final_block.metadata:
            version = final_block.metadata.get('version')
            print(f'   📌 Version: {version}')
            if version == UPDATED_VERSION:
                print(f'   ✅ Update successful! Version is now {version}')
            else:
                print(f'   ❌ Update failed! Expected {UPDATED_VERSION}, got {version}')
        else:
            print('   ❌ metadata is None after update!')
    except Exception as e:
        print(f'   ❌ Failed to read block: {e}')

    # Cleanup
    print('\n🧹 Cleaning up...')
    try:
        client.agents.blocks.detach(agent_id=agent_id, block_id=block_id)
        print('   ✅ Detached from agent')
    except Exception as e:
        print(f'   ⚠️  Failed to detach: {e}')

    try:
        client.blocks.delete(block_id=block_id)
        print('   ✅ Deleted block')
    except Exception as e:
        print(f'   ⚠️  Failed to delete: {e}')

    print('\n✨ Test complete!\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test block metadata operations')
    parser.add_argument('agent_id', help='Agent ID to test with')
    args = parser.parse_args()
    test_block_metadata(args.agent_id)
