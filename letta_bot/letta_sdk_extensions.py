"""Extensions for Letta SDK missing methods.

This module provides workarounds for methods that exist in the REST API
but are not yet implemented in the Python SDK.
"""

from typing import TYPE_CHECKING, Any

from letta_client._base_client import AsyncPaginator, make_request_options
from letta_client._models import BaseModel
from letta_client._types import NotGiven
from letta_client.pagination import AsyncArrayPage

if TYPE_CHECKING:
    from letta_client import AsyncLetta


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
