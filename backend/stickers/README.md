# Sticker Library

Drop sticker files (PNG, GIF, WebP, APNG) directly into the category folders below. They will be picked up automatically by `GET /api/v1/video/stickers/library`.

## Categories

| Folder | Label (UI) | Suggested content |
|--------|------------|-------------------|
| `subscribe/` | Subscribe / CTA | YouTube subscribe button, bell icon, like button |
| `reactions/` | Reactions | heart, fire, thumbs up, clap, wow emoji |
| `decorations/` | Decorations | sparkles, stars, glitter |
| `arrows/` | Arrows | down arrow, pointer hand, swipe-up indicator |
| `mood/` | Mood | scary eyes, romantic rose, sad tear, shocked face |
| `frames/` | Frames | vintage border, neon frame |

## File rules

- Supported extensions: `.png`, `.gif`, `.webp`, `.apng`
- Naming: lowercase, dashes only (e.g. `subscribe-red.png`, `bell-ring.gif`). The basename becomes the sticker `id`.
- For animated stickers, prefer **GIF or WebP** with transparent background. APNG also works.
- Keep individual files under 5 MB.

## Adding a new category

Just create a new subfolder. The label shown in the UI is the folder name with first letter capitalized; rename the folder to whatever label you want.
