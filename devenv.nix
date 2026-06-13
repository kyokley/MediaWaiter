{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env = {
    GREET = "MW";
    DOCKER_COMPOSE_TEST_ARGS = "-f docker-compose.yml -f docker-compose.test.yml";
    USE_HOST_NET = "0";
    NO_CACHE = "0";
    UID = "1000";
  };

  # https://devenv.sh/packages/
  # packages = [
  #   pkgs.git
  # ];

  # https://devenv.sh/scripts/
  scripts = {
    hello.exec = "echo hello from $GREET";
    build-dev.exec = ''
      docker build \
        $(test ${config.env.USE_HOST_NET} -ne 0 && echo "--network=host" || echo "") \
        $(test ${config.env.NO_CACHE} -ne 0 && echo "--no-cache" || echo "") \
        --build-arg UID=${config.env.UID} \
        --tag=kyokley/mediawaiter \
        --target=dev \
        .
    '';
    pytest.exec = ''
      build-dev
      ${pkgs.docker}/bin/docker compose ${config.env.DOCKER_COMPOSE_TEST_ARGS} run --rm mediawaiter pytest
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
      version = "3.12";
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
