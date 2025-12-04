"""Extensions for Letta SDK missing methods.

This module provides workarounds for methods that exist in the REST API
but are not yet implemented in the Python SDK.
"""

from typing import TYPE_CHECKING, Any

from letta_client._base_client import AsyncPaginator, make_request_options
from letta_client._models import BaseModel
from letta_client._types import NotGiven
from letta_client.pagination import AsyncArrayPage
from letta_client.types.agents.message import Message

if TYPE_CHECKING:
    from letta_client import AsyncLetta


class FunctionDefinition(BaseModel):
    """Function definition model matching the REST API response."""

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class FunctionTool(BaseModel):
    """Function tool model matching the REST API response."""

    function: FunctionDefinition
    type: str = 'function'


class Template(BaseModel):
    """Template model matching the REST API response."""

    id: str
    name: str
    project_slug: str
    project_id: str
    description: str | None = None
    latest_version: str
    template_deployment_slug: str
    updated_at: str


class TemplatesPage(AsyncArrayPage[Template]):
    """Custom page for templates that uses 'templates' field instead of 'items'.

    Note: Use .templates to access the list of templates, not .items.
    The _get_page_items() override allows iteration via async for.
    """

    templates: list[Template]

    def _get_page_items(self) -> list[Template]:
        """Override to return templates for async iteration."""
        return self.templates


class ContextWindowOverview(BaseModel):
    """Overview of the context window, including the number of messages and tokens."""

    context_window_size_max: int
    context_window_size_current: int
    num_messages: int
    num_archival_memory: int
    num_recall_memory: int
    num_tokens_external_memory_summary: int
    external_memory_summary: str
    num_tokens_system: int
    system_prompt: str
    num_tokens_core_memory: int
    core_memory: str
    num_tokens_summary_memory: int
    summary_memory: str | None = None
    num_tokens_functions_definitions: int
    functions_definitions: list[FunctionTool] | None = None
    num_tokens_messages: int
    messages: list[Message]


async def context_window_overview(
    client: 'AsyncLetta',
    agent_id: str,
    *,
    extra_headers: dict[str, str] | None = None,
    extra_query: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None | NotGiven = None,
) -> ContextWindowOverview:
    """Fetch agent context window overview from Letta REST API.

    Workaround for missing client.agents.context() method in SDK v1.0.0.

    Args:
        client: The Letta client instance
        agent_id: The agent ID to fetch context overview for
        extra_headers: Send extra headers
        extra_query: Add additional query parameters
        extra_body: Add additional JSON properties
        timeout: Override the client-level default timeout

    Returns:
        ContextWindowOverview object with context usage details

    Raises:
        httpx.HTTPError: If the HTTP request fails
        APIError: If the API returns an error
    """
    return await client.get(
        f'/v1/agents/{agent_id}/context',
        cast_to=ContextWindowOverview,
        options=make_request_options(
            extra_headers=extra_headers,
            extra_query=extra_query,
            extra_body=extra_body,
            timeout=timeout,
        ),
    )


async def list_templates(
    client: 'AsyncLetta',
    project_id: str,
    *,
    extra_headers: dict[str, str] | None = None,
    extra_query: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None | NotGiven = None,
) -> AsyncPaginator[Template, TemplatesPage]:
    """List templates for a specific project.

    Workaround for missing client.templates.list() method in SDK v1.0.0.

    Args:
        client: The Letta client instance
        project_id: Project id to filter templates (required)
        extra_headers: Send extra headers
        extra_query: Add additional query parameters
        extra_body: Add additional JSON properties
        timeout: Override the client-level default timeout

    Returns:
        AsyncPaginator that yields Template objects
    """

    # Build query with project_id
    query_params = {'project_id': project_id}
    if extra_query:
        query_params.update(extra_query)

    # Use the get_api_list method with custom TemplatesPage
    return client.get_api_list(
        '/v1/templates',
        page=TemplatesPage,
        options=make_request_options(
            extra_headers=extra_headers,
            extra_query=query_params,
            extra_body=extra_body,
            timeout=timeout,
        ),
        model=Template,
    )
