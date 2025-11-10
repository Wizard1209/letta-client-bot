select AuthorizationRequest {**}
filter .status = <optional AuthStatus>$status ?? .status
order by .user.telegram_id then .created_at;