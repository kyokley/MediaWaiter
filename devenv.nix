{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
   env = {
    GREET = "MV";
    MW_SECRET_FILE = "secret.txt";
    MW_IGNORE_MEDIA_DIR_CHECKS = "true";
    PYTHONPATH = ".";
    MW_BASE_PATH = "/home/yokley/workspace/MV/media";
    MW_MEDIA_DIRS = "tv,movies";
    MW_WAITER_USERNAME = "waiter";
    MW_WAITER_PASSWORD = "waiter123";
    MW_MEDIAVIEWER_BASE_URL = "http://127.0.0.1:8000/mediaviewer";
    MW_EXTERNAL_MEDIAVIEWER_BASE_URL = "http://localhost:8000/mediaviewer";
    MW_MEDIAVIEWER_SUFFIX = "ALFRED-ENCODED";
    MW_MEDIAWAITER_PROTOCOL = "http://";
    MW_USE_NGINX = "false";
  };

  # https://devenv.sh/packages/
  packages = [
    pkgs.docker
  ];

  # https://devenv.sh/scripts/
  scripts = {
    touch-history.exec = ''
        mkdir -p logs
        chmod -R 777 logs
    '';
    build.exec = ''
      nix build .#dev-image
      docker load < result
    '';
    up.exec = ''
      uv run flask --app src/mediawaiter/waiter.py run
    '';
  };

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
      version = "3.13";
      uv = {
        enable = true;
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
  git-hooks.hooks = {
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
  # processes.ping.exec = "ping example.com";

  # See full reference at https://devenv.sh/reference/options/
}
