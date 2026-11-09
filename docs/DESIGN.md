# HSTN artwork design

This guide defines the approved visual family for controller-accessible session-switching shortcuts. Use the existing images in `assets/artwork/` as visual references when adding a launcher. The destination should be recognizable from the symbol, accent color, and label at couch distance.

## Shared visual language

Every destination has an upright rectangular doorway viewed at a slight angle, with its top edge rising toward the right. A thick luminous frame surrounds a dark opening. Soft light spills onto the floor, grounding the doorway without creating a detailed scene.

Use a deep midnight navy background with restrained atmospheric blue gradients and fine grain. Keep it quiet behind the symbol and lettering. The doorway supplies the destination's accent color; reuse that color for soft edge highlights and floor light.

Destination symbols are simple shaded-white pictograms. Use ivory/off-white fills, gentle gradients, and restrained colored highlights from the doorway. Keep shapes bold enough to read as thumbnails. Negative-space details reveal the background. Avoid realistic objects, glossy cartoon characters, ornate details, metal bevels, layered components, and thin internal strokes.

The doorway can occlude part of a moving symbol to suggest passing through it. Objects must still read clearly. Keep the full symbol inside the artwork's safe margins.

## Destination identities

| Destination | Doorway accent | Approved symbol | Distinctive details |
| --- | --- | --- | --- |
| Heroic | Warm gold/yellow | Simple white geometric sword passing through doorway | Hilt left, blade right, slight upward diagonal; thick cartoon blade; plain angular handle and crossguard; no overlapping sword parts, bevels, wrapped grip, or separate ornate pommel |
| Steam | Cool cyan/blue | White human pictogram floating through doorway | Round featureless head, arms forward to right, relaxed bent legs trailing left; only Steam uses this figure |
| Desktop | Bazzite-inspired violet/purple | White seated Tux-like penguin inside doorway | Broad seated body, splayed feet, simple flippers; oval eye cutouts, small rounded triangular beak cutout, curved negative-space limb separations |

Suggested starting colors, not sampled or official brand specifications: navy `#06152E`, ivory `#FFF5E2`, Heroic gold `#FFD15A`, Steam cyan `#12D8F2`, Desktop violet `#8B5CF6`. Match the approved images over exact swatches; gradients and lighting are part of the appearance.

For a future destination, choose a distinct accent and one simple destination-specific symbol. Reuse the doorway, background, typography, and shading. Do not automatically reuse the floating person, sword, or penguin for another launcher.

## Typography

Use two lines: smaller, widely spaced uppercase `SWITCH TO`, followed by a much larger bold uppercase destination name. Use a clean generic sans serif, not a platform's proprietary wordmark. Match the existing covers' weight, spacing, and ivory color.

Reduce the destination font size for longer names rather than clipping letters, crowding edges, or changing the layout. Keep roughly 6–8% outer safety margins for text; allow more where the library may crop. No subtitles, badges, watermarks, or extra explanatory text.

## Variants and composition

| Variant | Shape / export | Layout |
| --- | --- | --- |
| Portrait cover | 2:3; current exports 1024 × 1536 | Doorway and symbol occupy upper two-thirds; two-line title below |
| Wide cover | Approximately 920:430; current exports 1833 × 858 | Doorway and symbol on left; two-line title on right |
| Square icon | 1:1; current exports 1254 × 1254 | Doorway and destination symbol only; no text; roughly 10% padding and no clipped frame, limbs, hilt, or tip |
| Steam details background | Exactly 3840 × 1240 | Left approximately 45% stays clear for Steam's overlay; doorway, symbol, and title occupy right side |
| Plain background | Portrait and wide as needed | Navy texture and gradients only; no doorway, symbol, text, or accent-colored object |

Recompose each variant rather than stretching a portrait into a wide cover. Preserve the approved symbol's geometry and pose across variants. Verify actual exported dimensions: image generation may not honor requested pixel sizes. For an exact-size export, preserve proportions through appropriate resampling/canvas adjustment and inspect for cropping or distortion.

Export PNG in RGB for opaque covers. The current icons also have opaque navy backgrounds. Penguin cutouts show the scene behind the symbol; they do not require transparency across the entire cover. A standalone transparent symbol would be a separate requested asset.

## Approved source files

All paths below are relative to `assets/artwork/`.

| Destination | Portrait | Wide | Square icon | Details background |
| --- | --- | --- | --- | --- |
| Heroic | `switch-to-heroic-portrait.png` | `switch-to-heroic-wide.png` | `switch-to-heroic-icon.png` | `switch-to-heroic-details-background.png` |
| Steam | `switch-to-steam-portrait.png` | `switch-to-steam-wide.png` | `switch-to-steam-icon.png` | Not created |
| Desktop | `switch-to-desktop-portrait.png` | `switch-to-desktop-wide.png` | `switch-to-desktop-icon.png` | Not created |

