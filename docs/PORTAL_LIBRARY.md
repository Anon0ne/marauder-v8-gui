# Rian's portal library

Repository: https://github.com/rianhanft/Rians_Evil_Portals_For_Marauder

The optional library is a Git submodule at `portals/rians`, initially pinned to `75a60f7ba1ccf2d475fc0e82ba22c26795d53bb9`. Its HTML files and MIT license are maintained upstream; preserve the license when redistributing. Existing `portals/default` is retained.

## Fetch the pinned library

For a new source checkout:

```powershell
git clone --recurse-submodules https://github.com/Anon0ne/marauder-v8-gui.git
```

For an existing checkout, run from the source folder:

```powershell
git submodule update --init --recursive -- portals/rians
```

Inspect `git submodule status` to verify the pinned revision. To deliberately update the library, review upstream changes, then use `git submodule update --remote -- portals/rians` and commit the changed gitlink separately. Ordinary initialization does not update the pin.

## Installed app and device files

The standalone EXE folder is not a Git checkout. A copy of the pinned library can be placed at `<install folder>/portals/rians`; use the source checkout for submodule updates. Adding this library does not rebuild the EXE or add an automatic GUI template browser.

Upstream installation instructions require copying selected HTML files to the root of the Marauder storage, not into a subfolder. Keep the upstream license with redistributed copies. No device uploads or RF commands are performed by submodule initialization.

GitHub-generated source ZIPs omit submodule contents. Use a recursive Git clone to fetch the library. Future release packaging should explicitly include the pinned files and license if bundling the library; a flat source-manifest alone does not include Git submodule contents.
