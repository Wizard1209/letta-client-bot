{ inputs, ... }:
{
  perSystem =
    { system, ... }:
    {
      checks = inputs.deploy-rs.lib.${system}.deployChecks inputs.self.deploy;
    };
}
