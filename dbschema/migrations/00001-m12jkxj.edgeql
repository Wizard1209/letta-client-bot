CREATE MIGRATION m12jkxjpgwsw27yws4hgbn7cyl7z34rpdqbkzl7lwiyndv6xp33gwq
    ONTO initial
{
  CREATE SCALAR TYPE default::AuthStatus EXTENDING enum<pending, authorized, denied>;
  CREATE FUTURE simple_scoping;
  CREATE TYPE default::AuthRecord {
      CREATE PROPERTY letta_identity_id: std::str;
      CREATE INDEX ON (.letta_identity_id);
      CREATE REQUIRED PROPERTY status: default::AuthStatus {
          SET default := (default::AuthStatus.pending);
      };
      CREATE INDEX ON (.status);
      CREATE PROPERTY approved_at: std::datetime;
      CREATE PROPERTY approved_by: std::int64;
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET default := (std::datetime_current());
      };
      CREATE PROPERTY denied_at: std::datetime;
      CREATE PROPERTY denied_by: std::int64;
      CREATE REQUIRED PROPERTY updated_at: std::datetime {
          SET default := (std::datetime_current());
      };
  };
  CREATE TYPE default::User {
      CREATE PROPERTY username: std::str;
      CREATE INDEX ON (.username);
      CREATE REQUIRED PROPERTY telegram_id: std::int64 {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE INDEX ON (.telegram_id);
      CREATE REQUIRED PROPERTY first_name: std::str;
      CREATE PROPERTY last_name: std::str;
      CREATE PROPERTY full_name := ((.first_name ++ ((' ' ++ .last_name) IF EXISTS (.last_name) ELSE '')));
      CREATE REQUIRED PROPERTY first_seen: std::datetime {
          SET default := (std::datetime_current());
      };
      CREATE REQUIRED PROPERTY is_bot: std::bool {
          SET default := false;
      };
      CREATE PROPERTY language_code: std::str;
      CREATE REQUIRED PROPERTY last_seen: std::datetime {
          SET default := (std::datetime_current());
      };
  };
  ALTER TYPE default::AuthRecord {
      CREATE REQUIRED LINK user: default::User {
          CREATE CONSTRAINT std::exclusive;
      };
  };
};
