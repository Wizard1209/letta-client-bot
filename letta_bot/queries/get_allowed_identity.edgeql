select AuthorizationRequest { id } 
filter .user.telegram_id = <int64>$telegram_id
    and .status = AuthStatus.allowed;
