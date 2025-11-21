"""Comprehensive pagination testing for Letta SDK v1.0.

This script demonstrates all pagination patterns and verifies data integrity.
"""

import asyncio
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_pagination_patterns() -> None:
    """Test all pagination patterns with real API calls."""
    from letta_client import AsyncLetta

    # Read API key and project from .env
    env_file = Path(__file__).parent.parent / '.env'
    api_key = None
    project = None

    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith('LETTA_API_KEY='):
                api_key = line.split('=', 1)[1].strip()
            elif line.startswith('LETTA_PROJECT_ID='):
                project = line.split('=', 1)[1].strip()

    if not api_key or not project:
        print('❌ LETTA_API_KEY or LETTA_PROJECT_ID not found in .env')
        return

    client = AsyncLetta(api_key=api_key, project_id=project)

    print('=' * 70)
    print('LETTA SDK v1.0 PAGINATION PATTERNS')
    print('=' * 70)
    print()

    # Pattern 1: Single page access (most common in our codebase)
    print('📄 PATTERN 1: Single Page Access')
    print('-' * 70)
    print('Use case: Get first page of results (default limit)')
    print()
    print('Code:')
    print('    page = await client.identities.list()')
    print('    for identity in page.items:')
    print('        print(identity.id)')
    print()

    try:
        page = await client.identities.list()
        print(f'✓ Retrieved {len(page.items)} identities on first page')
        print(f'  Has next page: {page.has_next_page()}')
        if page.items:
            print(f'  First item ID: {page.items[0].id}')
            print(f'  Last item ID: {page.items[-1].id}')
    except Exception as e:
        print(f'✗ Error: {e}')
    print()

    # Pattern 2: Single page with limit
    print('📄 PATTERN 2: Single Page with Custom Limit')
    print('-' * 70)
    print('Use case: Get specific number of items (e.g., latest 5 agents)')
    print()
    print('Code:')
    print('    page = await client.identities.list(limit=5, order="desc")')
    print('    for identity in page.items:')
    print('        print(identity.id)')
    print()

    try:
        page = await client.identities.list(limit=5, order='desc')
        print(f'✓ Retrieved {len(page.items)} identities (limit=5)')
        print(f'  Has next page: {page.has_next_page()}')
    except Exception as e:
        print(f'✗ Error: {e}')
    print()

    # Pattern 3: Manual page iteration
    print('📄 PATTERN 3: Manual Multi-Page Iteration')
    print('-' * 70)
    print('Use case: Process pages individually with full control')
    print()
    print('Code:')
    print('    page = await client.identities.list(limit=2)')
    print('    all_ids = []')
    print('    async for current_page in page.iter_pages():')
    print('        all_ids.extend([i.id for i in current_page.items])')
    print('        print(f"Processed page with {len(current_page.items)} items")')
    print()

    try:
        page = await client.identities.list(limit=2)
        all_ids = []
        page_count = 0
        async for current_page in page.iter_pages():
            all_ids.extend([i.id for i in current_page.items])
            page_count += 1
            print(f'  Page {page_count}: {len(current_page.items)} items')
            if page_count >= 3:  # Limit for demo
                print('  (stopping after 3 pages for demo)')
                break

        print(f'✓ Collected {len(all_ids)} total identities across {page_count} pages')
    except Exception as e:
        print(f'✗ Error: {e}')
    print()

    # Pattern 4: Automatic iteration over all items
    print('📄 PATTERN 4: Automatic Iteration (ALL Items Across ALL Pages)')
    print('-' * 70)
    print('Use case: Process every single item without worrying about pagination')
    print()
    print('Code:')
    print('    paginator = client.identities.list(limit=2)')
    print('    all_ids = []')
    print('    async for identity in paginator:')
    print('        all_ids.append(identity.id)')
    print()
    print('⚠️  IMPORTANT: This automatically fetches ALL pages!')
    print()

    try:
        paginator = client.identities.list(limit=2)
        all_ids = []
        count = 0
        async for identity in paginator:
            all_ids.append(identity.id)
            count += 1
            if count >= 6:  # Limit for demo
                print('  (stopping after 6 items for demo)')
                break

        print(f'✓ Collected {len(all_ids)} identities via auto-iteration')
    except Exception as e:
        print(f'✗ Error: {e}')
    print()

    # Pattern 5: Verify no data loss with pagination
    print('📄 PATTERN 5: Data Integrity Test')
    print('-' * 70)
    print('Use case: Verify no items are lost during pagination')
    print()

    try:
        # Get all via single call (if available)
        full_page = await client.identities.list(limit=100)
        full_set = {i.id for i in full_page.items}

        # Get all via pagination
        paginated_set = set()
        page = await client.identities.list(limit=2)
        page_num = 0
        async for current_page in page.iter_pages():
            page_num += 1
            paginated_set.update(i.id for i in current_page.items)
            print(f'  Page {page_num}: collected {len(current_page.items)} items')
            if len(paginated_set) >= len(full_set):
                break

        print()
        print(f'Full list:    {len(full_set)} items')
        print(f'Paginated:    {len(paginated_set)} items')
        print(f'Missing:      {len(full_set - paginated_set)} items')
        print(f'Extra:        {len(paginated_set - full_set)} items')

        if full_set == paginated_set:
            print('✓ ✓ ✓ NO DATA LOSS - All items retrieved correctly!')
        else:
            print('✗ DATA MISMATCH DETECTED')
            if full_set - paginated_set:
                print(f'  Missing IDs: {full_set - paginated_set}')
            if paginated_set - full_set:
                print(f'  Extra IDs: {paginated_set - full_set}')

    except Exception as e:
        print(f'✗ Error: {e}')
    print()

    # Pattern 6: Cursor-based pagination (after/before)
    print('📄 PATTERN 6: Cursor-Based Pagination (Manual Control)')
    print('-' * 70)
    print('Use case: Resume from specific point or implement custom pagination')
    print()
    print('Code:')
    print('    # Get first page')
    print('    page1 = await client.identities.list(limit=2, order="asc")')
    print('    last_id = page1.items[-1].id')
    print('    ')
    print('    # Get next page starting after last_id')
    print('    page2 = await client.identities.list(limit=2, after=last_id, order="asc")')
    print()

    try:
        # Get first page
        page1 = await client.identities.list(limit=2, order='asc')
        if page1.items:
            print(f'  Page 1: {len(page1.items)} items')
            for item in page1.items:
                print(f'    - {item.id}')

            last_id = page1.items[-1].id

            # Get next page
            page2 = await client.identities.list(limit=2, after=last_id, order='asc')
            print(f'  Page 2 (after={last_id}): {len(page2.items)} items')
            for item in page2.items:
                print(f'    - {item.id}')

            print('✓ Cursor-based pagination working correctly')
        else:
            print('  No items to paginate')

    except Exception as e:
        print(f'✗ Error: {e}')
    print()

    print('=' * 70)
    print('SUMMARY: How Pagination Works in Letta SDK v1.0')
    print('=' * 70)
    print()
    print('1. SAFE PATTERNS (No data loss):')
    print('   • Single page: page = await client.list() → use page.items')
    print('   • Auto-iterate: async for item in client.list() → gets ALL items')
    print('   • Manual pages: async for page in (await client.list()).iter_pages()')
    print()
    print('2. PAGINATION MECHANISM:')
    print('   • Cursor-based using item IDs (not offset-based)')
    print('   • Uses "after" parameter for forward pagination')
    print('   • Uses "before" parameter for backward pagination')
    print('   • Automatically handled by iter_pages() and async iteration')
    print()
    print('3. KEY INSIGHTS:')
    print('   • .list() returns AsyncPaginator (not a page!)')
    print('   • await paginator → returns first AsyncArrayPage')
    print('   • page.items → List[T] of items on that page')
    print('   • page.has_next_page() → bool if more pages exist')
    print('   • page.get_next_page() → fetch next page manually')
    print('   • async for item in paginator → ALL items (recommended!)')
    print()
    print('4. COMMON PITFALL TO AVOID:')
    print('   ✗ BAD:  items = await client.list()  # Returns page, not items!')
    print('   ✓ GOOD: page = await client.list()')
    print('           items = page.items')
    print()
    print('   ✗ BAD:  for item in page:  # Only iterates first page!')
    print('   ✓ GOOD: async for item in client.list():  # All pages!')
    print()


if __name__ == '__main__':
    asyncio.run(test_pagination_patterns())
