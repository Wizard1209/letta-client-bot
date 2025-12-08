# Get authorization request by ID without modifying it
select AuthorizationRequest {
    id,
    user: {
        telegram_id,
        username,
        first_name,
        last_name,
        full_name
    },
    resource_id,
    resource_type,
    status,
    message,
    created_at
}
filter .id = <uuid>$id;
