select exists (
    select AuthorizationRequest
    filter
        .user.telegram_id = <int64>$telegram_id
        and .resource_type = <ResourceType>$resource_type
        and .status = AuthStatus.pending
)
