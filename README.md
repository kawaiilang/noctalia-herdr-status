# noctalia-herdr-status

English | [日本語](README-jp.md)

A read-only [Noctalia](https://github.com/noctalia-dev/noctalia) bar widget, panel, and Python helper that surfaces active [Herdr](https://herdr.dev) TUI agent/shell pane status and jumps directly to the selected pane and its hosting terminal window.

## Features

- **Privacy-preserving snapshot**: Reads Herdr's UNIX socket (`session.snapshot`) and exposes only pane IDs, display names, agent states (`blocked`, `working`, `done`, `idle`, `unknown`, `shell`), workspace/tab labels, and directory basenames—never full paths, terminal titles, or prompt contents.
- **Click-to-focus**: Clicking an entry in the panel focuses the Herdr pane (`pane.focus`) and raises its hosting terminal window.
- **Compositor support**: Window lookup and focus currently target the [Umbriel](https://github.com/noctalia-dev/umbriel) Wayland compositor via a dedicated backend (`src/noctalia_herdr_status/compositor.py`) so additional compositors can be added cleanly later.
- **Localization**: English and Japanese UI strings (`plugin/translations/`).

## Installation (Nix / Home Manager)

Add this repository as a flake input:

```nix
{
  inputs = {
    noctalia-herdr-status = {
      url = "github:kawaiilang/noctalia-herdr-status";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
}
```

Import the Home Manager module and place the widget explicitly in your Noctalia bar configuration:

```nix
{ inputs, osConfig, ... }:
{
  imports = [ inputs.noctalia-herdr-status.homeModules.default ];

  programs.noctaliaHerdrStatus = {
    enable = true;
    umbrielPackage = osConfig.programs.umbriel.package;
  };
}
```

Then include `"herdr-status"` in your Noctalia bar widget list (the module intentionally leaves bar ordering under host/user control).

The plugin ID is `kawaiilang/herdr-status` and the widget type is `kawaiilang/herdr-status:bar`.

## Environment Variables

- `HERDR_SOCKET_PATH`: Explicit path to the Herdr API socket.
- `HERDR_SESSION`: Named Herdr session (`$XDG_CONFIG_HOME/herdr/sessions/<name>/herdr.sock`).
- `HERDR_WINDOW_APP_ID`: Optional compositor `app_id` filter when disambiguating multiple terminal windows.

## Development & Testing

From the repository root, enter the development shell to use Python, Luau
and the linters. For example, compile a plugin file after editing it:

```bash
nix develop
luau-compile --null plugin/service.luau
```

With the direnv hook enabled, run `direnv allow` once in the repository root
to load the same shell automatically whenever you enter this checkout.

Format the Nix files and run the Python and Luau tests, Ruff, Pyright
and Nix static checks:

```bash
nix fmt
nix flake check
```

To run just the Luau checks, build the plugin. The build compiles `service`, `widget` and `panel`, then runs their tests against a mock Noctalia API.

```bash
nix build --no-link --print-build-logs .#plugin
```

Or run the Python test suite directly:

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests -v
```

## License

MIT ([LICENSE](LICENSE))
