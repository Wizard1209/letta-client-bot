select AuthorizationRequest {
    id,
    user: { telegram_id, first_name, full_name, username },
    resource_id,
}
filter
    .resource_type = ResourceType.access_agent
    and .resource_id = <str>$agent_id
    and .status = AuthStatus.pending
