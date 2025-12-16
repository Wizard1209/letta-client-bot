"""Merge memory blocks from one Letta agent to another.

Usage:
    uv run python -m devscripts.merge_memory <source_agent_id> <target_agent_id>
    uv run python -m devscripts.merge_memory --auto <source_agent_id> <target_agent_id>

Logic:
    - MERGE: label exists in both agents -> GPT merges values -> update target block
    - ATTACH: label only in source -> attach source block to target, send instruction
    - SKIP: label only in target -> no action

Options:
    --auto: Skip approval prompts and execute all actions automatically

Requires OPENAI_API_KEY env var for GPT merge operations.
"""

import argparse
import difflib
from itertools import islice

from letta_client import APIError
from openai import OpenAI

from devscripts.bootstrap import env, letta

MERGE_PROMPT = """You are a precise text merger. Your task is to merge two text blocks into one.

RULES:
1. PRESERVE all unique information from both blocks
2. DEDUPLICATE identical or near-identical content
3. DO NOT summarize, rephrase, or lose any detail
4. DO NOT add commentary or explanation
5. Maintain original formatting (markdown, lists, etc.)
6. If structure differs, prefer the more organized version
7. Output ONLY the merged text, nothing else

Merge BLOCK A and BLOCK B below:"""

ATTACH_INSTRUCTION = """A new memory block "{label}" has been attached to your core memory.

Please perform these steps:
1. Update memory_index — add the new block "{label}" to your index with an appropriate description
2. Review for duplicates — check if content in "{label}" overlaps with your existing blocks
3. Reconcile — merge or note any overlapping information across blocks"""


def get_openai_client() -> OpenAI:
    """Get sync OpenAI client."""
    return OpenAI(api_key=env('OPENAI_API_KEY'))


def get_agent_blocks(agent_id: str) -> dict[str, dict]:
    """Get blocks for agent as dict keyed by label."""
    try:
        blocks = letta.agents.blocks.list(agent_id=agent_id)
        return {
            b.label: {'id': b.id, 'value': b.value, 'description': b.description}
            for b in blocks
        }
    except APIError as e:
        print(f'  ✗ Failed to get blocks for {agent_id}: {e}')
        return {}


def prompt_approval(message: str) -> bool:
    """Prompt user for approval. Returns True if approved."""
    response = input(f'{message} [y/N]: ').strip().lower()
    return response in ('y', 'yes')


def truncate(text: str, max_len: int = 200) -> str:
    """Truncate text for display."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + '...'


def get_diff(old: str, new: str) -> str:
    """Generate a unified diff between two text strings."""
    if not old.endswith('\n'):
        old += '\n'
    if not new.endswith('\n'):
        new += '\n'

    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile='target (before)',
        tofile='merged (after)',
    )
    # Skip header lines (---, +++, @@)
    return ''.join(islice(diff, 3, None))


def print_diff(diff_text: str, indent: str = '   │  ') -> None:
    """Print diff with colored +/- lines and indentation."""
    if not diff_text.strip():
        print(f'{indent}(no changes)')
        return

    for line in diff_text.splitlines():
        if line.startswith('+'):
            print(f'{indent}\033[32m{line}\033[0m')  # green
        elif line.startswith('-'):
            print(f'{indent}\033[31m{line}\033[0m')  # red
        elif line.startswith('@@'):
            print(f'{indent}\033[36m{line}\033[0m')  # cyan
        else:
            print(f'{indent}{line}')


def merge_with_gpt(
    source_value: str, target_value: str, openai_client: OpenAI
) -> str | None:
    """Merge two block values using GPT."""
    user_content = f"""<block_a>
{source_value}
</block_a>

<block_b>
{target_value}
</block_b>"""

    try:
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': MERGE_PROMPT},
                {'role': 'user', 'content': user_content},
            ],
            temperature=0,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f'  ✗ GPT merge failed: {e}')
        return None


def update_block_value(block_id: str, new_value: str) -> bool:
    """Update a block's value."""
    try:
        letta.blocks.update(block_id=block_id, value=new_value)
        return True
    except APIError as e:
        print(f'  ✗ Failed to update block {block_id}: {e}')
        return False


def attach_block_to_agent(agent_id: str, block_id: str) -> bool:
    """Attach an existing block to an agent."""
    try:
        letta.agents.blocks.attach(agent_id=agent_id, block_id=block_id)
        return True
    except APIError as e:
        print(f'  ✗ Failed to attach block {block_id}: {e}')
        return False


def send_system_message(agent_id: str, message: str) -> bool:
    """Send a system message to agent."""
    try:
        letta.agents.messages.create(
            agent_id=agent_id,
            messages=[{'role': 'system', 'content': message}],
        )
        return True
    except APIError as e:
        print(f'  ✗ Failed to send system message: {e}')
        return False


