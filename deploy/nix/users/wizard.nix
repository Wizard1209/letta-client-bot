{
  users.users = {
    wizard = {
      description = "Vladimir Bobrikov";
      isNormalUser = true;
      openssh.authorizedKeys.keys = [
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICs8Wqmt6ahJfs823fdKyhJvC4VHEu88u6RtPoBCdhqY ed25519"
      ];
      extraGroups = [
        "wheel"
        "networkmanager"
      ];
    };
  };
}
