{
  description = "Law Admin - Django law practice management";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        python = pkgs.python313;

        systemDeps = with pkgs; [
          stdenv.cc.cc.lib
          postgresql_16
          postgresql_16.lib
          libjpeg
          libpng
          freetype
          zlib
          lcms2
          libtiff
          libwebp
          cairo
          pango
          gdk-pixbuf
          fontconfig
          harfbuzz
          gobject-introspection
          glib
          poppler-utils
          tesseract
          ghostscript
          ocrmypdf
          pkg-config
          libffi
          gcc
        ];

        runtimeDeps = with pkgs; [
          postgresql_16
          process-compose
          git
          curl
          jq
          httpie
          pre-commit
          ruff
        ];

        libraryPath = pkgs.lib.makeLibraryPath systemDeps;

        scripts = {
          pc-up = pkgs.writeShellScriptBin "pc-up" ''
            exec ${pkgs.process-compose}/bin/process-compose up "$@"
          '';

          pc-down = pkgs.writeShellScriptBin "pc-down" ''
            exec ${pkgs.process-compose}/bin/process-compose down "$@"
          '';

          db-psql = pkgs.writeShellScriptBin "db-psql" ''
            PGPASSWORD="''${DB_PASSWORD:-lawadminpass}" exec ${pkgs.postgresql_16}/bin/psql \
              -h "''${DB_HOST:-localhost}" \
              -p "''${DB_PORT:-5433}" \
              -U "''${DB_USER:-lawadminuser}" \
              -d "''${DB_NAME:-lawadmin}" \
              "$@"
          '';

          db-reset = pkgs.writeShellScriptBin "db-reset" ''
            set -e
            DB="''${DB_NAME:-lawadmin}"
            DB_USER="''${DB_USER:-lawadminuser}"
            echo "Resetting database $DB..."

            ${pkgs.postgresql_16}/bin/dropdb \
              -h "''${DB_HOST:-localhost}" \
              -p "''${DB_PORT:-5433}" \
              --if-exists "$DB"

            ${pkgs.postgresql_16}/bin/createdb \
              -h "''${DB_HOST:-localhost}" \
              -p "''${DB_PORT:-5433}" \
              -O "$DB_USER" \
              "$DB"

            echo "Database reset complete!"
          '';
        };

        shellHookScript = ''
          # Set library paths for native compilation
          export LD_LIBRARY_PATH="${libraryPath}:$LD_LIBRARY_PATH"
          export LIBRARY_PATH="${libraryPath}:$LIBRARY_PATH"

          # pkg-config paths
          export PKG_CONFIG_PATH="${pkgs.lib.makeSearchPath "lib/pkgconfig" systemDeps}:${pkgs.lib.makeSearchPath "share/pkgconfig" systemDeps}:$PKG_CONFIG_PATH"

          # Include paths for C headers
          export C_INCLUDE_PATH="${pkgs.lib.makeSearchPath "include" systemDeps}:$C_INCLUDE_PATH"
          export CPLUS_INCLUDE_PATH="${pkgs.lib.makeSearchPath "include" systemDeps}:$CPLUS_INCLUDE_PATH"

          # For WeasyPrint/Cairo (GObject Introspection)
          export GI_TYPELIB_PATH="${
            pkgs.lib.makeSearchPath "lib/girepository-1.0" [
              pkgs.pango
              pkgs.gdk-pixbuf
              pkgs.gobject-introspection
            ]
          }:$GI_TYPELIB_PATH"

          # Fontconfig
          export FONTCONFIG_FILE="${pkgs.fontconfig.out}/etc/fonts/fonts.conf"

          # PostgreSQL data directory
          export PGDATA="$PWD/.postgres-data"
          export PGPORT="''${POSTGRES_PORT:-5433}"

          # Virtual environment setup
          VENV_DIR="venv"

          if [ ! -d "$VENV_DIR" ]; then
            echo "Creating Python virtual environment..."
            ${python}/bin/python -m venv "$VENV_DIR"
          fi

          source "$VENV_DIR/bin/activate"

          # Check if requirements need to be installed
          if [ ! -f "$VENV_DIR/.requirements-installed" ] || [ requirements.txt -nt "$VENV_DIR/.requirements-installed" ]; then
            echo "Installing Python dependencies..."
            pip install --upgrade pip setuptools wheel

            # Install all requirements
            pip install -r requirements.txt

            touch "$VENV_DIR/.requirements-installed"
            echo "Dependencies installed!"
          fi

          # Source .env file if it exists (Django reads from config/.env)
          if [ -f "config/.env" ]; then
            set -a
            source config/.env
            set +a
          elif [ -f ".env" ]; then
            set -a
            source .env
            set +a
          fi

          echo ""
          echo "══════════════════════════════════════════════════════════"
          echo "  Law Admin Development Environment"
          echo "══════════════════════════════════════════════════════════"
          echo ""
          echo "  Services:"
          echo "    pc-up             Start all services (PostgreSQL, Django)"
          echo "    pc-down           Stop all services"
          echo ""
          echo "  Database:"
          echo "    db-psql           Connect to database via psql"
          echo "    db-reset          Drop and recreate database"
          echo ""
          echo "  Development:"
          echo "    python manage.py runserver    Start Django dev server"
          echo "    pytest                        Run tests"
          echo "    pre-commit run --all-files    Run code quality checks"
          echo ""
          echo "══════════════════════════════════════════════════════════"
          echo ""
        '';

      in
      {
        devShells.default = pkgs.mkShell {
          name = "lawadmin-dev";

          buildInputs = systemDeps ++ runtimeDeps ++ [ python ] ++ (builtins.attrValues scripts);

          shellHook = shellHookScript;

          NIX_ENFORCE_PURITY = 0;
        };

        apps.services = {
          type = "app";
          program = "${pkgs.writeShellScript "run-services" ''
            cd ${toString ./.}
            ${pkgs.process-compose}/bin/process-compose up
          ''}";
        };
      }
    );
}
