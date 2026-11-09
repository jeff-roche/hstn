// Loaded only for this HSTN Desktop process. Uses KWin's native Window objects,
// so restoration works for Wayland and XWayland without synthetic key presses.
const hstnPid = __HSTN_PID__;
const hstnTitle = __HSTN_TITLE__;
let lastApplication = workspace.activeWindow;
let previousApplication = null;
let menuVisible = false;
function isMenu(window) {
    return window && window.pid === hstnPid && window.caption === hstnTitle;
}
function isToast(window) {
    return window && window.pid === hstnPid && window.caption === 'HSTN — Controller notification';
}
workspace.windowActivated.connect(function(window) {
    if (!menuVisible && window && !isMenu(window) && !isToast(window)) lastApplication = window;
});
function attachMenu(window) {
    if (isToast(window)) {
        // Native Wayland clients cannot position their own top-level windows.
        function placeToast() {
            const area = workspace.clientArea(KWin.PlacementArea, window);
            const frame = window.frameGeometry;
            window.frameGeometry = {x: area.x + area.width - frame.width - 24,
                                    y: area.y + area.height - frame.height - 24,
                                    width: frame.width, height: frame.height};
            window.opacity = 0.8;
            window.keepAbove = true;
        }
        window.windowShown.connect(placeToast);
        placeToast();
        return;
    }
    if (!isMenu(window)) return;
    function shown() {
        if (!menuVisible) previousApplication = lastApplication;
        menuVisible = true;
        workspace.activeWindow = window;
    }
    function hidden() {
        menuVisible = false;
        const previous = workspace.windowList().find(function(candidate) {
            return candidate === previousApplication && !candidate.deleted;
        });
        if (previous) workspace.activeWindow = previous;
        previousApplication = null;
    }
    window.windowShown.connect(shown);
    window.windowHidden.connect(hidden);
    window.closed.connect(hidden);
    shown();
}
workspace.windowAdded.connect(attachMenu);
workspace.windowList().forEach(attachMenu);
