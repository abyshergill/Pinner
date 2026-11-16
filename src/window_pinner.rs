//! 'Always on Top' for *other* applications' windows (Windows only).
//!
//! Several windows can be pinned at once. They are kept in a **priority list**:
//! priority 1 is displayed above every other pinned window, priority 2 above
//! priority 3, and so on. (Windows keeps topmost windows in the order they were
//! last made topmost, so the list is re-applied lowest-priority first.)
//!
//! The OS calls live behind a small backend trait so the logic is testable and
//! the app still starts on macOS / Linux (feature disabled there).

use std::fmt;

pub type Hwnd = isize;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowInfo {
    pub hwnd: Hwnd,
    pub title: String,
    pub is_topmost: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedWindow {
    pub hwnd: Hwnd,
    pub title: String,
    /// Already "always on top" before we pinned it.
    pub was_topmost: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowPinError(pub String);

impl fmt::Display for WindowPinError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for WindowPinError {}

pub trait WindowBackend {
    fn available(&self) -> bool;
    fn reason(&self) -> String;
    fn list_windows(&self) -> Vec<WindowInfo>;
    fn set_topmost(&self, hwnd: Hwnd, topmost: bool) -> Result<(), WindowPinError>;
}

/// Used when the platform doesn't support window pinning.
pub struct UnavailableBackend(pub String);

impl WindowBackend for UnavailableBackend {
    fn available(&self) -> bool {
        false
    }
    fn reason(&self) -> String {
        self.0.clone()
    }
    fn list_windows(&self) -> Vec<WindowInfo> {
        Vec::new()
    }
    fn set_topmost(&self, _: Hwnd, _: bool) -> Result<(), WindowPinError> {
        Err(WindowPinError(self.0.clone()))
    }
}

#[cfg(windows)]
pub struct Win32Backend;

#[cfg(windows)]
impl WindowBackend for Win32Backend {
    fn available(&self) -> bool {
        true
    }
    fn reason(&self) -> String {
        String::new()
    }

    fn list_windows(&self) -> Vec<WindowInfo> {
        use windows_sys::Win32::Foundation::{BOOL, HWND, LPARAM};
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            EnumWindows, GetWindowLongW, GetWindowTextW, IsWindowVisible, GWL_EXSTYLE, WS_EX_TOPMOST,
        };

        unsafe extern "system" fn visit(hwnd: HWND, lparam: LPARAM) -> BOOL {
            let found = &mut *(lparam as *mut Vec<WindowInfo>);
            if IsWindowVisible(hwnd) == 0 {
                return 1;
            }
            let mut buf = [0u16; 512];
            let n = GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32);
            if n > 0 {
                let title = String::from_utf16_lossy(&buf[..n as usize]).trim().to_string();
                if !title.is_empty() {
                    let ex = GetWindowLongW(hwnd, GWL_EXSTYLE) as u32;
                    found.push(WindowInfo { hwnd: hwnd as Hwnd, title, is_topmost: ex & WS_EX_TOPMOST != 0 });
                }
            }
            1
        }

        let mut found: Vec<WindowInfo> = Vec::new();
        unsafe {
            EnumWindows(Some(visit), &mut found as *mut _ as LPARAM);
        }
        found
    }

    fn set_topmost(&self, hwnd: Hwnd, topmost: bool) -> Result<(), WindowPinError> {
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            SetWindowPos, HWND_NOTOPMOST, HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE,
        };
        let order = if topmost { HWND_TOPMOST } else { HWND_NOTOPMOST };
        let ok = unsafe { SetWindowPos(hwnd as _, order, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE) };
        if ok == 0 {
            Err(WindowPinError(format!(
                "Failed to modify window state:\n{}",
                std::io::Error::last_os_error()
            )))
        } else {
            Ok(())
        }
    }
}

/// Pick the right backend for this machine.
pub fn create_backend() -> Box<dyn WindowBackend> {
    #[cfg(windows)]
    {
        Box::new(Win32Backend)
    }
    #[cfg(not(windows))]
    {
        Box::new(UnavailableBackend("Pinning other windows is only supported on Windows.".into()))
    }
}

/// Window listing plus the ordered (priority) list of pinned windows.
pub struct WindowPinner {
    backend: Box<dyn WindowBackend>,
    own_titles: Vec<String>,
    pinned: Vec<PinnedWindow>,
    /// Off by default: pinned windows are released when the application stops.
    pub keep_pinned_on_exit: bool,
}

impl WindowPinner {
    pub fn new(own_titles: &[&str]) -> Self {
        Self::with_backend(create_backend(), own_titles)
    }

    pub fn with_backend(backend: Box<dyn WindowBackend>, own_titles: &[&str]) -> Self {
        Self {
            backend,
            own_titles: own_titles.iter().map(|t| t.to_lowercase()).collect(),
            pinned: Vec::new(),
            keep_pinned_on_exit: false,
        }
    }

    pub fn available(&self) -> bool {
        self.backend.available()
    }

    pub fn reason(&self) -> String {
        self.backend.reason()
    }

