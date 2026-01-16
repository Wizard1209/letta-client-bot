"""Test Letta file upload size limits.

Creates test files of various sizes and attempts to upload them to find the limit.

Usage:
    uv run python -m devscripts.test_upload_limits
    uv run python -m devscripts.test_upload_limits --min 1 --max 50 --step 5
    uv run python -m devscripts.test_upload_limits --binary-search --min 1 --max 100
"""

import argparse
import io
import sys

from letta_client import APIError

from devscripts.bootstrap import letta


def create_test_file(size_mb: float) -> io.BytesIO:
    """Create in-memory test file of specified size."""
    size_bytes = int(size_mb * 1024 * 1024)
    # Create text content (repeating pattern)
    content = ('x' * 1000 + '\n') * (size_bytes // 1001 + 1)
    content = content[:size_bytes]
    file = io.BytesIO(content.encode('utf-8'))
    file.name = f'test_{size_mb}mb.txt'
    return file


def try_upload(folder_id: str, size_mb: float) -> tuple[bool, str]:
    """Try to upload a file of specified size.

    Returns:
        Tuple of (success, message)
    """
    file = create_test_file(size_mb)
    try:
        result = letta.folders.files.upload(
            folder_id=folder_id,
            file=file,
        )
        return (True, f'uploaded, status={result.processing_status}')
    except APIError as e:
        status = getattr(e, 'status_code', 'unknown')
        return (False, f'APIError status={status}')
    except Exception as e:
        return (False, f'{type(e).__name__}: {e}')


def create_test_folder() -> str:
    """Create a temporary folder for testing."""
    import time

    folder = letta.folders.create(
        name=f'upload-limit-test-{int(time.time())}',
        metadata={'purpose': 'testing upload limits'},
    )
    return folder.id


def cleanup_folder(folder_id: str) -> None:
    """Delete test folder and its files."""
    try:
        # Delete all files first
        for file in letta.folders.files.list(folder_id=folder_id):
            try:
                letta.folders.files.delete(file.id, folder_id=folder_id)
            except APIError:
                pass
        # Delete folder
        letta.folders.delete(folder_id=folder_id)
        print(f'\nCleaned up folder: {folder_id}')
    except APIError as e:
        print(f'\nWarning: cleanup failed: {e}')


def test_linear(folder_id: str, min_mb: float, max_mb: float, step_mb: float) -> None:
    """Test sizes linearly from min to max."""
    print(f'\nTesting sizes from {min_mb}MB to {max_mb}MB (step {step_mb}MB)\n')
    print('-' * 50)

    size = min_mb
    last_success = 0.0
    first_fail = None

    while size <= max_mb:
        success, msg = try_upload(folder_id, size)
        status = 'OK' if success else 'FAIL'
        print(f'{size:6.1f} MB: {status:4} - {msg}')

        if success:
            last_success = size
        elif first_fail is None:
            first_fail = size

        size += step_mb

    print('-' * 50)
    print(f'\nResults:')
    print(f'  Last successful: {last_success} MB')
    if first_fail:
        print(f'  First failure:   {first_fail} MB')
        print(f'  Estimated limit: {last_success} - {first_fail} MB')


def test_binary_search(folder_id: str, min_mb: float, max_mb: float) -> None:
    """Find exact limit using binary search."""
    print(f'\nBinary search between {min_mb}MB and {max_mb}MB\n')
    print('-' * 50)

    low = min_mb
    high = max_mb
    precision = 0.5  # Stop when range is smaller than this

    while high - low > precision:
        mid = (low + high) / 2
        success, msg = try_upload(folder_id, mid)
        status = 'OK' if success else 'FAIL'
        print(f'{mid:6.1f} MB: {status:4} - {msg}')

        if success:
            low = mid
        else:
            high = mid

    print('-' * 50)
    print(f'\nResult:')
    print(f'  Upload limit: ~{low:.1f} MB')
    print(f'  (between {low:.1f} and {high:.1f} MB)')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Test Letta file upload size limits'
    )
    parser.add_argument(
        '--min',
        type=float,
        default=1.0,
        help='Minimum size to test in MB (default: 1)',
    )
    parser.add_argument(
        '--max',
        type=float,
        default=30.0,
        help='Maximum size to test in MB (default: 30)',
    )
    parser.add_argument(
        '--step',
        type=float,
        default=5.0,
        help='Step size in MB for linear test (default: 5)',
    )
    parser.add_argument(
        '--binary-search',
        action='store_true',
        help='Use binary search to find exact limit',
    )
    parser.add_argument(
        '--no-cleanup',
        action='store_true',
        help='Do not delete test folder after testing',
    )

    args = parser.parse_args()

    print('Creating test folder...')
    folder_id = create_test_folder()
    print(f'Folder ID: {folder_id}')

    try:
        if args.binary_search:
            test_binary_search(folder_id, args.min, args.max)
        else:
            test_linear(folder_id, args.min, args.max, args.step)
    except KeyboardInterrupt:
        print('\n\nInterrupted by user')
        sys.exit(1)
    finally:
        if not args.no_cleanup:
            cleanup_folder(folder_id)
        else:
            print(f'\nFolder kept: {folder_id}')


if __name__ == '__main__':
    main()
