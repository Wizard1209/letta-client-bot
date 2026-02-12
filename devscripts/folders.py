"""Manage Letta folders - list and delete.

Usage:
    uv run python -m devscripts.folders list
    uv run python -m devscripts.folders delete folder-uuid1 folder-uuid2
"""

import argparse

from letta_client import APIError

from devscripts.bootstrap import letta, print_config


def list_folders() -> None:
    """List all folders with their details."""
    folders = list(letta.folders.list())

    if not folders:
        print('\nNo folders found.')
        return

    print('\n' + '=' * 80)
    print(f'Found {len(folders)} folder(s)')
    print('=' * 80 + '\n')

    for idx, folder in enumerate(folders, 1):
        print(f'{idx}. {folder.name}')
        print(f'   ID: {folder.id}')

        if folder.description:
            print(f'   Description: {folder.description}')

        if folder.metadata:
            print(f'   Metadata: {folder.metadata}')

        # List files in folder
        try:
            files = list(letta.folders.files.list(folder_id=folder.id))
            if files:
                print(f'   Files ({len(files)}):')
                for f in files[:5]:  # Show first 5 files
                    status = f.processing_status or 'unknown'
                    print(f'     - {f.file_name} [{status}]')
                if len(files) > 5:
                    print(f'     ... and {len(files) - 5} more')
            else:
                print('   Files: (empty)')
        except APIError:
            print('   Files: (error listing)')

        print()

    print('=' * 80)


def delete_folder(folder_id: str) -> tuple[str, bool, str | None]:
    """Delete a folder and return result."""
    try:
        letta.folders.delete(folder_id=folder_id)
        return (folder_id, True, None)
    except APIError as e:
        return (folder_id, False, str(e))


def delete_folders(folder_ids: list[str]) -> None:
    """Delete specified folders."""
    if not folder_ids:
        print('\nNo folder IDs provided.')
        return

    print(f'\nDeleting {len(folder_ids)} folder(s)...\n')

    for folder_id in folder_ids:
        folder_id, success, error = delete_folder(folder_id)
        if success:
            print(f'  Deleted: {folder_id}')
        else:
            print(f'  Failed: {folder_id} - {error}')

    print('\nDone.')


def main() -> None:
    print_config()
    parser = argparse.ArgumentParser(description='Manage Letta folders')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # list command
    subparsers.add_parser('list', help='List all folders')

    # delete command
    delete_parser = subparsers.add_parser('delete', help='Delete folders by ID')
    delete_parser.add_argument(
        'folder_ids',
        nargs='+',
        help='One or more folder IDs to delete (space-separated)',
    )

    args = parser.parse_args()

    if args.command == 'list':
        list_folders()
    elif args.command == 'delete':
        delete_folders(args.folder_ids)


if __name__ == '__main__':
    main()
