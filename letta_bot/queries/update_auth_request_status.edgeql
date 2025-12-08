# Update authorization request status
update AuthorizationRequest
filter .id = <uuid>$id
set {
    status := <AuthStatus>$auth_status
};
