select AuthorizationRequest {**}
filter .status = <optional AuthStatus>$status ?? .status
order by .created_at;