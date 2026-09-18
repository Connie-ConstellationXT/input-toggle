{
  description = "Input Toggle: temporary Linux input-device control and remapping";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          lib = pkgs.lib;
          python = pkgs.python3.withPackages (ps: [ ps.evdev ]);
          source = lib.cleanSourceWith {
            src = ./.;
            filter = path: type:
              let name = baseNameOf path;
              in name != ".git" && name != "__pycache__" && !lib.hasSuffix ".pyc" name;
          };
          package = pkgs.stdenvNoCC.mkDerivation {
            pname = "input-toggle";
            version = "0.1.0";
            src = source;
            nativeBuildInputs = [ pkgs.makeWrapper ];

            installPhase = ''
              runHook preInstall
              mkdir -p "$out/lib/input-toggle"
              cp -r . "$out/lib/input-toggle"
              makeWrapper ${python}/bin/python "$out/bin/input-toggle" \
                --prefix PYTHONPATH : "$out/lib/input-toggle" \
                --prefix PATH : ${lib.makeBinPath [ pkgs.systemd pkgs.kmod ]} \
                --add-flags "$out/lib/input-toggle/input-toggle.py"
              runHook postInstall
            '';

            meta = {
              description = "Terminal UI for temporary Linux input-device control and remapping";
              platforms = lib.platforms.linux;
              mainProgram = "input-toggle";
            };
          };
        in {
          default = package;
          input-toggle = package;
        });

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.programs.input-toggle;
        in {
          options.programs.input-toggle = {
            enable = lib.mkEnableOption "the Input Toggle terminal application";
            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
              description = "The Input Toggle package to install.";
            };
            enableUinput = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Load the uinput kernel module at boot for virtual controller remappers.";
            };
          };

          config = lib.mkIf cfg.enable {
            environment.systemPackages = [ cfg.package ];
            boot.kernelModules = lib.mkIf cfg.enableUinput [ "uinput" ];
          };
        };
    };
}
