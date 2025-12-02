select AuthorizationRequest { id } 
filter .user.telegram_id = <int64>$telegram_id
    and .status = AuthStatus.allowed and .resource_type = ResourceType.access_identity;
