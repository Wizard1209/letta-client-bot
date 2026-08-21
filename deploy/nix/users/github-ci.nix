{ ... }:
{
  users.users.github-ci = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA+ed2XXpDNh9Nr5ffKC9KTWKK3MNXVTz4bbbRRbA21j github-deploy"
    ];
  };
}
