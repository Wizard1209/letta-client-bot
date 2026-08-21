{ inputs, ... }:
{
  imports = with inputs; [
    git-hooks-nix.flakeModule
  ];
  perSystem =
    { ... }:
    {
      pre-commit = {
        settings.hooks = {
          # nix formatter (rfc-style)
          nixfmt.enable = true;
          # removes dead nix code
          deadnix.enable = true;
          # prevents use of nix anti-patterns
          statix = {
            enable = true;
            args = [
              "fix"
            ];
          };
        };
      };
    };
}
