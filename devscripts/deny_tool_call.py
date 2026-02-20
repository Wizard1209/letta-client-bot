"""Deny a pending client tool call on an agent.

Use when agent is stuck waiting for approval and you need to unblock it.
Finds the most recent unanswered approval request automatically.

Usage:
    uv run python -m devscripts.deny_tool_call [-a AGENT_ID] [--reason REASON]
"""

import argparse

from devscripts.bootstrap import letta, print_config, resolve_agent_id


def find_pending_tool_call_id(agent_id):
    """Find the most recent unanswered approval_request_message."""
    messages = letta.agents.messages.list(
        agent_id=agent_id,
        limit=30,
        order='desc',
    )

    # Collect answered tool_call_ids from approval_response_messages
    answered = set()
    requests = []
    for msg in messages:
        mt = getattr(msg, 'message_type', None)
        if mt == 'approval_response_message':
            for a in getattr(msg, 'approvals', []) or []:
                tid = getattr(a, 'tool_call_id', None)
                if tid:
                    answered.add(tid)
        elif mt == 'approval_request_message':
            tc = getattr(msg, 'tool_call', None)
            if tc:
                requests.append((getattr(tc, 'tool_call_id', None), getattr(tc, 'name', '?')))

    # Find first unanswered request
    for tool_call_id, tool_name in requests:
        if tool_call_id and tool_call_id not in answered:
            return tool_call_id, tool_name

    return None, None


def main():
    parser = argparse.ArgumentParser(description='Deny pending tool call')
    parser.add_argument('-a', '--agent-id', help='Agent ID')
    parser.add_argument(
        '--reason', default='Denied via devscript', help='Denial reason'
    )
    args = parser.parse_args()

    agent_id = resolve_agent_id(args.agent_id)
    if not agent_id:
        print('Error: no agent ID. Use -a, LETTA_AGENT_ID env, or .agent_id file')
        return

    print_config(agent_id=agent_id)

    print('Looking for pending approval request...')
    tool_call_id, tool_name = find_pending_tool_call_id(agent_id)
    if not tool_call_id:
        print('No pending tool call found in recent messages.')
        return

    print(f'Found pending: tool={tool_name}, tool_call_id={tool_call_id}')
    print(f'Denying with reason: {args.reason}')

    response = letta.agents.messages.create(
        agent_id=agent_id,
        messages=[
            {
                'type': 'approval',
                'approvals': [
                    {
                        'type': 'approval',
                        'tool_call_id': tool_call_id,
                        'approve': False,
                        'reason': args.reason,
                    }
                ],
            }
        ],
    )

    print(f'Done — agent unblocked.')


if __name__ == '__main__':
    main()
