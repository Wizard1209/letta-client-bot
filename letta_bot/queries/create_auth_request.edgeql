insert AuthorizationRequest {
    user := (select User filter .telegram_id = <int64>$telegram_id),

    resource_type := <ResourceType>$resource_type,
    resource_id := <str>$resource_id,

    # default status is pending
    # maybe include message in the future
};