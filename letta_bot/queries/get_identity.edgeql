select Identity {
    user: {*},
    identifier_key,
    selected_agent,
    created_at,
}
filter .user.telegram_id = <int64>$telegram_id;
