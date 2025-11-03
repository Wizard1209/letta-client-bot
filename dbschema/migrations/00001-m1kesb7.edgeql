CREATE MIGRATION m1kesb7sw3airamtd4ehxrna6gpwcd3yzleik5xrr4tkluphj37tcq
    ONTO initial
{
  CREATE SCALAR TYPE default::AuthStatus EXTENDING enum<pending, allowed, denied, revoked>;
  CREATE SCALAR TYPE default::ResourceType EXTENDING enum<access_identity, create_agent_from_template, access_agent>;
  CREATE FUTURE simple_scoping;
  CREATE TYPE default::AuthorizationRequest {
      CREATE REQUIRED PROPERTY status: default::AuthStatus {
          SET default := (default::AuthStatus.pending);
      };
      CREATE INDEX ON (.status);
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET default := (std::datetime_of_transaction());
      };
      CREATE PROPERTY message: std::str;
      CREATE REQUIRED PROPERTY resource_id: std::str;
      CREATE REQUIRED PROPERTY resource_type: default::ResourceType;
      CREATE PROPERTY response: std::str;
      CREATE PROPERTY updated_by: std::int64;
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
          SET default := (std::datetime_of_transaction());
      };
      CREATE REQUIRED PROPERTY is_bot: std::bool {
          SET default := false;
      };
      CREATE PROPERTY language_code: std::str;
  };
  ALTER TYPE default::AuthorizationRequest {
      CREATE REQUIRED LINK user: default::User;
  };
  CREATE TYPE default::Identity {
      CREATE REQUIRED LINK user: default::User {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET default := (std::datetime_of_transaction());
      };
      CREATE REQUIRED PROPERTY identifier_key: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE REQUIRED PROPERTY identity_id: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE PROPERTY selected_agent: std::str;
  };
};
