"""Internal HSTN action and presentation profiles, independent of output emulation."""
ACTIONS = {name: name for name in (
    'ui_quick', 'ui_up', 'ui_down', 'ui_left', 'ui_right',
    'ui_accept', 'ui_back', 'ui_l1', 'ui_r1')}
ACTIVATION = ('Gamepad:Button:Guide', 'Gamepad:Button:Select')
PROFILES = {
    'playstation': {'glyphs': 'playstation', 'output_policy': 'ds5-single'},
    'xbox': {'glyphs': 'xbox', 'output_policy': 'xbox-series'},
    'legion-go-s': {'glyphs': 'handheld', 'output_policy': 'preserve'},
}
for profile in PROFILES.values():
    profile.update(actions=dict(ACTIONS), activation=ACTIVATION)
PROFILES['legion-go-s']['activation'] = ('Gamepad:Button:Guide', 'Gamepad:Button:QuickAccess')
# Wait for Accept/Back release before returning to normal forwarding. InputPlumber
# 0.83 otherwise keeps its DBus target pressed after the release goes elsewhere.
PROFILES['legion-go-s']['release_actions'] = {'ui_accept', 'ui_back'}
PROFILES['legion-go-s']['desktop_split'] = True
PROMPTS = {
    'playstation': (('l1', 'r1', 'cross', 'circle'), ('L1 or R1', 'Cross', 'Circle')),
    'xbox': (('xbox-lb', 'xbox-rb', 'xbox-a', 'xbox-b'), ('LB or RB', 'A', 'B')),
    'handheld': (('handheld-l1', 'handheld-r1', 'handheld-a', 'handheld-b'), ('L1 or R1', 'A', 'B')),
    'keyboard': (('keyboard-page-up', 'keyboard-page-down', 'keyboard-enter', 'keyboard-escape'),
                 ('Page Up or Page Down', 'Enter', 'Escape')),
}


def action(event, profile='playstation'):
    profile = next((name for name, value in PROFILES.items() if value['glyphs'] == profile), profile)
    return PROFILES[profile]['actions'].get(event)


def release_actions(profile):
    profile = next((name for name, value in PROFILES.items() if value['glyphs'] == profile), profile)
    return PROFILES[profile].get('release_actions', set())
