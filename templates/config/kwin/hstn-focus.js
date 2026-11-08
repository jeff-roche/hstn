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
workspace.windowActivated.connect(function(window) {
    if (!menuVisible && window && !isMenu(window)) lastApplication = window;
});
function attachMenu(window) {
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
