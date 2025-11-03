select(update AuthorizationRequest
    filter .id = <uuid>$id
    set { status := <AuthStatus>$auth_status }
) {user: {*}, resource_type, resource_id};