# Revoke agent access authorization request
# Used when admin detaches agent from user's identity
update AuthorizationRequest
filter
    .user.telegram_id = <int64>$telegram_id
    and .resource_type = <ResourceType>$resource_type
    and .resource_id = <str>$agent_id
    and .status = <AuthStatus>$current_status
set {
    status := <AuthStatus>$new_status
}
