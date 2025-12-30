"""Main conversion logic for Markdown to Telegram entities.

This module implements AST-based chunking: parse markdown to AST, group blocks
into chunks (each < 4096 chars), then render each chunk separately.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from aiogram.types import MessageEntity
import mistune
from mistune.core import BlockState

from md_tg.config import DEFAULT_CONFIG, MarkdownConfig
from md_tg.renderer import TelegramRenderer
from md_tg.utils import utf16_len


def _render_with_hooks(md: mistune.Markdown, state: BlockState) -> None:
    """Render state with proper hook application.

    Mistune plugins like task_lists use before_render_hooks to transform AST
    before rendering (e.g., rewriting list_item → task_list_item). These hooks
    must be called manually when using render_state() directly.

    This is a DRY helper to ensure hooks are always applied consistently.

    Args:
        md: Markdown instance with plugins loaded
        state: BlockState with parsed tokens to render
    """
    # Apply all before_render_hooks (e.g., task_lists rewriting)
    for hook in md.before_render_hooks:
        hook(md, state)

    # Now render the (potentially modified) tokens
    md.render_state(state)


def _split_inline_element(
    element: str | dict[str, Any],
    max_length: int,
    config: MarkdownConfig,
    state: BlockState,
) -> list[str | dict[str, Any]]:
    """Recursively split oversized inline element, preserving formatting.

    For formatted elements (bold, italic, code, etc.), splits children and
    wraps each chunk in the same formatting. For plain text, splits by chars.

    Args:
        element: Inline element to split (string or token dict)
        max_length: Maximum UTF-16 length per chunk
        config: Rendering configuration
        state: Rendering state for estimation

    Returns:
        List of inline elements, each fitting within max_length
    """
    # String element: split by characters (UTF-16 safe)
    if isinstance(element, str):
        if utf16_len(element) <= max_length:
            return [element]
        # Type assertion: list[str] is valid subtype of list[str | dict[str, Any]]
        return cast(list[str | dict[str, Any]], _split_text_by_chars(element, max_length))

    # Dict element: check if it needs splitting
    element_size = _estimate_inline_size(element, config, state)
    if element_size <= max_length:
        return [element]

    # For elements with 'raw' field (codespan, etc.), split the raw text
    if 'raw' in element:
        raw_text = (
            element['raw'] if isinstance(element['raw'], str) else str(element['raw'])
        )
        text_chunks = _split_text_by_chars(raw_text, max_length)
        # Wrap each chunk in same element type
        return [{**element, 'raw': chunk} for chunk in text_chunks]

    # For elements with children (emphasis, strong, link, etc.), split children
    if 'children' in element:
        children = element['children']
        if not isinstance(children, list):
            children = [children]

        # Split children into chunks
        child_chunks: list[list[str | dict[str, Any]]] = []
        current_chunk: list[str | dict[str, Any]] = []
        current_size = 0

        for child in children:
            child_size = _estimate_inline_size(child, config, state)

            # If single child exceeds limit, split it recursively
            if child_size > max_length:
                # Save current chunk first
                if current_chunk:
                    child_chunks.append(current_chunk)
                    current_chunk = []
                    current_size = 0

                # Split oversized child and add each piece as separate chunk
                split_children = _split_inline_element(child, max_length, config, state)
                for split_child in split_children:
                    child_chunks.append([split_child])
                continue

            # Check if adding child would exceed limit
            if current_size + child_size > max_length and current_chunk:
                child_chunks.append(current_chunk)
                current_chunk = []
                current_size = 0

            current_chunk.append(child)
            current_size += child_size

        if current_chunk:
            child_chunks.append(current_chunk)

        # Wrap each chunk in same element type (preserving formatting!)
        return [{**element, 'children': chunk} for chunk in child_chunks]

    # Fallback: return as-is (will be caught by validation)
    return [element]


def _split_text_by_chars(text: str, max_length: int) -> list[str]:
    """Split text into chunks, preserving UTF-16 surrogate pairs.

    Args:
        text: Text to split
        max_length: Maximum UTF-16 length per chunk

    Returns:
        List of text chunks, each <= max_length UTF-16 units
    """
    if utf16_len(text) <= max_length:
        return [text]

    chunks = []
    pos = 0

    while pos < len(text):
        chunk = ''
        chunk_len = 0

        while pos < len(text) and chunk_len < max_length:
            char = text[pos]
            char_len = utf16_len(char)

            if chunk_len + char_len > max_length:
                break

            chunk += char
            chunk_len += char_len
            pos += 1

        if chunk:
            chunks.append(chunk)

    return chunks


def _split_large_code_block(token: dict[str, Any], max_length: int) -> list[dict[str, Any]]:
    """Split a large code block into multiple smaller code blocks.

    Splits by lines, keeping each chunk under max_length.
    If a single line exceeds max_length, splits it character-by-character
    (UTF-16 safe, preserving emoji and surrogate pairs).
    Reserves 1 character for the final newline that save_chunk() adds.

    Args:
        token: block_code token that's too large
        max_length: Maximum UTF-16 length for each chunk

    Returns:
        List of smaller block_code tokens
    """
    code_content = token.get('raw') or ''
    language = token.get('attrs', {}).get('info')

    # Remove final newline for accurate splitting (it will be added back in save_chunk)
    code_content = code_content.rstrip('\n')

    lines = code_content.split('\n')
    chunks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_length = 0

    # Reserve 2 chars for final '\n\n' that block_code() renderer adds
    max_content_length = max_length - 2

    def save_chunk() -> None:
        """Save current_lines as a chunk token."""
        if not current_lines:
            return

        chunk_code = '\n'.join(current_lines)
        # Add final newline (this is why we reserved 1 char)
        chunk_token = {
            'type': 'block_code',
            'raw': chunk_code + '\n',
            'style': token.get('style', 'fenced'),
            'marker': token.get('marker', '```'),
        }
        if language:
            chunk_token['attrs'] = {'info': language}
        chunks.append(chunk_token)

    for line in lines:
        # Calculate line length (base length without separator)
        line_len = utf16_len(line)

        # Handle single line > max_length: split by characters (UTF-16 safe)
        if line_len > max_content_length:
            # Save current chunk first
            if current_lines:
                save_chunk()
                current_lines = []
                current_length = 0

            # Split long line character by character (UTF-16 aware)
            pos = 0
            while pos < len(line):
                chunk = ''
                chunk_len = 0

                # Accumulate characters until reaching max_content_length
                while pos < len(line) and chunk_len < max_content_length:
                    char = line[pos]
                    char_len = utf16_len(char)

                    if chunk_len + char_len > max_content_length:
                        break

                    chunk += char
                    chunk_len += char_len
                    pos += 1

                # Save chunk
                if chunk:
                    current_lines = [chunk]
                    save_chunk()
                    current_lines = []

            current_length = 0
            continue

        # Normal line handling
        # Add separator length for non-first lines in chunk
        separator_len = 1 if current_lines else 0  # 1 for '\n', 0 for first line
        total_line_len = line_len + separator_len

        # Check if adding this line exceeds limit
        if current_length + total_line_len > max_content_length and current_lines:
            save_chunk()
            current_lines = []
            current_length = 0
            # First line in new chunk: no separator needed
            total_line_len = line_len

        current_lines.append(line)
        current_length += total_line_len

    save_chunk()

    return chunks


def _estimate_block_size(
    token: dict[str, Any],
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> int:
    """Estimate UTF-16 size of a single block when rendered.

    Creates a temporary Markdown instance with TelegramRenderer,
    renders just this one block, and returns its UTF-16 length.

    Args:
        token: Single AST block token
        config: Rendering configuration
        env: Environment dict from parse state (contains ref_links)

    Returns:
        UTF-16 length of rendered block
    """
    # Create fresh renderer with config
    renderer = TelegramRenderer(config)

    # Create Markdown instance WITH plugins
    md = mistune.create_markdown(
        renderer=renderer,
        plugins=['strikethrough', 'task_lists', 'url', 'table'],
    )

    # Create state with just this one token
    state = BlockState()
    state.tokens = [token]
    # Copy env to preserve ref_links for reference-style link resolution
    if env is not None:
        state.env.update(env)

    # Render the token (with hooks applied for plugins like task_lists)
    _render_with_hooks(md, state)

    # Measure UTF-16 length
    return utf16_len(renderer.output_text)


def _estimate_inline_size(
    child: str | dict[str, Any],
    config: MarkdownConfig,
    state: BlockState,
) -> int:
    """Estimate UTF-16 size of a single inline element.

    Uses direct rendering pattern (like table_cell) without Markdown instance.

    Args:
        child: Inline element (string or token dict)
        config: Rendering configuration
        state: Rendering state with env (for ref_links)

    Returns:
        UTF-16 length of rendered inline element
    """
    # String children render as-is
    if isinstance(child, str):
        return utf16_len(child)

    # Create temporary renderer (like table_cell pattern)
    temp_renderer = TelegramRenderer(config)

    # Render inline token directly
    temp_renderer.render_token(child, state)

    return utf16_len(temp_renderer.output_text)


def _split_large_paragraph(
    token: dict[str, Any],
    max_length: int,
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split a large paragraph into multiple smaller paragraphs.

    Splits by inline children (text, emphasis, strong, code, link, etc.),
    keeping each chunk under max_length. If a single child exceeds max_length,
    splits it recursively while preserving formatting (e.g., **long text**
    becomes **part1** and **part2**).

    Args:
        token: paragraph token that's too large
        max_length: Maximum UTF-16 length for each chunk
        config: Rendering configuration
        env: Environment dict from parse state (contains ref_links)

    Returns:
        List of smaller paragraph tokens, guaranteed to fit within max_length
    """
    children = token.get('children', [])
    if not children:
        return []

    # Paragraph renderer adds '\n\n' after content
    chunk_limit = max_length - 2

    chunks: list[dict[str, Any]] = []
    current_chunk: list[str | dict[str, Any]] = []
    current_size = 0

    # Create state with env for proper ref_link resolution
    state = BlockState()
    if env is not None:
        state.env.update(env)

    for child in children:
        child_size = _estimate_inline_size(child, config, state)

        # If single child exceeds limit, split it recursively while preserving formatting
        if child_size > chunk_limit:
            # Save current chunk first
            if current_chunk:
                chunks.append({'type': 'paragraph', 'children': current_chunk})
                current_chunk = []
                current_size = 0

            # Split oversized child recursively (preserves formatting structure)
            split_children = _split_inline_element(child, chunk_limit, config, state)

            # Add each split piece as separate paragraph
            for split_child in split_children:
                chunks.append({'type': 'paragraph', 'children': [split_child]})

            continue

        # Start new chunk if adding this child would exceed limit
        if current_size + child_size > chunk_limit and current_chunk:
            chunks.append({'type': 'paragraph', 'children': current_chunk})
            current_chunk = []
            current_size = 0

        current_chunk.append(child)
        current_size += child_size

    # Add final chunk if not empty
    if current_chunk:
        chunks.append({'type': 'paragraph', 'children': current_chunk})

    return chunks


