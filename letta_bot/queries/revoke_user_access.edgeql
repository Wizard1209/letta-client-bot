update AuthorizationRequest
filter .user.telegram_id = <int64>$telegram_id and .resource_type = ResourceType.access_identity
set { status := AuthStatus.revoked };
# TODO: return identity for information and notification