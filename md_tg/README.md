# md_tg - Markdown to Telegram Converter

Converts Markdown to Telegram's native MessageEntity format. Parses Markdown into AST and generates plain text with entity objects - no MarkdownV2 escaping needed.

## Features

- 🎯 **Native Telegram entities** - no manual escaping
- 📦 **Automatic chunking** - splits long messages at block boundaries (4096 char limit)
- 🔤 **UTF-16 aware** - correct entity offsets for emoji and Unicode
- 📊 **Full Markdown support** - headings, lists, tables, code blocks, links, task lists
- ⚡ **Fast** - single-pass rendering for short messages (<1ms)

## Installation

```bash
pip install mistune  # Required dependency
```

## Quick Start

```python
from md_tg import markdown_to_telegram

markdown = """# Hello World

This is **bold** and *italic* text.

```python
print("Code example")
```
"""

# Convert to Telegram format
chunks = markdown_to_telegram(markdown)

# Send to Telegram
for text, entities in chunks:
    await bot.send_message(chat_id, text, entities=entities)
```

**Result:**
```python
# chunks[0]
text = "📌 Hello World\n\nThis is bold and italic text.\n\nprint(\"Code example\")"
entities = [
    {'type': 'bold', 'offset': 3, 'length': 11},  # "Hello World"
    {'type': 'bold', 'offset': 23, 'length': 4},  # "bold"
    {'type': 'italic', 'offset': 32, 'length': 6},  # "italic"
    {'type': 'pre', 'offset': 45, 'length': 21, 'language': 'python'},
]
```

## Supported Markdown

| Markdown | Telegram Entity | Example |
|----------|----------------|---------|
| `**bold**` | `bold` | **bold** |
| `*italic*` | `italic` | *italic* |
| `~~strike~~` | `strikethrough` | ~~strike~~ |
| `` `code` `` | `code` | `code` |
| `[link](url)` | `text_link` | [example](https://example.com) |
| ` ```lang` | `pre` | with language tag |
| `# Heading` | `bold` + emoji | 📌 Heading |
| `- [ ] Todo` | text | ☑️ Todo |
| `- [x] Done` | text | ✅ Done |
| `> quote` | `italic` | *quote* |
| `---` | text | `————————` |
| Tables | `code` | ASCII art table |

## Configuration

```python
from md_tg import markdown_to_telegram, MarkdownConfig

config = MarkdownConfig(
    # Chunk size (Telegram max: 4096)
    max_chunk_length=4096,

    # Heading emojis (H1-H6)
    head_level_1='📌',
    head_level_2='✏️',
    head_level_3='📚',
    head_level_4='🔖',
    head_level_5='📎',
    head_level_6='📝',

    # Task lists
    task_completed='✅',
    task_uncompleted='☑️',

    # Links and images
    link_reference='🔗',  # For [text][ref] style links
    image_emoji='🖼️',     # For ![alt](src) images

    # Visual separators
    thematic_break_char='—',
    thematic_break_length=8,
)

chunks = markdown_to_telegram(markdown, config)
```

## How It Works

```
Markdown → Mistune Parser → AST → Estimate block sizes
    → Split large blocks (if needed) → Group into chunks (<4096)
    → Render each chunk → (text, entities) pairs
```

**Smart chunking:**
- Splits at block boundaries (paragraphs, headings, code blocks)
- Never splits words mid-way
- Large code blocks split by lines (preserves language tag)
- Entity offsets automatically correct per chunk

## Module Structure

```
md_tg/
├── __init__.py      # Public API: markdown_to_telegram, MarkdownConfig
├── converter.py     # Main conversion logic + chunking
├── renderer.py      # TelegramRenderer (mistune renderer)
├── config.py        # MarkdownConfig + MessageEntity TypedDict
└── utils.py         # UTF-16 length utilities
```

## UTF-16 Handling

Telegram API requires entity offsets in UTF-16 code units:

```python
text = "Hello 👋 World"
# Emoji = 2 UTF-16 units

entity = {
    'type': 'bold',
    'offset': 8,   # UTF-16 offset (not Unicode codepoint!)
    'length': 5
}
```

md_tg handles this automatically via `utf16_len()` utility.

## License

Part of letta-client-bot project.

## Credits

- **Mistune** - Markdown parser (https://github.com/lepture/mistune)
- Inspired by **telegramify-markdown** (https://github.com/sudoskys/telegramify-markdown)

*Module vibed with Claude Code*
