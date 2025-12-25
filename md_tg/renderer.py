"""Custom Mistune renderer for Telegram message entities."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlparse

from mistune import BaseRenderer
from mistune.core import BlockState

from md_tg.config import MarkdownConfig, MessageEntity
from md_tg.utils import utf16_len

# Hosts that Telegram rejects for text_link entities
_INVALID_HOSTS = frozenset({'localhost', '127.0.0.1', '0.0.0.0', '::1'})


def _is_valid_telegram_url(url: str) -> bool:
    """Check if URL is valid for Telegram text_link entity.

    Telegram requires http://, https://, or tg:// URLs with valid public hosts.

    Args:
        url: URL string to validate

    Returns:
        True if URL is valid for Telegram text_link entity
    """
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
    except (ValueError, AttributeError):
        return False

    # tg:// deep links are always valid
    if scheme == 'tg':
        return True

    # Must have http or https scheme with valid host
    if scheme not in ('http', 'https'):
        return False

    # Validate host: must exist, not be localhost, and have TLD
    if not (host := parsed.hostname):
        return False

    host = host.lower()
    return host not in _INVALID_HOSTS and '.' in host


class TelegramRenderer(BaseRenderer):
    """Renderer that converts Markdown to Telegram plain text with entities.

    This renderer processes Markdown AST and produces:
    1. Plain text without Markdown formatting
    2. List of MessageEntity objects for Telegram formatting

    Attributes:
        config: Configuration for emoji replacements
        text: Accumulated plain text
        entities: List of message entities
        current_offset: Current position in UTF-16 units
    """

    # Number of spaces per nesting level for visual indentation of nested lists
    INDENT_PER_LEVEL = 2

    def __init__(self, config: MarkdownConfig | None = None) -> None:
        """Initialize renderer.

        Args:
            config: Configuration for rendering (uses default if None)
        """
        super().__init__()
        self.config = config or MarkdownConfig()
        self.output_text: str = ''
        self.entities: list[MessageEntity] = []
        self.current_offset: int = 0
        # Stack to track nested lists (for numbering and depth)
        self._list_stack: list[dict[str, Any]] = []
        # Table state for collecting all rows before rendering
        self._table_data: dict[str, Any] | None = None
        # Track if we're inside a list_item (to adjust paragraph spacing)
        self._in_list_item: bool = False

    def _get_method(self, name: str) -> Callable[..., str]:
        """Get renderer method by name with fallback.

        Args:
            name: Method name (token type)

        Returns:
            Renderer method or fallback handler
        """
        try:
            return super()._get_method(name)
        except AttributeError:
            # Fallback: return method that renders children or raw text
            return self._fallback_renderer

    def _fallback_renderer(self, token: dict[str, Any], state: BlockState) -> str:
        """Fallback renderer for unknown token types.

        Args:
            token: Token dict
            state: Rendering state

        Returns:
            Empty string (content already added)
        """
        # Try to render children if present
        if 'children' in token:
            self._render_children(token, state)
        # Or try to add raw text if present
        elif 'raw' in token:
            raw = token.get('raw', '')
            if isinstance(raw, str):
                self._add_text(raw)
        return ''

    def _add_text(self, content: str) -> None:
        """Add text and update offset.

        Args:
            content: Text content to add
        """
        if not content:  # Early return for empty strings
            return
        self.output_text += content
        self.current_offset += utf16_len(content)

    def _add_entity(
        self,
        entity_type: str,
        offset: int,
        length: int,
        url: str | None = None,
        language: str | None = None,
    ) -> None:
        """Add entity to the list.

        Note: Per Telegram API spec, entity length must not include trailing whitespace.
        Ensure that trailing newlines/spaces are added AFTER creating the entity.
        https://core.telegram.org/api/entities#entity-length

        Args:
            entity_type: Type of entity (bold, italic, code, etc.)
            offset: Start offset of the entity in UTF-16 units
            length: Length in UTF-16 units
            url: URL for text_link entities
            language: Programming language for pre entities
        """
        if length <= 0:  # Skip empty entities
            return

        # Create MessageEntity dict
        entity: MessageEntity = {
            'type': entity_type,
            'offset': offset,
            'length': length,
        }
        if url is not None:
            entity['url'] = url
        if language is not None:
            entity['language'] = language
        self.entities.append(entity)

    def _remove_trailing_newlines(self, max_newlines: int = 1) -> int:
        """Remove trailing newlines from output, leaving at most max_newlines.

        Args:
            max_newlines: Maximum newlines to keep at the end (default: 1)

        Returns:
            Number of characters removed (for updating entity lengths if needed)
        """
        removed_count = 0

        # Remove all double newlines
        while self.output_text.endswith('\n\n'):
            self.output_text = self.output_text[:-2]
            self.current_offset -= 2
            removed_count += 2

        # Remove extra single newlines if needed
        if max_newlines == 0 and self.output_text.endswith('\n'):
            self.output_text = self.output_text[:-1]
            self.current_offset -= 1
            removed_count += 1

        return removed_count

    def _remove_trailing_whitespace(self) -> str:
        """Remove trailing whitespace from output and return removed text.

        Per Telegram API spec, entity length must NOT include trailing whitespace.
        This method removes trailing whitespace and returns it so it can be
        re-added after creating the entity.

        Returns:
            Removed trailing whitespace (empty string if none removed)
        """
        if not self.output_text:
            return ''

        # Find where trailing whitespace starts
        stripped = self.output_text.rstrip()
        if len(stripped) == len(self.output_text):
            return ''  # No trailing whitespace

        # Extract trailing whitespace
        trailing = self.output_text[len(stripped) :]

        # Remove it from output
        self.output_text = stripped
        self.current_offset -= utf16_len(trailing)

        return trailing

    def _render_children(self, token: dict[str, Any], state: BlockState) -> None:
        """Render children tokens or text strings.

        Args:
            token: Token dict with 'children'
            state: Rendering state
        """
        children = token.get('children', [])
        if not children:
            return

        # Normalize to list for consistent handling
        if not isinstance(children, list):
            children = [children]

        # Render each child
        for child in children:
            if isinstance(child, str):
                self._add_text(child)
            elif isinstance(child, dict):
                self.render_token(child, state)
            # Ignore unknown types (defensive programming)

    def _render_inline_entity(
        self,
        token: dict[str, Any],
        state: BlockState,
        entity_type: str,
    ) -> str:
        """Generic renderer for inline entities (bold, italic, strikethrough).

        Args:
            token: Token with children to render
            state: Rendering state
            entity_type: Type of entity ('bold', 'italic', 'strikethrough')

        Returns:
            Empty string (content already added to output)
        """
        start_offset = self.current_offset
        self._render_children(token, state)

        # Per Telegram API spec, entity length must not include trailing whitespace
        trailing = self._remove_trailing_whitespace()

        length = self.current_offset - start_offset
        if length > 0:
            self._add_entity(entity_type, start_offset, length)

        # Re-add trailing whitespace after entity
        if trailing:
            self._add_text(trailing)

        return ''

    # Inline elements

    def text(self, token: dict[str, Any], state: BlockState) -> str:
        """Render plain text.

        Args:
            token: Token dict with 'raw' text content
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        raw = token.get('raw', '')
        if isinstance(raw, str):
            self._add_text(raw)
        return ''

    def emphasis(self, token: dict[str, Any], state: BlockState) -> str:
        """Render italic text (*text* or _text_)."""
        return self._render_inline_entity(token, state, 'italic')

    def strong(self, token: dict[str, Any], state: BlockState) -> str:
        """Render bold text (**text** or __text__)."""
        return self._render_inline_entity(token, state, 'bold')

    def codespan(self, token: dict[str, Any], state: BlockState) -> str:
        """Render inline code (`code`).

        Args:
            token: Token dict with 'raw' code content
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        raw = token.get('raw', '')
        if not raw:
            return ''

        start_offset = self.current_offset
        if isinstance(raw, str):
            self._add_text(raw)
        else:
            self._add_text(str(raw))

        # Per Telegram API spec, entity length must not include trailing whitespace
        trailing = self._remove_trailing_whitespace()

        length = self.current_offset - start_offset
        if length > 0:  # Only add entity if there's content
            self._add_entity('code', start_offset, length)

        # Re-add trailing whitespace after entity
        if trailing:
            self._add_text(trailing)

        return ''

    def inline_html(self, token: dict[str, Any], state: BlockState) -> str:
        """Render inline HTML as inline code.

        HTML tags are rendered as inline code entities for security and clarity.

        Args:
            token: Token dict with 'raw' HTML content
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        raw = token.get('raw', '')
        if not raw:
            return ''

        start_offset = self.current_offset
        if isinstance(raw, str):
            self._add_text(raw)
        else:
            self._add_text(str(raw))

        # Per Telegram API spec, entity length must not include trailing whitespace
        trailing = self._remove_trailing_whitespace()

        length = self.current_offset - start_offset
        if length > 0:  # Only add entity if there's content
            self._add_entity('code', start_offset, length)

        # Re-add trailing whitespace after entity
        if trailing:
            self._add_text(trailing)

        return ''

    def linebreak(self, token: dict[str, Any], state: BlockState) -> str:
        """Render hard line break.

        Args:
            token: Token dict
            state: Rendering state

        Returns:
            Empty string (newline already added)
        """
        self._add_text('\n')
        return ''

    def softbreak(self, token: dict[str, Any], state: BlockState) -> str:
        """Render soft line break.

        In standard Markdown, soft breaks (single newlines within a paragraph)
        are rendered as spaces for text wrapping. However, for Telegram messages,
        users expect single newlines to be preserved, so we render them as '\n'.

        Args:
            token: Token dict
            state: Rendering state

        Returns:
            Empty string (newline already added)
        """
        self._add_text('\n')
        return ''

    def link(self, token: dict[str, Any], state: BlockState) -> str:
        """Render link [text](url) or reference-style [text][ref].

        Reference-style links are detected by presence of 'ref' or 'label' field
        (added by Mistune when resolving link definitions).
        Can be visually marked with config.link_reference emoji.

        Note: Telegram requires valid URLs with scheme for text_link entities.
        Fragment-only URLs (#anchor) and relative paths are rendered as plain text.

        Args:
            token: Token dict with 'attrs' (link URL) and 'children' (link text)
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Get URL from attrs
        attrs = token.get('attrs', {})
        url = attrs.get('url', '') if isinstance(attrs, dict) else ''

        if not url:
            # No URL, just render children as plain text
            self._render_children(token, state)
            return ''

        # Validate URL for Telegram text_link entity
        # Telegram requires publicly accessible HTTP/HTTPS URLs or tg:// scheme
        # Rejects: fragments (#anchor), relative paths, localhost, private IPs
        is_valid_url = _is_valid_telegram_url(url)

        # Check if this is a reference-style link (Mistune adds 'ref' and 'label')
        is_reference_link = 'ref' in token or 'label' in token

        # Add reference indicator emoji if configured and this is a reference link
        # NOTE: Emoji is added BEFORE start_offset, so it's OUTSIDE the text_link entity
        if is_reference_link and self.config.link_reference:
            self._add_text(f'{self.config.link_reference} ')

        start_offset = self.current_offset

        # Render children (link text)
        if token.get('children'):
            self._render_children(token, state)
        else:
            # If no children, use URL as text
            self._add_text(url)

        # Per Telegram API spec, entity length must not include trailing whitespace
        trailing = self._remove_trailing_whitespace()

        length = self.current_offset - start_offset
        # Only add text_link entity for valid URLs
        if length > 0 and is_valid_url:
            self._add_entity('text_link', start_offset, length, url=url)

        # Re-add trailing whitespace after entity
        if trailing:
            self._add_text(trailing)

        return ''

    def image(self, token: dict[str, Any], state: BlockState) -> str:
        """Render image ![alt](src).

        Args:
            token: Token dict with 'attrs' containing 'url' and optional 'alt'
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Get children first (alt text is in children for images)
        children = token.get('children', [])
        alt_text = ''
        if children:
            # Extract text from children
            for child in children if isinstance(children, list) else [children]:
                if isinstance(child, str):
                    alt_text += child
                elif isinstance(child, dict) and child.get('type') == 'text':
                    alt_text += child.get('raw', '')

        # Get URL from attrs
        attrs = token.get('attrs', {})
        src = attrs.get('url', '') if isinstance(attrs, dict) else ''

        # Add image emoji if configured
        if self.config.image_emoji:
            self._add_text(f'{self.config.image_emoji} ')

        # Format: emoji [alt text](url) or emoji (url)
        if alt_text:
            self._add_text(alt_text)
            self._add_text(' ')
        self._add_text(f'({src})')
        return ''

    def strikethrough(self, token: dict[str, Any], state: BlockState) -> str:
        """Render strikethrough text (~~text~~)."""
        return self._render_inline_entity(token, state, 'strikethrough')

    # Block elements

    def paragraph(self, token: dict[str, Any], state: BlockState) -> str:
        """Render paragraph.

        Args:
            token: Token dict with 'children' key containing inline content
            state: Rendering state

        Returns:
            Rendered paragraph text with newlines
        """
        self._render_children(token, state)
        # Inside list_item, add only one newline to avoid double spacing
        # when paragraph is followed by nested list
        if self._in_list_item:
            self._add_text('\n')
        else:
            self._add_text('\n\n')
        return ''

    def heading(self, token: dict[str, Any], state: BlockState) -> str:
        """Render heading (like telegramify-markdown behavior).

        Supports two styles:
        - ATX style: # Heading (emoji + text, entire line bold)
        - Setext style: Heading\n─── (plain text + underline, no bold)

        Args:
            token: Token dict with 'attrs' containing level and 'children' for content
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Get level and style from token
        attrs = token.get('attrs', {})
        level = attrs.get('level', 1) if isinstance(attrs, dict) else 1
        style = token.get('style', 'atx')  # 'atx' or 'setext'

        # Check if this is a Setext-style heading
        if style == 'setext':
            # Setext headings: render as plain text with underline below
            self._render_children(token, state)

            # Uses configurable character and length
            self._add_text('\n')
            self._add_text(
                self.config.setext_underline_char * self.config.setext_underline_length
            )
            self._add_text('\n\n')
            return ''

        # ATX style: render with emoji prefix
        # Like telegramify-markdown: entire line (emoji + text) is bold
        emoji_levels = (
            self.config.head_level_1,
            self.config.head_level_2,
            self.config.head_level_3,
            self.config.head_level_4,
            self.config.head_level_5,
            self.config.head_level_6,
        )

        # Get emoji (level is 1-based, tuple is 0-based)
        emoji = emoji_levels[level - 1] if 1 <= level <= 6 else emoji_levels[0]

        # Format: 📌 Heading Text (all bold!)
        start_offset = self.current_offset  # Start before emoji
        self._add_text(f'{emoji} ')
        self._render_children(token, state)

        # Per Telegram API spec, entity length must not include trailing whitespace
        trailing = self._remove_trailing_whitespace()

        length = self.current_offset - start_offset  # Includes emoji + text

        # Make entire line bold (emoji + text)
        if length > 0:
            self._add_entity('bold', start_offset, length)

        # Re-add trailing whitespace after entity (before adding final newlines)
        if trailing:
            self._add_text(trailing)

        self._add_text('\n\n')
        return ''

    def thematic_break(self, token: dict[str, Any], state: BlockState) -> str:
        """Render thematic break (horizontal rule).

        Like telegramify-markdown: renders as three hyphens (default).
        This is different from setext underline which uses box drawing chars.

        Args:
            token: Token dict
            state: Rendering state

        Returns:
            Empty string (separator already added)
        """
        # Configurable via thematic_break_char and thematic_break_length
        self._add_text(self.config.thematic_break_char * self.config.thematic_break_length)
        self._add_text('\n\n')
        return ''

    def block_text(self, token: dict[str, Any], state: BlockState) -> str:
        """Render block text.

        Args:
            token: Token dict with 'children'
            state: Rendering state

        Returns:
            Rendered block text
        """
        self._render_children(token, state)
        # Inside list_item, add newline after block_text (similar to paragraph)
        if self._in_list_item:
            self._add_text('\n')
        return ''

    def block_code(self, token: dict[str, Any], state: BlockState) -> str:
        """Render code block (```code```).

        Args:
            token: Token dict with 'raw' (code) and optional 'attrs' (language info)
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        code_content = token.get('raw', '')
        if not code_content:
            return ''

        code_text = str(code_content).rstrip()
        if not code_text:
            return ''

        # Get language from attrs
        attrs = token.get('attrs', {})
        language = None
        if isinstance(attrs, dict):
            info = attrs.get('info')
            if info and isinstance(info, str):
                language = info.split()[0]

        start_offset = self.current_offset
        self._add_text(code_text)
        length = self.current_offset - start_offset

        # Add entity with optional language
        if language:
            self._add_entity('pre', start_offset, length, language=language)
        else:
            self._add_entity('pre', start_offset, length)

        self._add_text('\n\n')
        return ''

    def block_quote(self, token: dict[str, Any], state: BlockState) -> str:
        """Render block quote.

        Args:
            token: Token dict with 'children'
            state: Rendering state

        Returns:
            Rendered block quote with formatting
        """
        start_offset = self.current_offset
        self._render_children(token, state)

        # Per Telegram API spec, entity length must not include trailing whitespace
        # Remove any trailing whitespace (spaces, tabs, newlines) added by children
        trailing = self._remove_trailing_whitespace()
        quote_length = self.current_offset - start_offset

        self._add_entity('blockquote', start_offset, quote_length)

        # Re-add trailing whitespace OR add standard spacing if no trailing
        # The children (paragraphs) typically already add \n\n, so we reuse that
        # If no trailing, add standard block spacing
        if trailing:
            self._add_text(trailing)
        else:
            self._add_text('\n\n')
        return ''

    def block_html(self, token: dict[str, Any], state: BlockState) -> str:
        """Render block HTML as code block with HTML syntax.

        HTML tags are rendered as code blocks with language='html' for clarity.

        Args:
            token: Token dict with 'raw' (HTML content)
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        html_content = token.get('raw', '')
        if not html_content:
            return ''

        # Convert to string and strip trailing whitespace (not leading)
        html_text = str(html_content).rstrip()
        if not html_text:
            return ''

        start_offset = self.current_offset
        self._add_text(html_text)
        length = self.current_offset - start_offset

        # Create pre entity with html language
        self._add_entity('pre', start_offset, length, language='html')
        self._add_text('\n\n')
        return ''

    def list(self, token: dict[str, Any], state: BlockState) -> str:
        """Render list (ordered or unordered).

        Args:
            token: Token dict with 'children' (list items) and 'attrs' (ordered flag)
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Get list attributes
        attrs = token.get('attrs', {})
        ordered = attrs.get('ordered', False) if isinstance(attrs, dict) else False
        depth = attrs.get('depth', 0) if isinstance(attrs, dict) else 0

        # Push list state onto stack for list_item to access
        self._list_stack.append(
            {
                'ordered': ordered,
                'counter': 0,  # Will be incremented by list_item
                'depth': depth,  # Nesting level (0-based, provided by Mistune)
            }
        )

        # Render list items
        self._render_children(token, state)

        # Pop list state
        self._list_stack.pop()

        self._add_text('\n')
        return ''

    def list_item(self, token: dict[str, Any], state: BlockState) -> str:
        """Render list item (numbered or bullet).

        Note: Task list items are handled by task_list_item() method.

        Args:
            token: Token dict with 'children'
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Add prefix based on list type with visual indentation for nested lists
        if self._list_stack:
            # Get current list state from stack
            list_state = self._list_stack[-1]
            depth = list_state.get('depth', 0)

            # Add indentation for nested lists (visual spacing)
            indent = ' ' * (depth * self.INDENT_PER_LEVEL)
            self._add_text(indent)

            if list_state['ordered']:
                # Ordered list: increment counter and use "1. ", "2. ", etc.
                list_state['counter'] += 1
                self._add_text(f'{list_state["counter"]}. ')
            else:
                # Unordered list: use bullet
                self._add_text('• ')
        else:
            # Fallback (shouldn't happen)
            self._add_text('• ')

        # Render children with adjusted paragraph spacing
        self._in_list_item = True
        self._render_children(token, state)
        self._in_list_item = False

        # Remove trailing paragraph breaks if any, add single newline
        self._remove_trailing_newlines(max_newlines=0)
        self._add_text('\n')
        return ''

    def task_list_item(self, token: dict[str, Any], state: BlockState) -> str:
        """Render task list item (- [ ] or - [x]).

        Args:
            token: Token dict with 'children' and 'attrs' containing 'checked' status
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Get checked status
        attrs = token.get('attrs', {})
        checked = attrs.get('checked', False) if isinstance(attrs, dict) else False

        # Add indentation for nested task lists
        if self._list_stack:
            depth = self._list_stack[-1].get('depth', 0)
            indent = ' ' * (depth * self.INDENT_PER_LEVEL)
            self._add_text(indent)

        # Add checkbox emoji
        checkbox = self.config.task_completed if checked else self.config.task_uncompleted
        self._add_text(f'{checkbox} ')

        # Render children with adjusted paragraph spacing
        self._in_list_item = True
        self._render_children(token, state)
        self._in_list_item = False

        # Remove trailing paragraph breaks if any, add single newline
        self._remove_trailing_newlines(max_newlines=0)
        self._add_text('\n')
        return ''

    # Table rendering methods

    def blank_line(self, token: dict[str, Any], state: BlockState) -> str:
        """Render blank line (just skip it).

        Args:
            token: Token dict
            state: Rendering state

        Returns:
            Empty string
        """
        # Don't add anything for blank lines
        return ''

    def table(self, token: dict[str, Any], state: BlockState) -> str:
        """Render table with Unicode box-drawing characters.

        Collects all table data first to calculate column widths,
        then renders the entire table with proper formatting.

        Args:
            token: Token dict with 'children' (table_head and table_body)
            state: Rendering state

        Returns:
            Empty string (text already added)
        """
        # Initialize table data collection
        self._table_data = {
            'headers': [],
            'rows': [],
            'current_row': [],
        }

        # Render children to collect data
        self._render_children(token, state)

        # Now render the collected table
        if self._table_data:
            table_text = self._render_table_simple(
                self._table_data['headers'], self._table_data['rows']
            )

            if table_text:
                start_offset = self.current_offset
                self._add_text(table_text)

                # Per Telegram API spec, entity length must not include trailing whitespace
                trailing = self._remove_trailing_whitespace()

                length = self.current_offset - start_offset

                # Wrap entire table in 'pre' entity for monospace font
                # Like telegramify-markdown: simple ASCII table in code block
                if length > 0:
                    self._add_entity('pre', start_offset, length)

                # Re-add trailing whitespace after entity
                if trailing:
                    self._add_text(trailing)

                self._add_text('\n\n')

        # Clean up
        self._table_data = None
        return ''

    def table_head(self, token: dict[str, Any], state: BlockState) -> str:
        """Collect table header cells.

        Note: In Mistune, table_head contains cells directly (no table_row wrapper).

        Args:
            token: Token dict with 'children' (table cells)
            state: Rendering state

        Returns:
            Empty string (data collected in state)
        """
        if self._table_data is not None:
            # Headers are direct children of table_head (no table_row)
            self._table_data['current_row'] = []
            self._render_children(token, state)
            self._table_data['headers'] = self._table_data['current_row']
        return ''

    def table_body(self, token: dict[str, Any], state: BlockState) -> str:
        """Collect table body rows.

        Args:
            token: Token dict with 'children' (table rows)
            state: Rendering state

        Returns:
            Empty string (data collected in state)
        """
        self._render_children(token, state)
        return ''

    def table_row(self, token: dict[str, Any], state: BlockState) -> str:
        """Collect table row cells (for table_body only).

        Note: Headers don't use table_row - they're direct children of table_head.

        Args:
            token: Token dict with 'children' (table cells)
            state: Rendering state

        Returns:
            Empty string (data collected in state)
        """
        if self._table_data is not None:
            self._table_data['current_row'] = []
            self._render_children(token, state)
            # Save the row (this is for body only)
            self._table_data['rows'].append(self._table_data['current_row'])

        return ''

    def table_cell(self, token: dict[str, Any], state: BlockState) -> str:
        """Collect table cell content.

        Args:
            token: Token dict with 'children' (cell content)
            state: Rendering state

        Returns:
            Empty string (data collected in state)
        """
        if self._table_data is not None:
            # Create temporary renderer to extract cell text without affecting main output
            temp_renderer = TelegramRenderer(self.config)
            temp_renderer._render_children(token, state)
            cell_text = temp_renderer.output_text.strip()

            # Store the cell
            self._table_data['current_row'].append(cell_text)

        return ''

    def _render_table_simple(
        self, headers: Sequence[str], rows: Sequence[Sequence[str]]
    ) -> str:
        """Render table with simple ASCII characters (|, -).

        Similar to telegramify-markdown approach: simple ASCII table that works
        well with pre entity (monospace font).

        Args:
            headers: Sequence of header cell texts
            rows: Sequence of rows, each row is a sequence of cell texts

        Returns:
            Formatted table as string with ASCII characters
        """
        if not headers:
            return ''

        # Calculate column widths (max of header and all rows)
        num_cols = len(headers)
        col_widths = [len(h) for h in headers]

        for row in rows:
            for i, cell in enumerate(row):
                if i < num_cols:
                    col_widths[i] = max(col_widths[i], len(cell))

        # Simple ASCII table like standard Markdown:
        # | Name  | Age |
        # |-------|-----|
        # | Bob   | 25  |

        lines = []

        # Header row: | Name | Age |
        header_cells = [headers[i].ljust(col_widths[i]) for i in range(num_cols)]
        header_line = '| ' + ' | '.join(header_cells) + ' |'
        lines.append(header_line)

        # Separator: |-------|-----|
        separator = '|' + '|'.join('-' * (w + 2) for w in col_widths) + '|'
        lines.append(separator)

        # Data rows: | Bob   | 25  |
        for row in rows:
            row_cells = []
            for i in range(num_cols):
                cell = row[i] if i < len(row) else ''
                row_cells.append(cell.ljust(col_widths[i]))
            row_line = '| ' + ' | '.join(row_cells) + ' |'
            lines.append(row_line)

        return '\n'.join(lines)

    def finalize(self) -> tuple[str, Sequence[MessageEntity]]:
        """Finalize rendering and return result.

        Removes trailing whitespace and filters invalid entities.

        Note: Chunking is handled at converter level (converter.py), not here.
        This renderer processes a single chunk of blocks and returns one result.

        Returns:
            (plain_text, entities) tuple.
        """
        # Remove trailing whitespace
        text = self.output_text.rstrip()

        # Calculate how much was trimmed
        text_length_utf16 = utf16_len(text)

        # Filter entities that extend beyond the trimmed text
        valid_entities = [
            entity
            for entity in self.entities
            if entity['offset'] + entity['length'] <= text_length_utf16
        ]

        return (text, valid_entities)
