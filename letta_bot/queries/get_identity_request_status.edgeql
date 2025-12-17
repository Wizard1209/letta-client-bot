# Returns identity request if pending or allowed (null if none or denied/revoked)
select AuthorizationRequest { id, status }
filter .user.telegram_id = <int64>$telegram_id
    and .resource_type = ResourceType.access_identity
    and .status in {AuthStatus.pending, AuthStatus.allowed}
limit 1;
