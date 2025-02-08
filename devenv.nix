{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env.MW_IGNORE_MEDIA_DIR_CHECKS = if config.containers.prod.isBuilding then "false" else "true";

  # https://devenv.sh/packages/
  # packages = [
  #   pkgs.git
  # ];

  # https://devenv.sh/scripts/
  # scripts.hello.exec = "echo hello from $GREET";

  # enterShell = ''
  #   # hello
  # '';

  # https://devenv.sh/tests/
  # enterTest = ''
  #   # echo "Running tests"
  #   # git --version | grep "2.42.0"
  # '';

  # https://devenv.sh/services/
  # services.postgres.enable = true;

  # https://devenv.sh/languages/
  # languages.nix.enable = true;
  languages = {
    python = {
      enable = true;
      version = "3.12";
      uv = {
        enable = true;
        sync = {
          enable = true;
          extras = [] ++ lib.optionals (config.containers.dev.isBuilding) ["dev"];
        };
      };
    };

    javascript = {
      enable = true;
      npm = {
        enable = true;
        install.enable = true;
      };
    };
  };

  # https://devenv.sh/pre-commit-hooks/
  pre-commit.hooks = {
    hadolint.enable = false;
    check-merge-conflicts.enable = true;
    check-added-large-files.enable = true;
    check-toml.enable = true;
    check-yaml.enable = true;
    checkmake.enable = true;
    detect-private-keys.enable = true;
    ripsecrets.enable = true;
    ruff.enable = true;
    ruff-format.enable = true;
    trim-trailing-whitespace.enable = true;
    yamlfmt.enable = true;
    yamllint.enable = false;
  };

  # https://devenv.sh/processes/
  processes.dev.exec = "uv run python waiter.py";
  containers.dev.name = "kyokley/mediawaiter";
  containers.dev.startupCommand = config.processes.dev.exec;

  containers.prod.name = "kyokley/mediawaiter";
  containers.prod.startupCommand = "uv run gunicorn waiter:gunicorn_app";

  # See full reference at https://devenv.sh/reference/options/
}
