"""Test folder workflow: create agent, attach folder, upload file, check tools.

This script demonstrates and tests the folder attachment workflow:
1. Create a minimal agent
2. Create a folder and attach it to the agent
3. Upload a test file to the folder
4. Show agent tools (should have file tools)
5. Show agent info and folder ID
6. Detach folder from agent
7. Show agent tools again (file tools should be gone)
8. Cleanup: delete agent and folder

Usage:
    uv run python -m devscripts.test_folder_workflow
    uv run python -m devscripts.test_folder_workflow --keep  # Don't cleanup
"""

import argparse
import time
from io import BytesIO

from devscripts.bootstrap import letta


def print_section(title: str) -> None:
    """Print section header."""
    print()
    print('=' * 60)
    print(f'  {title}')
    print('=' * 60)


def print_tools(agent_id: str) -> None:
    """Print agent's tools."""
    agent = letta.agents.retrieve(agent_id, include=['agent.tools'])
    tools = agent.tools or []

    print(f'\nTools ({len(tools)}):')
    if not tools:
        print('  (none)')
        return

    for tool in tools:
        print(f'  - {tool.name}')


def print_agent_info(agent_id: str) -> None:
    """Print agent information."""
    agent = letta.agents.retrieve(agent_id, include=['agent.tools'])

    print(f'\nAgent: {agent.name}')
    print(f'  ID: {agent.id}')
    print(f'  Model: {agent.model}')
    print(f'  Tools: {len(agent.tools or [])}')


def print_folders(agent_id: str) -> None:
    """Print agent's attached folders."""
    folders = list(letta.agents.folders.list(agent_id=agent_id))

    print(f'\nFolders ({len(folders)}):')
    if not folders:
        print('  (none)')
        return

    for folder in folders:
        print(f'  - {folder.name} (ID: {folder.id})')


def wait_for_file_processing(folder_id: str, file_id: str, timeout: float = 60.0) -> str:
    """Wait for file processing to complete."""
    start = time.time()
    interval = 1.0

    while time.time() - start < timeout:
        file_obj = letta.folders.files.retrieve(file_id, folder_id=folder_id)
        status = file_obj.processing_status

        if status == 'completed':
            return status
        if status == 'error':
            raise RuntimeError(f'File processing failed: {file_obj.error_message}')

        print(f'  Status: {status}... waiting')
        time.sleep(interval)
        interval = min(interval * 1.5, 5.0)

    raise TimeoutError(f'File processing timed out after {timeout}s')


def main() -> None:
    parser = argparse.ArgumentParser(description='Test folder workflow')
    parser.add_argument(
        '--keep',
        action='store_true',
        help='Keep agent and folder after test (no cleanup)',
    )
    args = parser.parse_args()

    agent_id: str | None = None
    folder_id: str | None = None

    try:
        # 1. Create agent
        print_section('1. Creating agent')
        agent = letta.agents.create(
            name='test-folder-workflow',
            include_base_tools=True,
            tags=['test', 'folder-workflow'],
        )
        agent_id = agent.id
        print(f'Created agent: {agent.name} (ID: {agent_id})')

        # Show initial tools
        print_section('2. Initial agent tools')
        print_tools(agent_id)

        # 2. Create folder
        print_section('3. Creating folder')
        folder = letta.folders.create(
            name=f'test-folder-{agent_id[:8]}',
            metadata={'test': 'true', 'agent_id': agent_id},
        )
        folder_id = folder.id
        print(f'Created folder: {folder.name} (ID: {folder_id})')

        # 3. Attach folder to agent
        print_section('4. Attaching folder to agent')
        letta.agents.folders.attach(folder_id=folder_id, agent_id=agent_id)
        print(f'Attached folder {folder_id} to agent {agent_id}')

        # Show tools after folder attachment
        print_section('5. Agent tools after folder attachment')
        print_tools(agent_id)
        print_folders(agent_id)

        # 4. Upload test file
        print_section('6. Uploading test file')
        test_content = b'# Test Document\n\nThis is a test file for folder workflow.\n'
        test_file = BytesIO(test_content)
        test_file.name = 'test_document.md'

        file_obj = letta.folders.files.upload(
            folder_id=folder_id,
            file=test_file,
        )
        print(f'Uploaded file: {file_obj.file_name} (ID: {file_obj.id})')
        print(f'Processing status: {file_obj.processing_status}')

        # Wait for processing
        print('\nWaiting for file processing...')
        final_status = wait_for_file_processing(folder_id, file_obj.id)
        print(f'Final status: {final_status}')

        # Show agent info
        print_section('7. Agent info with folder')
        print_agent_info(agent_id)
        print_folders(agent_id)

        # List files in folder
        files = list(letta.folders.files.list(folder_id=folder_id))
        print(f'\nFiles in folder ({len(files)}):')
        for f in files:
            print(f'  - {f.file_name} [{f.processing_status}]')

        # 5. Detach folder
        print_section('8. Detaching folder from agent')
        letta.agents.folders.detach(folder_id=folder_id, agent_id=agent_id)
        print(f'Detached folder {folder_id} from agent {agent_id}')

        # Show tools after folder detachment
        print_section('9. Agent tools after folder detachment')
        print_tools(agent_id)
        print_folders(agent_id)

        print_section('Test completed successfully!')

    finally:
        # Cleanup
        if not args.keep:
            print_section('Cleanup')

            if agent_id:
                try:
                    letta.agents.delete(agent_id=agent_id)
                    print(f'Deleted agent: {agent_id}')
                except Exception as e:
                    print(f'Failed to delete agent: {e}')

            if folder_id:
                try:
                    letta.folders.delete(folder_id=folder_id)
                    print(f'Deleted folder: {folder_id}')
                except Exception as e:
                    print(f'Failed to delete folder: {e}')
        else:
            print_section('Skipping cleanup (--keep flag)')
            print(f'Agent ID: {agent_id}')
            print(f'Folder ID: {folder_id}')


if __name__ == '__main__':
    main()
