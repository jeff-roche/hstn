# Controller and keyboard prompts

The button and keyboard prompts used by the overlay are from Kenney's **Input Prompts**
(1.3), created and distributed by Kenney (https://kenney.nl), under CC0.
The original package license is preserved in LICENSE.

Official pack: https://kenney.nl/assets/input-prompts

Source files were obtained from this pinned mirror of the Kenney pack:
https://github.com/Maaack/Kenney-Input-Prompts/tree/dd37497091c176e91ce81a14e203729ea12d8e4b

| Local file | Original file under `PlayStation Series/Vector/` |
| --- | --- |
| cross.svg | playstation_button_cross.svg |
| circle.svg | playstation_button_circle.svg |
| l1.svg | playstation_trigger_l1.svg |
| r1.svg | playstation_trigger_r1.svg |

The SVG fill is changed from white to HSTN ivory. A 64 × 64 viewBox and
256 px intrinsic dimensions preserve the original geometry and padding while
allowing smooth scaling in Qt rich text. No symbol paths were changed.

The footer follows the last device used for navigation: PlayStation, Xbox, or
keyboard. Physical controller identity determines the family even when the
controller is emulated as another output type. Button release, duplicate held
input, unrelated controller events, and mouse movement do not change the family.
Before navigation, the footer defaults to keyboard prompts.

Additional assets use the same pinned Kenney pack, ivory fill, and 64 × 64 viewBox:

| Local file | Original file |
| --- | --- |
| xbox-a.svg | Xbox Series/Vector/xbox_button_a.svg |
| xbox-b.svg | Xbox Series/Vector/xbox_button_b.svg |
| xbox-lb.svg | Xbox Series/Vector/xbox_lb.svg |
| xbox-rb.svg | Xbox Series/Vector/xbox_rb.svg |
| keyboard-enter.svg | Keyboard & Mouse/Vector/keyboard_enter.svg |
| keyboard-escape.svg | Keyboard & Mouse/Vector/keyboard_escape.svg |
| keyboard-page-up.svg | Keyboard & Mouse/Vector/keyboard_page_up.svg |
| keyboard-page-down.svg | Keyboard & Mouse/Vector/keyboard_page_down.svg |

`usb.svg` and `bluetooth.svg` are HSTN-authored vectors of the conventional
transport symbols, drawn in the same ivory color for controller notifications.
These two files are released under CC0, like the prompt assets above.

## Reusable handheld prompts

`handheld-a.svg`, `handheld-b.svg`, `handheld-l1.svg`, and `handheld-r1.svg`
come from `Steam Deck/Vector/steamdeck_button_{a,b,l1,r1}.svg` in the same
pinned Kenney 1.3 mirror and use the existing CC0 license. They retain the
original paths and 64 × 64 geometry, with HSTN ivory (#FFF5E2) fills and 256 px
intrinsic dimensions. The `handheld` presentation family is reusable by later
handheld device profiles; it does not imply Steam Deck hardware support.

Internal input profiles live in `scripts/input-profiles.py`: HSTN actions,
activation chord, glyph family, and output policy are independent fields.
Add physical detection separately in the runtime registry and standalone root
guard, with parity tests. New hardware must opt into a routing policy explicitly.