    /// Pinned windows, highest priority first.
    pub fn pinned(&self) -> &[PinnedWindow] {
        &self.pinned
    }

    pub fn priority_of(&self, hwnd: Hwnd) -> Option<usize> {
        self.pinned.iter().position(|p| p.hwnd == hwnd).map(|i| i + 1)
    }

    /// Visible, titled windows (excluding this app), sorted by title.
    pub fn list_windows(&self, text: &str) -> Vec<WindowInfo> {
        let needle = text.trim().to_lowercase();
        let mut windows: Vec<_> = self
            .backend
            .list_windows()
            .into_iter()
            .filter(|w| {
                let t = w.title.to_lowercase();
                !self.own_titles.contains(&t) && t.contains(&needle)
            })
            .collect();
        windows.sort_by_key(|w| (w.title.to_lowercase(), w.hwnd));
        windows
    }

    /// Forget pinned windows that no longer exist; true if the list changed.
    pub fn prune(&mut self, open: &[Hwnd]) -> bool {
        let before = self.pinned.len();
        self.pinned.retain(|p| open.contains(&p.hwnd));
        self.pinned.len() != before
    }

    /// Pin `hwnd` at `priority` (1 = highest); re-pinning just re-prioritises.
    pub fn pin(&mut self, hwnd: Hwnd, title: &str, priority: usize, was_topmost: bool) -> Result<(), WindowPinError> {
        // keep the *original* state across re-pins
        let was = self.pinned.iter().find(|p| p.hwnd == hwnd).map_or(was_topmost, |p| p.was_topmost);
        self.insert(hwnd, title, priority, was);
        self.apply(Some(hwnd))
    }

    /// Change the priority of an already pinned window.
    pub fn move_to(&mut self, hwnd: Hwnd, priority: usize) -> Result<(), WindowPinError> {
        let Some(cur) = self.pinned.iter().find(|p| p.hwnd == hwnd).cloned() else {
            return Err(WindowPinError("That window is not pinned.".into()));
        };
        self.insert(hwnd, &cur.title, priority, cur.was_topmost);
        self.apply(Some(hwnd))
    }

    pub fn unpin(&mut self, hwnd: Hwnd) -> Result<(), WindowPinError> {
        self.pinned.retain(|p| p.hwnd != hwnd);
        self.backend.set_topmost(hwnd, false)
    }

    pub fn unpin_all(&mut self) -> Result<(), WindowPinError> {
        let mut first_error = None;
        for p in self.pinned.clone() {
            if let Err(e) = self.unpin(p.hwnd) {
                first_error.get_or_insert(e); // window may have been closed meanwhile
            }
        }
        first_error.map_or(Ok(()), Err)
    }

    /// Stop pinning everything - call when the application exits. Never fails.
    ///
    /// Windows that were already "always on top" before we touched them keep
    /// that state; everything we pinned goes back to normal. Returns how many
    /// windows were released.
    pub fn release_all(&mut self) -> usize {
        let pinned = std::mem::take(&mut self.pinned);
        pinned
            .iter()
            .filter(|p| !p.was_topmost)
            .filter(|p| self.backend.set_topmost(p.hwnd, false).is_ok())
            .count()
    }

    /// Called when the application stops. Releases every pinned window - unless
    /// the user ticked "Active after the application stop".
    pub fn release_on_exit(&mut self) -> usize {
        if self.keep_pinned_on_exit { 0 } else { self.release_all() }
    }

    fn insert(&mut self, hwnd: Hwnd, title: &str, priority: usize, was_topmost: bool) {
        self.pinned.retain(|p| p.hwnd != hwnd);
        let index = priority.saturating_sub(1).min(self.pinned.len());
        self.pinned.insert(index, PinnedWindow { hwnd, title: title.to_string(), was_topmost });
    }

