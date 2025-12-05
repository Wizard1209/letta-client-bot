# Check if user already has a pending agent access request for a specific agent
select exists (
    select AuthorizationRequest
    filter
        .user.telegram_id = <int64>$telegram_id
        and .resource_type = <ResourceType>$resource_type
        and .resource_id = <str>$agent_id
        and .status = <AuthStatus>$status
)
