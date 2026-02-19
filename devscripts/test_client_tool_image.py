"""Test client-side tool with DALL-E image generation.

Demonstrates the client-side tool pattern:
1. Send message to agent with client_tools=[generate_image]
2. Agent calls generate_image → execution pauses (approval_request_message)
3. Client generates image via DALL-E
4. Client sends approval + image back to agent
5. Agent sees the image and describes it

Usage:
    uv run python -m devscripts.test_client_tool_image "Draw a cat"
    uv run python -m devscripts.test_client_tool_image -a <agent-id> "Draw a sunset"
"""

import argparse
import base64
import json
import sys
from pathlib import Path

from openai import OpenAI

from devscripts.bootstrap import letta, print_config, resolve_agent_id
from letta_bot.config import CONFIG

# Client-side tool schema
CLIENT_TOOL = {
    'name': 'generate_image',
    'description': (
        'Generate an image based on a text description using DALL-E. '
        'Use this tool when the user asks you to draw, create, or generate an image.'
    ),
    'parameters': {
        'type': 'object',
        'properties': {
            'prompt': {
                'type': 'string',
                'description': 'Detailed image generation prompt in English',
            },
        },
        'required': ['prompt'],
    },
}


def generate_image(prompt: str) -> tuple[str, str]:
    """Call DALL-E API to generate an image.

    Returns:
        Tuple of (base64_image_data, revised_prompt)
    """
    openai_client = OpenAI(api_key=CONFIG.openai_api_key)

    print(f'  [DALL-E] Generating image for: {prompt}')
    response = openai_client.images.generate(
        model='dall-e-3',
        prompt=prompt,
        size='1024x1024',
        response_format='b64_json',
        n=1,
    )

    image_data = response.data[0]
    b64 = image_data.b64_json
    revised = image_data.revised_prompt or prompt

    if not b64:
        raise RuntimeError('DALL-E returned empty image data')

    print(f'  [DALL-E] Done. Revised prompt: {revised}')
    return b64, revised


def save_image(b64_data: str, path: Path) -> None:
    """Save base64 image to file."""
    image_bytes = base64.b64decode(b64_data)
    path.write_bytes(image_bytes)
    print(f'  [SAVE] Image saved: {path} ({len(image_bytes)} bytes)')


def print_messages(messages):
    """Print all messages from a Letta response."""
    for msg in messages:
        msg_type = getattr(msg, 'message_type', '?')

        if msg_type == 'assistant_message':
            content = getattr(msg, 'content', '')
            print(f'\n  [AGENT] {content}')

        elif msg_type == 'reasoning_message':
            reasoning = getattr(msg, 'reasoning', '')
            print(f'  [REASONING] {reasoning}')

        elif msg_type == 'tool_call_message':
            tool_call = getattr(msg, 'tool_call', None)
            if tool_call:
                print(f'  [TOOL CALL] {tool_call.name}({tool_call.arguments})')

        elif msg_type == 'approval_request_message':
            tool_call = getattr(msg, 'tool_call', None)
            if tool_call:
                print(f'  [APPROVAL REQUEST] {tool_call.name}({tool_call.arguments})')

        elif msg_type == 'tool_return_message':
            print(f'  [TOOL RETURN] {getattr(msg, "tool_return", "")}')

        else:
            print(f'  [{msg_type}]')


def find_approval_request(messages):
    """Find the first approval_request_message in response."""
    for msg in messages:
        if getattr(msg, 'message_type', None) == 'approval_request_message':
            return msg
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Test client-side tool with DALL-E image generation',
    )
    parser.add_argument('prompt', help='User message to send to agent')
    parser.add_argument(
        '-a', '--agent-id',
        help='Agent ID (also reads from LETTA_AGENT_ID env or .agent_id file)',
    )
    parser.add_argument(
        '-o', '--output',
        default='test_output.png',
        help='Output image path (default: test_output.png)',
    )

    args = parser.parse_args()

    agent_id = resolve_agent_id(args.agent_id)
    if not agent_id:
        print('Error: No agent ID found')
        print('  Set via: --agent-id, LETTA_AGENT_ID env, or .agent_id file')
        return 1

    print_config(agent_id=agent_id, prompt=args.prompt)

    # Step 1: Send user message with client tool
    print('--- Sending message to agent ---')
    response = letta.agents.messages.create(
        agent_id=agent_id,
        messages=[{'role': 'user', 'content': args.prompt}],
        client_tools=[CLIENT_TOOL],
    )

    print_messages(response.messages)

    # Step 2: Loop — handle approval requests until agent finishes
    image_counter = 0
    while True:
        approval_req = find_approval_request(response.messages)
        if not approval_req:
            break  # Agent finished, no more tool calls

        tool_call = approval_req.tool_call
        tool_args = json.loads(tool_call.arguments)
        dalle_prompt = tool_args.get('prompt', args.prompt)

        # Step 3: Generate image via DALL-E
        print(f'\n--- Executing client-side tool ---')
        b64_data, revised_prompt = generate_image(dalle_prompt)

        # Step 4: Save image locally
        image_counter += 1
        output_path = Path(args.output)
        if image_counter > 1:
            output_path = output_path.with_stem(
                f'{output_path.stem}_{image_counter}'
            )
        save_image(b64_data, output_path)

        # Step 5: Send approval + image back to agent
        print('\n--- Sending result back to agent ---')

        # Build image content part
        image_part = {
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': 'image/png',
                'data': b64_data,
            },
        }

        # Try: approval + user message with image in one call
        response = letta.agents.messages.create(
            agent_id=agent_id,
            messages=[
                # Approval response with tool result
                {
                    'type': 'approval',
                    'approvals': [{
                        'type': 'tool',
                        'tool_call_id': tool_call.tool_call_id,
                        'tool_return': f'Image generated successfully. Revised prompt: {revised_prompt}',
                        'status': 'success',
                    }],
                },
                # User message with image for agent to see
                {
                    'role': 'user',
                    'content': [
                        image_part,
                        {
                            'type': 'text',
                            'text': '<generated_image>DALL-E result attached</generated_image>',
                        },
                    ],
                },
            ],
            client_tools=[CLIENT_TOOL],
        )

        print_messages(response.messages)

    print('\n--- Done ---')
    return 0


if __name__ == '__main__':
    sys.exit(main())
