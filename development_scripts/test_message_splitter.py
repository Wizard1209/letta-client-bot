"""Quick test of message splitter functionality."""

from aiogram.utils.formatting import Bold, Code, Italic, Text

from letta_bot.message_splitter import split_message

# Test 1: Short message (no split needed)
short = Text(Bold('Test:'), ' Hello world')
chunks = split_message(short, max_length=100)
print(f'Test 1 - Short message: {len(chunks)} chunk(s)')
print(f'  Content: {chunks[0].as_markdown()[:50]}...')
print()

# Test 2: Long message with newlines (should split at newlines)
long_text = '\n'.join([f'Line {i}: Some content here' for i in range(200)])
long = Text(Bold('Agent response:'), '\n\n', long_text)
chunks = split_message(long, max_length=500)
print(f'Test 2 - Long message with newlines: {len(chunks)} chunk(s)')
for i, chunk in enumerate(chunks[:3]):
    print(f'  Chunk {i + 1}: len={len(chunk)}')
print()

# Test 3: Long message with dots (should split at dots)
dot_text = '. '.join([f'Sentence {i}' for i in range(200)])
dot_msg = Text(Italic('Reasoning:'), ' ', dot_text)
chunks = split_message(dot_msg, max_length=400)
print(f'Test 3 - Long message with dots: {len(chunks)} chunk(s)')
for i, chunk in enumerate(chunks[:3]):
    print(f'  Chunk {i + 1}: len={len(chunk)}')
print()

# Test 4: Verify formatting is preserved
formatted = Text(Bold('Bold'), ' normal ', Code('python', 'code'), ' ', Italic('italic'))
repeated = Text(*([formatted, ' | '] * 100))
chunks = split_message(repeated, max_length=300)
print(f'Test 4 - Complex formatting: {len(chunks)} chunk(s)')
print(f'  First chunk: {chunks[0].as_markdown()[:80]}...')
has_formatting = '*' in chunks[0].as_markdown() and '`' in chunks[0].as_markdown()
print(f'  All formatting preserved: {has_formatting}')
