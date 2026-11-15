{
  description = "MediaWaiter checks";

  inputs = {
    nixpkgs.url = "github:cachix/devenv-nixpkgs/rolling";
    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    git-hooks,
  }: let
    systems = [
      "x86_64-linux"
      "aarch64-linux"
      "x86_64-darwin"
      "aarch64-darwin"
    ];
    forAllSystems = nixpkgs.lib.genAttrs systems;
  in {
    checks = forAllSystems (system: {
      pre-commit-check = git-hooks.lib.${system}.run {
        src = ./.;
        hooks = {
          check-merge-conflicts.enable = true;
          check-added-large-files.enable = true;
          check-toml.enable = true;
          check-yaml.enable = true;
          detect-private-keys.enable = true;
          ripsecrets.enable = true;
          ruff.enable = true;
          ruff-format.enable = true;
          trim-trailing-whitespace.enable = true;
          yamlfmt.enable = true;
        };
      };
    });
  };
}
