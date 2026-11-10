# Asset provenance and redistribution

This inventory covers runtime assets and documentation images. Third-party
licenses are summarized in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
Review date: November 10, 2026. A documented design or filename alone does not
establish permission to redistribute an image.

| Files | Source and changes | License / verification status |
| --- | --- | --- |
| `controller/{cross,circle,l1,r1}.svg` | Kenney Input Prompts 1.3, PlayStation vectors; ivory fill and normalized dimensions. | CC0-1.0; package notice preserved. |
| `controller/xbox-{a,b,lb,rb}.svg` | Same pinned pack, Xbox Series vectors; same presentation adjustments. | CC0-1.0; package notice preserved. |
| `controller/keyboard-{enter,escape,page-up,page-down}.svg` | Same pinned pack, Keyboard & Mouse vectors; same presentation adjustments. | CC0-1.0; package notice preserved. |
| `controller/handheld-{a,b,l1,r1}.svg` | Same pinned pack, Steam Deck vectors; same presentation adjustments. | CC0-1.0; package notice preserved. |
| `controller/{usb,bluetooth}.svg` | HSTN-authored transport symbols, as recorded in `controller/README.md`. | CC0-1.0 dedication recorded there. |
| `artwork/heroic-official-icon.png` | Exact upstream Heroic `public/icon.png`; no changes. | GPL-3.0-only; blob verified, full license included. |
| `artwork/switch-to-heroic-{portrait,wide,icon,details-background}.png` | GPT-generated gold sword/doorway family described in `docs/DESIGN.md`; committed in `2d8d694`. | MIT for HSTN's rights; GPT origin confirmed by maintainer. |
| `artwork/switch-to-steam-{portrait,wide,icon}.png` | GPT-generated cyan figure/doorway family, same design guide and introduction commit. | MIT for HSTN's rights; GPT origin confirmed by maintainer. |
| `artwork/switch-to-desktop-{portrait,wide,icon}.png` | GPT-generated violet penguin/doorway family, same design guide and introduction commit. | MIT for HSTN's rights; GPT origin confirmed by maintainer. |
| `artwork/navy-background-{portrait,wide}.png` | GPT-generated atmospheric backgrounds in the same artwork family and introduction commit. | MIT for HSTN's rights; GPT origin confirmed by maintainer. |
| `logo/hstn-rocket.svg`, `logo/hstn-rocket-{24,48,256}.png` | GPT-generated rocket design, editable SVG and PNG exports supplied with the approved Launch Deck handoff in `aafa4e3`; see `docs/ui-redesign/brief.md`. | MIT for HSTN's rights; GPT origin confirmed by maintainer. |
| `../docs/ui-redesign/references/{01-launch-deck,02-close-and-switch,03-approved-rocket}.png` | GPT-generated design references supplied in the same handoff. | MIT for HSTN's rights; GPT origin confirmed by maintainer. |
| `../docs/ui-redesign/{launch-deck-tv,launch-deck-handheld,launch-deck-desktop,review-tv,review-handheld}.png` | HSTN native Qt demo/fixture captures; see `docs/ui-redesign/README.md` and `design-qa.md`. | HSTN screenshot contributions; embedded asset terms still apply. |
| `../docs/controller-support/*.png` | HSTN controller-prompt, notification, and handheld fixture captures; see that directory's README and `tests/test_overlay_design.py`. | HSTN screenshot contributions; embedded asset terms still apply. |

## Verified upstream assets

The [controller README](controller/README.md) records every local SVG's original
path in the pinned Kenney mirror. Its package notice identifies Kenney and CC0;
the [official pack page](https://kenney.nl/assets/input-prompts) also declares
CC0. Paths and license evidence refer to 1.3, even if the current official pack
has a later version.

At review, all 16 local prompt SVGs matched the pinned source element geometry
and attributes except for fill and root dimensions/viewBox. The preserved
package license also matched upstream `License.txt` (normalizing line endings).

The Heroic PNG matches upstream's Git blob and SHA-256 as recorded in the root
notices. The upstream package declares GPL-3.0-only and supplies `COPYING`.
`artwork/HEROIC-COPYING` preserves that full license. The root MIT license does
not replace it. The image remains in Steam's existing icon/logo slots.
No separate icon-specific license was found in the pinned upstream tree; the
icon's GPL-3.0-only classification follows the upstream repository declaration.

## GPT-generated project artwork

On November 10, 2026, maintainer Jeff Roche confirmed that all the custom artwork
listed above was generated with GPT. This confirmation covers the doorway
images, navy backgrounds, rocket design, and supplied reference mockups. The
generation source is OpenAI GPT; the exact model/service, generation dates,
prompts, and full input/reference history were not recorded. Introduction
commits and the approved design references remain the available project history;
they are not generation timestamps.

HSTN makes its rights, if any, in these custom assets and their project edits
available under the root [MIT license](../LICENSE). This does not assert
exclusive copyright in generated output or grant third-party trademark rights.
The [OpenAI Terms of Use, Content section](https://openai.com/policies/terms-of-use/#content),
reviewed November 10, 2026, allocates output rights between OpenAI and the user
to the extent permitted by law and notes that outputs may not be unique. That
allocation is separate from whether copyright exists in a particular image.

The previous missing-origin release gate is resolved by the maintainer's
confirmation. The runtime screenshots remain Qt demo/fixture captures of the
application, including its generated artwork and separately licensed prompts.
Kenney's controller assets and the downloaded official Heroic icon retain the
upstream provenance and licenses recorded above. Future supplied references or
replacement assets still require their own source and rights review.

## New or replacement assets

Record the source URL, pinned revision, creator, license, modifications, and
required notices before adding an asset. Keep editable source where available.
For a generated asset, record the service and generation date, supplied
references, and the contributor's right to share the result. Do not include
private account records or prompts containing private information. Update this
inventory, the root notices, and the package allowlist together. Preserve
existing third-party licenses and do not claim trademark permissions.
