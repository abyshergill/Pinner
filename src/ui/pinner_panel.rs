//! The 'Always on Top' tab: pin other applications' windows (Windows only).

use eframe::egui;

use pinner::window_pinner::{Hwnd, WindowInfo, WindowPinner};

pub struct PinnerPanel {
    windows: Vec<WindowInfo>,
    chosen: Option<Hwnd>,
    priority: usize,
    loaded: bool,
    error: Option<String>,
}

impl PinnerPanel {
    pub fn new() -> Self {
        Self { windows: Vec::new(), chosen: None, priority: 1, loaded: false, error: None }
    }

    /// Call when the tab becomes visible so the window list is fresh.
    pub fn invalidate(&mut self) {
        self.loaded = false;
    }

    fn load(&mut self, pinner: &mut WindowPinner) {
        self.windows = pinner.list_windows("");
        let open: Vec<Hwnd> = self.windows.iter().map(|w| w.hwnd).collect();
        pinner.prune(&open);
        if !self.windows.iter().any(|w| Some(w.hwnd) == self.chosen) {
            self.chosen = self.windows.first().map(|w| w.hwnd);
        }
        self.loaded = true;
    }

    /// Returns `Some(new value)` when "Active after the application stop" was toggled.
    pub fn ui(&mut self, ui: &mut egui::Ui, pinner: &mut WindowPinner) -> Option<bool> {
        if !pinner.available() {
            ui.add_space(12.0);
            ui.heading("Always on Top is not available here");
            ui.label(pinner.reason());
            ui.weak("Everything else in Pinner works as usual.");
            return None;
        }
        if !self.loaded {
            self.load(pinner);
        }

        ui.weak("Pick a window, choose its priority (1 stays above all other pinned windows) and click “Pin on Top”.");
        ui.add_space(6.0);

        ui.horizontal(|ui| {
            ui.label("Window");
            let current = self
                .windows
                .iter()
                .find(|w| Some(w.hwnd) == self.chosen)
                .map_or("(no windows)".to_string(), |w| w.title.clone());
            egui::ComboBox::from_id_salt("window").width(380.0).selected_text(truncate(&current, 60)).show_ui(ui, |ui| {
                for w in &self.windows {
                    ui.selectable_value(&mut self.chosen, Some(w.hwnd), truncate(&w.title, 80));
                }
            });
            if ui.button("⟳ Refresh").clicked() {
                self.load(pinner);
            }
        });
        ui.horizontal(|ui| {
            ui.label("Priority");
            let max = pinner.pinned().len() + 1;
            self.priority = self.priority.clamp(1, max);
            egui::ComboBox::from_id_salt("priority").selected_text(self.priority.to_string()).show_ui(ui, |ui| {
                for p in 1..=max {
                    ui.selectable_value(&mut self.priority, p, p.to_string());
                }
            });
            if ui.add_enabled(self.chosen.is_some(), egui::Button::new("📌 Pin on Top")).clicked() {
                if let Some(w) = self.windows.iter().find(|w| Some(w.hwnd) == self.chosen).cloned() {
                    self.error = pinner.pin(w.hwnd, &w.title, self.priority, w.is_topmost).err().map(|e| e.to_string());
                }
            }
        });
        if let Some(e) = &self.error {
            ui.colored_label(egui::Color32::LIGHT_RED, e);
        }

        ui.separator();
        ui.strong("Pinned windows (highest priority first)");
        let pinned: Vec<_> = pinner.pinned().to_vec();
        if pinned.is_empty() {
            ui.weak("Nothing pinned yet.");
        }
        let mut action: Option<(Hwnd, i32)> = None; // -1 up, 1 down, 0 unpin
        for (i, p) in pinned.iter().enumerate() {
            ui.horizontal(|ui| {
                ui.label(format!("{}.", i + 1));
                ui.label(truncate(&p.title, 70));
                if ui.add_enabled(i > 0, egui::Button::new("▲")).clicked() {
                    action = Some((p.hwnd, -1));
                }
                if ui.add_enabled(i + 1 < pinned.len(), egui::Button::new("▼")).clicked() {
                    action = Some((p.hwnd, 1));
                }
                if ui.button("Unpin").clicked() {
                    action = Some((p.hwnd, 0));
                }
            });
        }
        if let Some((hwnd, dir)) = action {
            let current = pinner.priority_of(hwnd).unwrap_or(1) as i32;
            let res = match dir {
                0 => pinner.unpin(hwnd),
                d => pinner.move_to(hwnd, (current + d).max(1) as usize),
            };
            self.error = res.err().map(|e| e.to_string());
        }
        if !pinned.is_empty() && ui.button("Unpin all").clicked() {
            self.error = pinner.unpin_all().err().map(|e| e.to_string());
        }

        ui.separator();
        let mut keep = pinner.keep_pinned_on_exit;
        let mut changed = None;
        if ui
            .checkbox(&mut keep, "Active after the application stop")
            .on_hover_text("Leave pinned windows on top after Pinner closes")
            .changed()
        {
            pinner.keep_pinned_on_exit = keep;
            changed = Some(keep);
        }
        changed
    }
}

impl Default for PinnerPanel {
    fn default() -> Self {
        Self::new()
    }
}

fn truncate(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let head: String = text.chars().take(max.saturating_sub(1)).collect();
    format!("{head}…")
}