Heroic's approved covers now use the sword. Earlier arrow covers and rejected sword drafts have been superseded. The filenames above are the current approved sources; use the manifest for launcher slot assignments.

`heroic-official-icon.png` is a separate downloaded upstream asset, not the custom gold doorway icon. The current `scripts/configure-launchers.py --launcher steam` deliberately uses this official icon for Steam's sidebar icon and details-page logo overlay, with Steam's default logo placement. Creating a custom doorway icon does not implicitly change that setting.

## Library integration

The root `manifest.json` is the source of truth for destination image filenames and launcher slot assignments. `destinations` defines available images; `launchers.<library>.entries.<target>.slots` maps launcher slots to those image keys. Images listed without a slot assignment remain available assets and are not installed automatically. Paths in `destinations.*.images` are relative to `assets_dir`, which is relative to the manifest.

`scripts/configure-launchers.py --launcher steam` applies the Heroic portrait, wide cover, and details background from the standard filenames. Steam grid artwork uses the shortcut's detected app ID: `<id>p.png` for portrait, `<id>.png` for wide, `<id>_hero.png` for details background, `<id>_icon.png` for icon, and `<id>_logo.png` for the separate logo overlay. The script removes the custom `logoPosition` setting to use Steam's default placement.

`scripts/configure-launchers.py --launcher heroic` applies both Steam and Desktop artwork. For these shortcuts, **`art_square` points to the approved portrait**, while **`art_cover` points to the wide cover**. The text-free square icons are available as assets; do not substitute them for Heroic's portrait field without an explicit request.

Close the relevant launcher before changing its library configuration. Preserve launch commands, arguments, game IDs, other library entries, and unrelated settings. Back up changed files. The script creates missing selected shortcuts with the verified host launch settings and preserves existing launch settings and IDs. Host switcher wrappers must already be installed and executable.

Generating or replacing project assets does not automatically apply them to a running launcher. Use the appropriate configuration script after closing the launcher, then inspect the actual library display.

## Adding a destination

1. Choose its display name, accent color, and simple pictogram. Check that it is visually distinct from existing destinations.
2. Generate a portrait using an approved cover as the style reference. Supply any destination-symbol reference separately and state what to borrow from it.
3. Review the portrait before producing variants. Confirm spelling, symbol shape, color, thumbnail readability, and consistency with the family.
4. Derive wide, square, and any needed details-page variants from that approved portrait. Preserve symbol design rather than redesigning it for each layout.
5. Save under `assets/artwork/switch-to-<target>-<variant>.png`. Use versioned filenames during iteration and remove rejected versions only when requested. Update consuming scripts if filenames change.
6. Inspect dimensions and safe areas, then apply through the launcher configuration script with backups. Check portrait, wide, and details views individually.

Use original destination-inspired pictograms by default. Upstream logos are separate assets with their own usage terms; an AI-generated approximation is not official artwork or evidence of permission. Describe the destination in plain text without suggesting endorsement.

## Reusable generation brief

```text
Create a [VARIANT] for a session-switcher destination named [NAME].
Style reference: [APPROVED FAMILY IMAGE].
Symbol reference: [OPTIONAL REFERENCE; specify shape cues only].

Deep midnight navy atmospheric background, subtle blue gradients and fine grain.
Upright rectangular doorway in slight perspective, thick luminous [ACCENT] frame,
soft colored floor light. One simple off-white [SYMBOL] [POSE / PLACEMENT].
Bold clean geometric shapes, gentle ivory shading, restrained [ACCENT] rim light.
Negative-space details reveal the background. No realistic texture, ornate
parts, bevels, glossy character rendering, or overlapping symbol components.

Composition: [LAYOUT FROM VARIANTS TABLE].
Exact text for covers: "SWITCH TO" above "[UPPERCASE DESTINATION]".
Square icons: no text. Details banners: left 45% clear for Steam's overlay.
Generic bold sans serif, ivory lettering, generous margins, thumbnail legibility.
No additional logos, words, borders, badges, or watermark.
Export [DIMENSIONS / ASPECT RATIO].
Preserve the approved symbol geometry and palette across all variants.
```

For a targeted revision, say what changes and explicitly preserve everything else. For example: “Widen only the blade slightly; keep the hilt left, blade right, simple geometry, gold doorway, navy background, and typography unchanged.”

## Review checklist

- Destination name is correct and fully inside safe margins.
- Doorway, accent, and white pictogram match the family.
- Symbol is recognizable at library thumbnail size; icon still reads at 32–64 pixels.
- Lighting adds depth without decorative or realistic detail.
- All variants preserve the same symbol and pose.
- Square icon contains no text; details banner leaves the overlay area clear.
- Export dimensions are checked, including the exact 3840 × 1240 details banner.
- Library integration preserves working launch settings and uses portrait art in Heroic's `art_square` field.

## Overlay UI

The native overlay follows the approved [Launch Deck handoff](ui-redesign/brief.md).
See [implementation and validation](ui-redesign/README.md) for screenshots and acceptance status.
