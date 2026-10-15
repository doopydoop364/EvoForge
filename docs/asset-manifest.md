# Asset manifest protocol 1

Installed Python plugins are trusted operator-installed code. Browser assets are
restricted declarative content. `get_asset_manifest()` is a classmethod returning:

```python
@classmethod
def get_asset_manifest(cls):
    return {"protocol": 1, "assets": {
        "player": {"path": "assets/player.svg", "media_type": "image/svg+xml"}
    }}
```

The formal schema is `evoforge.rendering.schema.Manifest`. Logical ids contain only
ASCII letters, digits, `_` or `-`, up to 80 characters. There are at most 256 assets.
Paths are relative to the package file defining the installed GamePlugin class.
Built-in games use EvoForge's fixed asset directory. Absolute paths, traversal,
backslashes, symlink components and paths outside the package are rejected.
Request URLs contain only declared logical ids and content hashes, never paths.

Allowlisted formats: PNG, WebP, restricted SVG and JSON metadata, at most 2 MiB
per file. Extensions must match MIME types; binary signatures and SVG/XML content
are validated. SVG supports geometric elements only: svg/g/path/rect/circle/
ellipse/polygon/polyline/line/title/desc. Scripts, HTML/foreignObject, images,
external references, CSS, event handlers, declarations/entities and unsupported
attributes are rejected. Files are served with `nosniff` and a sandboxed CSP.
JSON is data, never evaluated. Clients never load JavaScript from a plugin.

`GET /api/v1/games/{game}/manifest` produces authenticated URLs of the form
`/api/v1/games/{game}/assets/{sha256-prefix}/{logical-id}`. The 24-hex content digest
changes with bytes, enabling `private, max-age=31536000, immutable` caching. Old
hashes return 404 if an asset changes; reinstalling the matching plugin restores
compatibility. Refresh the page after a plugin update to reload manifests.

Package assets explicitly in your wheel using setuptools package-data. The Coin
example includes its own SVGs and license. Included EvoForge graphics are original
CC0 geometric illustrations; no commercial game sprites are bundled.