def main(source_agent_id: str, target_agent_id: str, auto_approve: bool = False) -> None:
    """Merge memory blocks from source to target agent."""
    print(f'\n📦 Memory Merge: {source_agent_id} → {target_agent_id}')
    if auto_approve:
        print('   (Auto-approve mode)')
    print()

    # Step 1: Get blocks from both agents
    print('1. Fetching blocks...')
    source_blocks = get_agent_blocks(source_agent_id)
    target_blocks = get_agent_blocks(target_agent_id)

    if not source_blocks:
        print('  ✗ No source blocks found. Aborting.')
        return

    print(f'   Source blocks: {list(source_blocks.keys())}')
    print(f'   Target blocks: {list(target_blocks.keys())}')

    # Step 2: Categorize blocks
    source_labels = set(source_blocks.keys())
    target_labels = set(target_blocks.keys())

    to_merge = source_labels & target_labels
    to_attach = source_labels - target_labels
    to_skip = target_labels - source_labels

    print('\n2. Plan:')
    print(f'   MERGE ({len(to_merge)}): {list(to_merge) or "none"}')
    print(f'   ATTACH ({len(to_attach)}): {list(to_attach) or "none"}')
    print(f'   SKIP ({len(to_skip)}): {list(to_skip) or "none"}')

    # Initialize counters
    merged_count = 0
    attached_count = 0
    skipped_by_user = 0
    failed_count = 0

    # Step 3: Process MERGE blocks
    if to_merge:
        print('\n3. Merging blocks with GPT...')
        openai_client = get_openai_client()

        for label in to_merge:
            print(f'\n   ┌─ MERGE: {label}')
            source_val = source_blocks[label]['value']
            target_val = target_blocks[label]['value']

            # Skip if values are identical
            if source_val == target_val:
                print('   │  Values identical, skipping')
                print('   └─ ⏭ skipped')
                continue

            # Show preview
            print(f'   │  Source ({len(source_val)} chars): {truncate(source_val)}')
            print(f'   │  Target ({len(target_val)} chars): {truncate(target_val)}')

            # Get approval
            if not auto_approve:
                if not prompt_approval('   │  Merge these blocks?'):
                    print('   └─ ⏭ skipped by user')
                    skipped_by_user += 1
                    continue

            # Perform merge
            print('   │  Calling GPT...', end=' ')
            merged_value = merge_with_gpt(source_val, target_val, openai_client)

            if not merged_value:
                print('\n   └─ ✗ failed')
                failed_count += 1
                continue

            print(f'done ({len(merged_value)} chars)')

            # Show diff: target (before) → merged (after)
            print('   │')
            print('   │  Diff (target → merged):')
            diff_text = get_diff(target_val, merged_value)
            print_diff(diff_text)
            print('   │')

            # Confirm update
            if not auto_approve:
                if not prompt_approval('   │  Apply this merge?'):
                    print('   └─ ⏭ skipped by user')
                    skipped_by_user += 1
                    continue

            # Update block
            print('   │  Updating block...', end=' ')
            if update_block_value(target_blocks[label]['id'], merged_value):
                print('done')
                print('   └─ ✓ merged')
                merged_count += 1
            else:
                print('failed')
                print('   └─ ✗ failed')
                failed_count += 1

    # Step 4: Process ATTACH blocks one by one
    if to_attach:
        print('\n4. Attaching blocks...')

        for label in to_attach:
            print(f'\n   ┌─ ATTACH: {label}')
            block_id = source_blocks[label]['id']
            block_val = source_blocks[label]['value']
            block_desc = source_blocks[label].get('description', 'N/A')

            # Show preview
            print(f'   │  Block ID: {block_id}')
            print(f'   │  Description: {block_desc}')
            print(f'   │  Content ({len(block_val)} chars): {truncate(block_val)}')

            # Get approval
            if not auto_approve:
                if not prompt_approval('   │  Attach this block?'):
                    print('   └─ ⏭ skipped by user')
                    skipped_by_user += 1
                    continue

            # Attach the block
            print('   │  Attaching...', end=' ')
            if not attach_block_to_agent(target_agent_id, block_id):
                print('failed')
                print('   └─ ✗ failed')
                failed_count += 1
                continue
            print('done')

            # Send instruction
            print('   │  Sending instruction to agent...', end=' ')
            instruction = ATTACH_INSTRUCTION.format(label=label)
            if send_system_message(target_agent_id, instruction):
                print('done')
                print('   └─ ✓ attached')
            else:
                print('failed (block attached, instruction failed)')
                print('   └─ ⚠ partial')
            attached_count += 1

    # Summary
    print(f'\n{"=" * 40}')
    print('📊 Summary:')
    print(f'   Merged:          {merged_count}')
    print(f'   Attached:        {attached_count}')
    print(f'   Skipped (target): {len(to_skip)}')
    print(f'   Skipped (user):  {skipped_by_user}')
    print(f'   Failed:          {failed_count}')
    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Merge memory blocks from source agent to target agent'
    )
    parser.add_argument(
        'source_agent_id', help='Source agent ID (blocks will be read from here)'
    )
    parser.add_argument(
        'target_agent_id', help='Target agent ID (blocks will be merged/attached here)'
    )
    parser.add_argument(
        '--auto',
        action='store_true',
        help='Skip approval prompts and execute all actions automatically',
    )
    args = parser.parse_args()
    main(args.source_agent_id, args.target_agent_id, auto_approve=args.auto)
