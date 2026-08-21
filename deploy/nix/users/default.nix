{
  flake.nixosModules = {
    users-vizqq = import ./vizqq.nix;
    users-wizard = import ./wizard.nix;
    users-github-ci = import ./github-ci.nix;
  };
}
