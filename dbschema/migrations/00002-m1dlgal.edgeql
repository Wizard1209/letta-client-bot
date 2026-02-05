CREATE MIGRATION m1dlgaln77vhnprx774artpqggdrcyljq56p433x6hwawy5ogyhxiq
    ONTO m1kesb7sw3airamtd4ehxrna6gpwcd3yzleik5xrr4tkluphj37tcq
{
  ALTER TYPE default::AuthorizationRequest {
      CREATE CONSTRAINT std::exclusive ON ((.user, .resource_type, .resource_id)) EXCEPT ((.status != default::AuthStatus.pending));
  };
  ALTER TYPE default::Identity {
      DROP PROPERTY identity_id;
  };
};