    /// Re-assert topmost, lowest priority first so priority 1 ends up on top.
    fn apply(&mut self, must_succeed: Option<Hwnd>) -> Result<(), WindowPinError> {
        let mut errors: Vec<(Hwnd, WindowPinError)> = Vec::new();
        for p in self.pinned.iter().rev() {
            if let Err(e) = self.backend.set_topmost(p.hwnd, true) {
                errors.push((p.hwnd, e));
            }
        }
        if errors.is_empty() {
            return Ok(());
        }
        // stale windows (closed, access denied) leave the list
        self.pinned.retain(|p| !errors.iter().any(|(h, _)| *h == p.hwnd));
        match must_succeed.and_then(|m| errors.into_iter().find(|(h, _)| *h == m)) {
            Some((_, e)) => Err(e),
            None => Ok(()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::HashSet;
    use std::rc::Rc;

    #[derive(Default)]
    struct State {
        windows: Vec<WindowInfo>,
        calls: Vec<(Hwnd, bool)>,
        broken: HashSet<Hwnd>,
    }

    struct Mock(Rc<RefCell<State>>);

    impl WindowBackend for Mock {
        fn available(&self) -> bool {
            true
        }
        fn reason(&self) -> String {
            String::new()
        }
        fn list_windows(&self) -> Vec<WindowInfo> {
            self.0.borrow().windows.clone()
        }
        fn set_topmost(&self, hwnd: Hwnd, topmost: bool) -> Result<(), WindowPinError> {
            let mut s = self.0.borrow_mut();
            s.calls.push((hwnd, topmost));
            if s.broken.contains(&hwnd) { Err(WindowPinError("gone".into())) } else { Ok(()) }
        }
    }

    fn win(hwnd: Hwnd, title: &str) -> WindowInfo {
        WindowInfo { hwnd, title: title.into(), is_topmost: false }
    }

    fn pinner() -> (WindowPinner, Rc<RefCell<State>>) {
        let st = Rc::new(RefCell::new(State::default()));
        st.borrow_mut().windows = vec![win(3, "zeta"), win(1, "Alpha Editor"), win(2, "Pinner"), win(4, "alpha two")];
        (WindowPinner::with_backend(Box::new(Mock(st.clone())), &["Pinner"]), st)
    }

    fn order(p: &WindowPinner) -> Vec<Hwnd> {
        p.pinned().iter().map(|w| w.hwnd).collect()
    }

    #[test]
    fn lists_sorted_filtered_without_self() {
        let (p, _) = pinner();
        let all: Vec<_> = p.list_windows("").iter().map(|w| w.hwnd).collect();
        assert_eq!(all, [1, 4, 3]);
        assert_eq!(p.list_windows(" ALPHA ").len(), 2);
    }

    #[test]
    fn priorities_and_apply_order() {
        let (mut p, st) = pinner();
        p.pin(1, "a", 1, false).unwrap();
        p.pin(3, "z", 2, false).unwrap();
        p.pin(4, "b", 1, false).unwrap();
        assert_eq!(order(&p), [4, 1, 3]);
        assert_eq!(p.priority_of(3), Some(3));
        // last apply pass goes lowest priority first so priority 1 ends on top
        let calls = st.borrow().calls.clone();
        let last: Vec<_> = calls[calls.len() - 3..].iter().map(|c| c.0).collect();
        assert_eq!(last, [3, 1, 4]);
        p.move_to(3, 1).unwrap();
        assert_eq!(order(&p), [3, 4, 1]);
        assert!(p.move_to(99, 1).is_err());
    }

    #[test]
    fn priority_is_clamped() {
        let (mut p, _) = pinner();
        p.pin(1, "a", 0, false).unwrap();
        p.pin(3, "z", 50, false).unwrap();
        assert_eq!(order(&p), [1, 3]);
    }

    #[test]
    fn repin_keeps_original_topmost_state() {
        let (mut p, st) = pinner();
        p.pin(1, "a", 1, true).unwrap();
        p.pin(1, "a", 1, false).unwrap();
        assert!(p.pinned()[0].was_topmost);
        st.borrow_mut().calls.clear();
        assert_eq!(p.release_all(), 0); // was already on top: left alone
        assert!(st.borrow().calls.is_empty());
    }

    #[test]
    fn failed_pin_errors_and_stale_windows_drop() {
        let (mut p, st) = pinner();
        p.pin(1, "a", 1, false).unwrap();
        st.borrow_mut().broken.insert(1);
        assert!(p.pin(3, "z", 1, false).is_ok()); // 3 fine, stale 1 dropped silently
        assert_eq!(order(&p), [3]);
        st.borrow_mut().broken.insert(3);
        assert!(p.pin(3, "z", 1, false).is_err());
        assert!(p.pinned().is_empty());
    }

    #[test]
    fn unpin_prune_release() {
        let (mut p, st) = pinner();
        p.pin(1, "a", 1, false).unwrap();
        p.pin(3, "z", 2, false).unwrap();
        p.unpin(1).unwrap();
        assert_eq!(order(&p), [3]);
        assert!(!p.prune(&[3]));
        assert!(p.prune(&[]));
        p.pin(1, "a", 1, false).unwrap();
        p.pin(3, "z", 2, false).unwrap();
        p.keep_pinned_on_exit = true;
        assert_eq!(p.release_on_exit(), 0);
        assert_eq!(p.pinned().len(), 2);
        p.keep_pinned_on_exit = false;
        st.borrow_mut().broken.insert(3);
        assert_eq!(p.release_on_exit(), 1);
        assert!(p.pinned().is_empty());
    }

    #[test]
    fn unpin_all_reports_first_error_but_clears() {
        let (mut p, st) = pinner();
        p.pin(1, "a", 1, false).unwrap();
        p.pin(3, "z", 2, false).unwrap();
        st.borrow_mut().broken.insert(1);
        assert!(p.unpin_all().is_err());
        assert!(p.pinned().is_empty());
    }

    #[test]
    fn unavailable_backend() {
        let p = WindowPinner::with_backend(Box::new(UnavailableBackend("nope".into())), &[]);
        assert!(!p.available());
        assert_eq!(p.reason(), "nope");
        assert!(p.list_windows("").is_empty());
    }
}
