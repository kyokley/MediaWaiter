{
  description = "App to serve HTML5 videos";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

    # Core pyproject-nix ecosystem tools
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";

    # Ensure consistent dependencies between these tools
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs";
    pyproject-build-systems.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
  };

  outputs = { self, nixpkgs, flake-utils, uv2nix, pyproject-nix, pyproject-build-systems, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3; # Your desired Python version

        # 1. Load Project Workspace (parses pyproject.toml, uv.lock)
        workspace = uv2nix.lib.workspace.loadWorkspace {
          workspaceRoot = ./.; # Root of your flake/project
        };

        # 2. Generate Nix Overlay from uv.lock (via workspace)
        uvLockedOverlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel"; # Or "sdist"
        };

        # 3. Placeholder for Your Custom Package Overrides
        myCustomOverrides = final: prev: {
          coverage = prev.coverage.overrideAttrs (old: {
            buildInputs = (old.buildInputs or []) ++ final.resolveBuildSystem {setuptools = [];};
          });
        };

        # 4. Construct the Final Python Package Set
        pythonSet =
          (pkgs.callPackage pyproject-nix.build.packages { inherit python; })
          .overrideScope (nixpkgs.lib.composeManyExtensions [
            pyproject-build-systems.overlays.default # For build tools
            uvLockedOverlay                          # Your locked dependencies
            myCustomOverrides                        # Your fixes
          ]);

        # --- This is where your project's metadata is accessed ---
        projectNameInToml = "mediawaiter"; # MUST match [project.name] in pyproject.toml!
        thisProjectAsNixPkg = pythonSet.${projectNameInToml};
        # ---

        # 5. Create the Python Runtime Environment
        appPythonEnv = pythonSet.mkVirtualEnv
          (thisProjectAsNixPkg.pname + "-env")
          workspace.deps.default; # Uses deps from pyproject.toml [project.dependencies]

        devPythonEnv = pythonSet.mkVirtualEnv
          (thisProjectAsNixPkg.pname + "-env")
          workspace.deps.all; # Uses deps from pyproject.toml [project.dependencies]

        # Node/NPM stuff
        nodeDependencies = (pkgs.callPackage ./default.nix {}).nodeDependencies;
      in
      {
        # Development Shell
        devShells.default = pkgs.mkShell {
          packages = [ devPythonEnv pkgs.ruff pkgs.uv ];
          shellHook = ''
            export PYTHONPATH=.
            export MW_IGNORE_MEDIA_DIR_CHECKS=true
          '';
        };

        # Nix Package for Your Application
        packages.default = pkgs.stdenv.mkDerivation {
          pname = thisProjectAsNixPkg.pname;
          version = thisProjectAsNixPkg.version;
          src = ./.; # Source of your main script

          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = [ appPythonEnv ]; # Runtime Python environment

          installPhase = ''
            mkdir -p $out/bin $out/lib

            cp ./gunicorn.conf.py $out/lib/

            makeWrapper ${appPythonEnv}/bin/gunicorn $out/bin/${thisProjectAsNixPkg.pname} \
              --add-flags "--config=$out/lib/gunicorn.conf.py" \
              --add-flags src.mediawaiter.waiter:gunicorn_app
          '';
        };
        packages.${thisProjectAsNixPkg.pname} = self.packages.${system}.default;

        packages.dev = pkgs.stdenv.mkDerivation {
          pname = thisProjectAsNixPkg.pname;
          version = thisProjectAsNixPkg.version;
          src = ./.; # Source of your main script

          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = [ devPythonEnv ]; # Runtime Python environment

          installPhase = ''
            mkdir -p $out/bin $out/lib

            cp -r . $out/lib/mediawaiter
            cp -r ${nodeDependencies}/lib/node_modules/* $out/lib/mediawaiter/src/mediawaiter/static/

            makeWrapper ${devPythonEnv}/bin/mediawaiter $out/bin/${thisProjectAsNixPkg.pname} \
              --set PYTHONPATH $out/lib/mediawaiter \
              --set MW_STATIC_FOLDER $out/lib/mediawaiter/src/mediawaiter/static
          '';
        };

        # App for `nix run`
        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/${thisProjectAsNixPkg.pname}";
        };
        apps.${thisProjectAsNixPkg.pname} = self.apps.${system}.default;

        packages.mv-image = pkgs.dockerTools.buildImage {
          name = "kyokley/mediawaiter";
          tag = "latest";
          copyToRoot = pkgs.buildEnv {
            name = "image-root";
            paths = [ self.packages.${system}.default ];
            pathsToLink = ["/bin" "/lib"];
          };
          config = {
            Cmd = ["/bin/${thisProjectAsNixPkg.pname}"];
          };
        };

        packages.dev-image = pkgs.dockerTools.buildImage {
          name = "kyokley/mediawaiter";
          tag = "latest";
          copyToRoot = pkgs.buildEnv {
            name = "image-root";
            paths = [ self.packages.${system}.dev ];
            pathsToLink = ["/bin" "/lib"];
          };
          config = {
            Cmd = ["/bin/${thisProjectAsNixPkg.pname}"];
          };
        };
      }
    );
}
