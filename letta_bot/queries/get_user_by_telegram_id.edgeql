# Get user by telegram_id
select User {
    telegram_id,
    username,
    first_name,
    last_name,
    full_name
}
filter .telegram_id = <int64>$telegram_id;
