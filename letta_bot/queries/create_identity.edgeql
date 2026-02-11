insert Identity {
    user := (select User filter .telegram_id = <int64>$telegram_id),
    identifier_key := <str>$identifier_key
};