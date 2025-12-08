select exists (
    select AuthorizationRequest
    filter
        .user.telegram_id = <int64>$telegram_id
        and .resource_type = <ResourceType>$resource_type
        and .status = <optional AuthStatus>$status ?? AuthStatus.pending
        and (
            <optional str>$resource_id ?? '' = ''
            or .resource_id = <optional str>$resource_id
        )
)
