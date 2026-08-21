"""Deny a client tool call an agent is blocked on.

An agent that asked for approval and never got an answer stays on that run,
and every later message to it is refused with 409. This is the manual way
out: it finds the most recent unanswered approval request and denies it.

Usage:
    uv run python -m devscripts.deny_tool_call [-a AGENT_ID] [--reason REASON]
"""

import argparse

from devscripts.bootstrap import letta, print_config, resolve_agent_id


def find_pending_approval(agent_id: str) -> tuple[str | None, str | None, str | None]:
    """Return (request_message_id, tool_call_id, tool_name) of the oldest unanswered request."""
    messages = letta.agents.messages.list(agent_id=agent_id, limit=30, order='desc')

    answered = set()
    requests = []
    for msg in messages:
        message_type = getattr(msg, 'message_type', None)
        if message_type == 'approval_response_message':
            for approval in getattr(msg, 'approvals', []) or []:
                if tool_call_id := getattr(approval, 'tool_call_id', None):
                    answered.add(tool_call_id)
        elif message_type == 'approval_request_message':
            tool_call = getattr(msg, 'tool_call', None)
            if tool_call:
                requests.append(
                    (
                        msg.id,
                        getattr(tool_call, 'tool_call_id', None),
                        getattr(tool_call, 'name', '?'),
                    )
                )

    for request_id, tool_call_id, tool_name in requests:
        if tool_call_id and tool_call_id not in answered:
            return request_id, tool_call_id, tool_name

    return None, None, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-a', '--agent-id', help='agent ID')
    parser.add_argument('--reason', default='Denied via devscript', help='denial reason')
    parser.add_argument('--execute', action='store_true', help='actually deny')
    args = parser.parse_args()

    agent_id = resolve_agent_id(args.agent_id)
    if not agent_id:
        print('Error: no agent ID. Use -a, LETTA_AGENT_ID env, or .agent_id file')
        return

    print_config(agent_id=agent_id, mode='EXECUTE' if args.execute else 'dry-run')

    request_id, tool_call_id, tool_name = find_pending_approval(agent_id)
    if not tool_call_id:
        print('No unanswered approval request in the last 30 messages.')
        return

    print(f'pending: tool={tool_name} tool_call_id={tool_call_id} request={request_id}')
    if not args.execute:
        print(f'\ndry-run: would deny with reason {args.reason!r}. Pass --execute to apply.')
        return

    # approval_request_id is what Letta matches the answer against; the bot's own
    # approval path sends it too, and without it the request stays open.
    letta.agents.messages.create(
        agent_id=agent_id,
        messages=[
            {
                'type': 'approval',
                'approval_request_id': request_id,
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
    print('denied — agent unblocked.')


if __name__ == '__main__':
    main()
