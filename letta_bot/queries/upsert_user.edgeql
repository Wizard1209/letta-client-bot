select (
    insert User {
      telegram_id := <int64>$telegram_id,
      is_bot := <bool>$is_bot,
      first_name := <str>$first_name,
      last_name := <optional str>$last_name ?? '',
      username := <optional str>$username ?? '',
      language_code := <optional str>$language_code ?? ''
    }
    unless conflict on .telegram_id
    else (
      update User
      filter .telegram_id = <int64>$telegram_id
      set {
        first_name := <str>$first_name,
        last_name := <optional str>$last_name ?? '',
        username := <optional str>$username ?? '',
        language_code := <optional str>$language_code ?? ''
      }
    )
  ) {*};
