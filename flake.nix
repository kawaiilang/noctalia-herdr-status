{
  description = "Read-only Herdr TUI session status plugin and helper for Noctalia";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];

      mkHelper =
        {
          pkgs,
          umbrielPackage ? null,
          lsfdPackage ? pkgs.util-linux,
        }:
        let
          inherit (pkgs) lib;
          extraFlags = [
            "--lsfd"
            (lib.getExe' lsfdPackage "lsfd")
          ]
          ++ lib.optionals (umbrielPackage != null) [
            "--umbriel"
            (lib.getExe umbrielPackage)
          ];
        in
        pkgs.python3Packages.buildPythonApplication {
          pname = "noctalia-herdr-status";
          version = "1.0.0";
          pyproject = true;
          src = lib.fileset.toSource {
            root = ./.;
            fileset = lib.fileset.unions [
              ./pyproject.toml
              ./README.md
              ./src
            ];
          };
          build-system = [ pkgs.python3Packages.setuptools ];
          makeWrapperArgs = [
            "--add-flags"
            (lib.escapeShellArgs extraFlags)
          ];
          doCheck = false;
          meta = {
            description = "Query Herdr TUI session status and focus panes for Noctalia";
            license = lib.licenses.mit;
            mainProgram = "noctalia-herdr-status";
            platforms = lib.platforms.linux;
          };
        };

      mkPlugin =
        {
          pkgs,
          helper ? mkHelper { inherit pkgs; },
        }:
        let
          inherit (pkgs) lib;
          pluginSrc = ./plugin;
        in
        pkgs.runCommand "noctalia-herdr-status-plugin" { nativeBuildInputs = [ pkgs.luau ]; } ''
          mkdir -p "$out/translations"
          cp ${pluginSrc}/plugin.toml "$out/plugin.toml"
          cp ${pluginSrc}/service.luau "$out/service.luau"
          cp ${pluginSrc}/widget.luau "$out/widget.luau"
          cp ${pluginSrc}/panel.luau "$out/panel.luau"
          cp ${pluginSrc}/translations/en.json "$out/translations/en.json"
          cp ${pluginSrc}/translations/ja.json "$out/translations/ja.json"
          substituteInPlace "$out/service.luau" --replace-fail '@helperCommand@' '${lib.getExe helper}'
          for entry in service widget panel; do
            luau-compile --null "$out/$entry.luau"
            cat ${pluginSrc}/tests/mocks.luau "$out/$entry.luau" ${pluginSrc}/tests/"$entry-test.luau" > "$entry-test.luau"
            luau "$entry-test.luau"
          done
        '';

      lintTools =
        pkgs:
        let
          python = pkgs.python3;
          lintPackages = [
            python
            pkgs.ruff
            pkgs.pyright
            pkgs.nixfmt
            pkgs.statix
            pkgs.deadnix
          ];
        in
        {
          inherit python lintPackages;
          packages = lintPackages ++ [ pkgs.luau ];
        };
    in
    {
      lib = { inherit mkHelper mkPlugin; };

      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          helper = mkHelper { inherit pkgs; };
          plugin = mkPlugin { inherit pkgs helper; };
        in
        {
          inherit helper plugin;
          default = plugin;
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          tools = lintTools pkgs;
        in
        {
          default = pkgs.mkShellNoCC {
            inherit (tools) packages;
          };
        }
      );

      homeModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.programs.noctaliaHerdrStatus;
        in
        {
          options.programs.noctaliaHerdrStatus = {
            enable = lib.mkEnableOption "Noctalia Herdr status plugin and helper";

            umbrielPackage = lib.mkOption {
              type = lib.types.nullOr lib.types.package;
              default = null;
              description = "Optional Umbriel package whose executable is wired into the helper.";
            };

            lsfdPackage = lib.mkOption {
              type = lib.types.package;
              default = pkgs.util-linux;
              description = "Package providing lsfd for terminal host resolution.";
            };

            helperPackage = lib.mkOption {
              type = lib.types.package;
              default = mkHelper {
                inherit pkgs;
                inherit (cfg) umbrielPackage lsfdPackage;
              };
              description = "Packaged noctalia-herdr-status helper executable.";
            };

            pluginPackage = lib.mkOption {
              type = lib.types.package;
              default = mkPlugin {
                inherit pkgs;
                helper = cfg.helperPackage;
              };
              description = "Packaged Noctalia Luau plugin directory.";
            };

            pluginInstallName = lib.mkOption {
              type = lib.types.str;
              default = "herdr-status";
              description = "Directory name under $XDG_DATA_HOME/noctalia/plugins/.";
            };

            widgetName = lib.mkOption {
              type = lib.types.str;
              default = "herdr-status";
              description = "Widget key under programs.noctalia.settings.widget.";
            };
          };

          config = lib.mkIf cfg.enable {
            home.packages = [ cfg.helperPackage ];
            xdg.dataFile."noctalia/plugins/${cfg.pluginInstallName}".source = cfg.pluginPackage;
            programs.noctalia.settings.plugins.enabled = lib.mkAfter [ "kawaiilang/herdr-status" ];
            programs.noctalia.settings.widget.${cfg.widgetName}.type = "kawaiilang/herdr-status:bar";
          };
        };

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          inherit (pkgs) lib;
          inherit (self.packages.${system}) helper plugin;
          tools = lintTools pkgs;
          lintSrc = lib.fileset.toSource {
            root = ./.;
            fileset = lib.fileset.unions [
              ./flake.nix
              ./pyproject.toml
              ./pyrightconfig.json
              ./src
              ./tests
            ];
          };
        in
        {
          inherit plugin;

          python-tests =
            pkgs.runCommand "noctalia-herdr-status-python-tests"
              {
                nativeBuildInputs = [ tools.python ];
              }
              ''
                export PYTHONDONTWRITEBYTECODE=1
                export HERDR_STATUS_HELPER="${lib.getExe helper}"
                export PYTHONPATH="${./src}:${./tests}"
                python3 -m unittest discover -s ${./tests} -v
                touch "$out"
              '';

          lint = pkgs.runCommand "noctalia-herdr-status-lint" { nativeBuildInputs = tools.lintPackages; } ''
            export HOME="$TMPDIR"
            cd ${lintSrc}
            ruff check --no-cache src tests
            pyright --project pyrightconfig.json --pythonpath ${lib.getExe tools.python}
            nixfmt --check flake.nix
            statix check .
            deadnix --fail flake.nix
            touch "$out"
          '';
        }
      );
    };
}