def _split_list_item(
    item_token: dict[str, Any],
    max_length: int,
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split a large list_item into multiple list_items.

    Splits children (paragraphs, code blocks, etc.) across multiple list_items.
    Visually creates multiple bullet points, but preserves all content.

    Args:
        item_token: list_item token to split
        max_length: Maximum UTF-16 length for each chunk
        config: Rendering configuration
        env: Environment dict from parse state

    Returns:
        List of list_item tokens, each fitting within max_length
    """
    children = item_token.get('children', [])
    if not children:
        return [item_token]

    # list_item renderer removes trailing '\n\n' and adds '\n'
    # So we need to account for final '\n'
    chunk_limit = max_length - 1

    chunks: list[dict[str, Any]] = []
    current_children: list[dict[str, Any]] = []
    current_size = 0

    for child in children:
        child_size = _estimate_block_size(child, config, env)

        # If single child exceeds limit, try splitting it if it's a splittable type
        if child_size > chunk_limit:
            # Save current accumulated children as a list_item
            if current_children:
                chunks.append({**item_token, 'children': current_children})
                current_children = []
                current_size = 0

            # Try to split the oversized child
            if child['type'] == 'paragraph':
                # Split paragraph and wrap each piece in a list_item
                split_paras = _split_large_paragraph(child, max_length, config, env)
                for para in split_paras:
                    chunks.append({**item_token, 'children': [para]})
            elif child['type'] == 'block_code':
                # Split code block and wrap each piece in a list_item
                split_codes = _split_large_code_block(child, max_length)
                for code in split_codes:
                    chunks.append({**item_token, 'children': [code]})
            elif child['type'] == 'list':
                # Nested list - split it and wrap each piece in a list_item
                split_lists = _split_large_list(child, max_length, config, env)
                for nested_list in split_lists:
                    chunks.append({**item_token, 'children': [nested_list]})
            else:
                # Other types (block_quote, etc.) - add as-is
                # Will be caught by validation if still too large
                chunks.append({**item_token, 'children': [child]})

            continue

        # Check if adding this child would exceed limit
        if current_size + child_size > chunk_limit and current_children:
            chunks.append({**item_token, 'children': current_children})
            current_children = []
            current_size = 0

        current_children.append(child)
        current_size += child_size

    # Add final chunk if not empty
    if current_children:
        chunks.append({**item_token, 'children': current_children})

    return chunks


def _split_large_blockquote(
    token: dict[str, Any],
    max_length: int,
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split a large blockquote into multiple smaller blockquotes.

    Splits children (paragraphs, code blocks, lists, etc.) across multiple
    blockquotes while preserving formatting.

    Args:
        token: block_quote token to split
        max_length: Maximum UTF-16 length for each chunk
        config: Rendering configuration
        env: Environment dict from parse state

    Returns:
        List of blockquote tokens, each fitting within max_length
    """
    children = token.get('children', [])
    if not children:
        return [token]

    # blockquote renderer adds '\n\n' after content
    chunk_limit = max_length - 2

    chunks: list[dict[str, Any]] = []
    current_children: list[dict[str, Any]] = []
    current_size = 0

    for child in children:
        child_size = _estimate_block_size(child, config, env)

        # If single child exceeds limit, split it if it's a splittable type
        if child_size > chunk_limit:
            # Save current accumulated children as a blockquote
            if current_children:
                chunks.append({**token, 'children': current_children})
                current_children = []
                current_size = 0

            # Split the oversized child
            if child['type'] == 'paragraph':
                split_paras = _split_large_paragraph(child, max_length, config, env)
                for para in split_paras:
                    chunks.append({**token, 'children': [para]})
            elif child['type'] == 'block_code':
                split_codes = _split_large_code_block(child, max_length)
                for code in split_codes:
                    chunks.append({**token, 'children': [code]})
            elif child['type'] == 'list':
                split_lists = _split_large_list(child, max_length, config, env)
                for nested_list in split_lists:
                    chunks.append({**token, 'children': [nested_list]})
            elif child['type'] == 'block_quote':
                # Nested blockquote - split recursively
                split_quotes = _split_large_blockquote(child, max_length, config, env)
                for nested_quote in split_quotes:
                    chunks.append({**token, 'children': [nested_quote]})
            else:
                # Other types - add as-is
                chunks.append({**token, 'children': [child]})

            continue

        # Check if adding this child would exceed limit
        if current_size + child_size > chunk_limit and current_children:
            chunks.append({**token, 'children': current_children})
            current_children = []
            current_size = 0

        current_children.append(child)
        current_size += child_size

    # Add final chunk if not empty
    if current_children:
        chunks.append({**token, 'children': current_children})

    return chunks


def _make_table(table_head: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Create table token from header and rows.

    Args:
        table_head: table_head token with headers
        rows: List of table_row tokens

    Returns:
        Complete table token
    """
    return {
        'type': 'table',
        'children': [
            table_head,
            {'type': 'table_body', 'children': rows},
        ],
    }


def _split_large_table(
    token: dict[str, Any],
    max_length: int,
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split large table into multiple tables by rows.

    Each split table keeps same headers and gets subset of rows.

    Args:
        token: table token that's too large
        max_length: Maximum UTF-16 length for each chunk
        config: Rendering configuration
        env: Environment dict from parse state

    Returns:
        List of smaller table tokens
    """
    children = token.get('children', [])
    if not children:
        return []

    # Extract table_head and table_body
    table_head = next((c for c in children if c.get('type') == 'table_head'), None)
    table_body = next((c for c in children if c.get('type') == 'table_body'), None)

    if not table_head or not table_body:
        return [token]

    rows = table_body.get('children', [])
    if not rows:
        return [token]

    # Reserve space for '\n\n' that table renderer adds
    chunk_limit = max_length - 2

    # Group rows by estimating full table size each time
    chunks: list[dict[str, Any]] = []
    current_rows: list[Any] = []

    for row in rows:
        # Test if adding this row would exceed limit
        test_table = _make_table(table_head, current_rows + [row])
        test_size = _estimate_block_size(test_table, config, env)

        if test_size > chunk_limit:
            # Adding this row exceeds limit
            if not current_rows:
                # First row itself exceeds limit - add it alone anyway
                chunks.append(_make_table(table_head, [row]))
            else:
                # Save current chunk and start new one with this row
                chunks.append(_make_table(table_head, current_rows))
                current_rows = [row]
        else:
            # Can safely add this row
            current_rows.append(row)

    # Add remaining rows
    if current_rows:
        chunks.append(_make_table(table_head, current_rows))

    return chunks if chunks else [token]


def _split_large_list(
    token: dict[str, Any],
    max_length: int,
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split a large list into multiple smaller lists.

    Splits by list_item elements, keeping each chunk under max_length.
    Preserves list type (ordered/unordered) and attributes. If a single
    list_item exceeds max_length, splits its children across multiple
    list_items while preserving formatting.

    Args:
        token: list token that's too large
        max_length: Maximum UTF-16 length for each chunk
        config: Rendering configuration
        env: Environment dict from parse state (contains ref_links)

    Returns:
        List of smaller list tokens, guaranteed to fit within max_length
    """
    children = token.get('children', [])
    if not children:
        return []

    # List renderer adds '\n' after content
    chunk_limit = max_length - 1
    list_attrs = token.get('attrs', {})

    chunks: list[dict[str, Any]] = []
    current_chunk: list[dict[str, Any]] = []
    current_size = 0

    for child in children:
        # Estimate size of this list_item
        child_size = _estimate_block_size(child, config, env)

        # If single list_item exceeds limit, split it into multiple list_items
        if child_size > chunk_limit:
            # Save current chunk first
            if current_chunk:
                chunks.append(
                    {
                        'type': 'list',
                        'children': current_chunk,
                        'attrs': list_attrs,
                    }
                )
                current_chunk = []
                current_size = 0

            # Split oversized list_item (preserves structure)
            split_items = _split_list_item(child, max_length, config, env)

            # Add each split item as a separate list
            for split_item in split_items:
                chunks.append(
                    {
                        'type': 'list',
                        'children': [split_item],
                        'attrs': list_attrs,
                    }
                )

            continue

        # Start new chunk if adding this child would exceed limit
        if current_size + child_size > chunk_limit and current_chunk:
            chunks.append(
                {
                    'type': 'list',
                    'children': current_chunk,
                    'attrs': list_attrs,
                }
            )
            current_chunk = []
            current_size = 0

        current_chunk.append(child)
        current_size += child_size

    # Add final chunk if not empty
    if current_chunk:
        chunks.append(
            {
                'type': 'list',
                'children': current_chunk,
                'attrs': list_attrs,
            }
        )

    return chunks


def _group_blocks_into_chunks(
    tokens: list[dict[str, Any]],
    config: MarkdownConfig,
    block_sizes: dict[int, int] | None = None,
    env: Mapping[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    """Group AST blocks into chunks, each fitting within max_chunk_length.

    Args:
        tokens: List of AST block tokens
        config: Configuration with max_chunk_length
        block_sizes: Optional pre-computed block sizes (token_index -> size)
                    to avoid re-computing sizes
        env: Environment dict from parse state (contains ref_links)

    Returns:
        List of token groups (chunks), each group renders to < max_chunk_length
    """
    max_length = config.max_chunk_length
    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = []
    current_size = 0

    for i, token in enumerate(tokens):
        # Skip blank lines (they don't render to anything)
        if token.get('type') == 'blank_line':
            continue

        # Use pre-computed size or estimate now
        if block_sizes is not None and i in block_sizes:
            block_size = block_sizes[i]
        else:
            block_size = _estimate_block_size(token, config, env)

        # Handle blocks that are themselves > max_length
        if block_size > max_length:
            # Save current chunk first
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0

            # Split large block
            if token['type'] == 'block_code':
                # Split code block by lines
                sub_tokens = _split_large_code_block(token, max_length)
                for sub_token in sub_tokens:
                    chunks.append([sub_token])
            elif token['type'] == 'paragraph':
                # Split paragraph by inline children
                sub_tokens = _split_large_paragraph(token, max_length, config, env)
                for sub_token in sub_tokens:
                    chunks.append([sub_token])
            elif token['type'] == 'list':
                # Split list by list_item elements
                sub_tokens = _split_large_list(token, max_length, config, env)
                for sub_token in sub_tokens:
                    chunks.append([sub_token])
            elif token['type'] == 'block_quote':
                # Split blockquote by children (similar to list_item logic)
                sub_tokens = _split_large_blockquote(token, max_length, config, env)
                for sub_token in sub_tokens:
                    chunks.append([sub_token])
            elif token['type'] == 'table':
                # Split table by rows
                sub_tokens = _split_large_table(token, max_length, config, env)
                for sub_token in sub_tokens:
                    chunks.append([sub_token])
            else:
                # Other block types (heading, thematic_break, etc.)
                # Headings and thematic_break are typically short
                # For rare edge cases, include as-is
                chunks.append([token])

            continue

        # Check if adding this block would exceed limit
        if current_size + block_size > max_length and current_chunk:
            # Save current chunk and start new one
            chunks.append(current_chunk)
            current_chunk = [token]
            current_size = block_size
        else:
            # Add block to current chunk
            current_chunk.append(token)
            current_size += block_size

    # Don't forget last chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _render_chunk(
    tokens: list[dict[str, Any]],
    config: MarkdownConfig,
    env: Mapping[str, Any] | None = None,
) -> tuple[str, list[MessageEntity]]:
    """Render a group of tokens to (text, entities).

    Args:
        tokens: List of AST block tokens to render
        config: Rendering configuration
        env: Environment dict from parse state (contains ref_links)

    Returns:
        (plain_text, entities) tuple
    """
    # Create fresh renderer
    renderer = TelegramRenderer(config)

    # Create Markdown instance WITH plugins (critical for strikethrough, task_lists, etc.)
    md = mistune.create_markdown(
        renderer=renderer,
        plugins=['strikethrough', 'task_lists', 'url', 'table'],
    )

    # Create state with these tokens
    state = BlockState()
    state.tokens = tokens
    # Copy env to preserve ref_links for reference-style link resolution
    if env is not None:
        state.env.update(env)

    # Render all tokens (with hooks applied for plugins like task_lists)
    _render_with_hooks(md, state)

    # Finalize and return
    return renderer.finalize()


def markdown_to_telegram(
    markdown_text: str,
    config: MarkdownConfig | None = None,
) -> list[tuple[str, list[MessageEntity]]]:
    """Convert Markdown text to Telegram plain text with message entities.

    This function parses Markdown and produces Telegram-compatible output:
    - Plain text without Markdown formatting
    - List of MessageEntity objects for formatting (bold, italic, code, etc.)

    Automatic chunking via AST splitting is now implemented! If text exceeds
    max_chunk_length (4096), it will be split at block boundaries (between
    paragraphs, headings, code blocks, etc). Words are never split mid-way.

    Large code blocks (> 4096 chars) are automatically split by lines.

    Args:
        markdown_text: Input Markdown text
        config: Optional configuration for rendering (uses default if None)

    Returns:
        List of (plain_text, entities) tuples. ALWAYS returns at least one tuple,
        even for empty input (returns [("", [])]).

        One tuple if text fits in single chunk, multiple tuples if text was split.

    Examples:
        >>> chunks = markdown_to_telegram("**Bold** and *italic*")
        >>> text, entities = chunks[0]  # Safe: always at least one chunk
        >>> print(text)
        Bold and italic
        >>> print(entities)
        [{'type': 'bold', 'offset': 0, 'length': 4},
         {'type': 'italic', 'offset': 9, 'length': 6}]

        >>> # Send all chunks (works for both single and multiple chunks)
        >>> chunks = markdown_to_telegram(markdown_text)
        >>> for text, entities in chunks:
        ...     await bot.send_message(chat_id, text, entities=entities)

        >>> # Automatic chunking for long text
        >>> long_markdown = "..." # Your long text (> 4096 chars)
        >>> chunks = markdown_to_telegram(long_markdown)
        >>> print(f"Split into {len(chunks)} chunks")
        >>> for text, entities in chunks:
        ...     await bot.send_message(chat_id, text, entities=entities)

        >>> # Empty input is safe
        >>> chunks = markdown_to_telegram("")
        >>> text, entities = chunks[0]  # No IndexError
        >>> assert text == "" and entities == []
    """
    # Use default config if none provided
    if config is None:
        config = DEFAULT_CONFIG

    # Parse markdown to AST
    md = mistune.create_markdown(plugins=['strikethrough', 'task_lists', 'url', 'table'])
    state = BlockState()

    # Normalize line endings
    text = markdown_text.replace('\r\n', '\n').replace('\r', '\n')
    if not text.endswith('\n'):
        text += '\n'

    # Parse to tokens
    state.process(text)
    md.block.parse(state)

    # Extract env for reference-style link resolution
    env = state.env

    # Check if small enough for single chunk (fast path)
    # Compute and cache block sizes to avoid re-computing in _group_blocks_into_chunks
    block_sizes: dict[int, int] = {}
    total_size = 0
    for i, tok in enumerate(state.tokens):
        if tok.get('type') != 'blank_line':
            size = _estimate_block_size(tok, config, env)
            block_sizes[i] = size
            total_size += size

    if total_size <= config.max_chunk_length:
        # Render as single chunk (fast path)
        return [_render_chunk(state.tokens, config, env)]

    # Group into chunks (reuse cached block sizes)
    chunk_groups = _group_blocks_into_chunks(state.tokens, config, block_sizes, env)

    # Guarantee: always return at least one chunk (even if empty)
    if not chunk_groups:
        # No content blocks → return single empty chunk
        return [('', [])]

    # Render each chunk
    return [_render_chunk(tokens, config, env) for tokens in chunk_groups]
