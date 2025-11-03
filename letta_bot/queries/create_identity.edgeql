insert Identity {
    user := (select User filter .telegram_id = <int64>$telegram_id),
    identifier_key := <str>$identifier_key,
    identity_id := <str>$identity_id
};