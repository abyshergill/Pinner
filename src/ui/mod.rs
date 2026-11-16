//! The egui front end: header, tabs and the three tab views.

mod pinner_panel;
mod section;

use eframe::egui;

use pinner::launcher::Launcher;
use pinner::models::Section;
use pinner::repository::Repository;
use pinner::window_pinner::WindowPinner;
use pinner::APP_NAME;

use pinner_panel::PinnerPanel;
use section::{take_copy_request, SectionView, Status};

pub const SETTING_SELF_ON_TOP: &str = "self_always_on_top";
pub const SETTING_KEEP_PINS: &str = "keep_pins_after_exit";

#[derive(PartialEq, Clone, Copy)]
enum Tab {
    Paths,
    Browser,
    OnTop,
}

pub struct PinnerApp {
    repo: Repository,
    launcher: Launcher,
    pinner: WindowPinner,
    tab: Tab,
    paths: SectionView,
    browser: SectionView,
    panel: PinnerPanel,
    stay_on_top: bool,
    status: Status,
    on_top_applied: bool,
}

impl PinnerApp {
    pub fn new(repo: Repository) -> Self {
        let mut pinner = WindowPinner::new(&[APP_NAME]);
        pinner.keep_pinned_on_exit = repo.get_bool(SETTING_KEEP_PINS, false); // default: unchecked
        let stay_on_top = repo.get_bool(SETTING_SELF_ON_TOP, false);
        Self {
            repo,
            launcher: Launcher::new(),
            pinner,
            tab: Tab::Paths,
            paths: SectionView::new(Section::Paths),
            browser: SectionView::new(Section::Browser),
            panel: PinnerPanel::new(),
            stay_on_top,
            status: Status::default(),
            on_top_applied: false,
        }
    }

    fn apply_stay_on_top(&self, ctx: &egui::Context) {
        let level = if self.stay_on_top {
            egui::viewport::WindowLevel::AlwaysOnTop
        } else {
            egui::viewport::WindowLevel::Normal
        };
        ctx.send_viewport_cmd(egui::ViewportCommand::WindowLevel(level));
    }
}

impl eframe::App for PinnerApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if !self.on_top_applied {
            self.on_top_applied = true;
            if self.stay_on_top {
                self.apply_stay_on_top(ctx);
            }
        }

        egui::TopBottomPanel::top("header").show(ctx, |ui| {
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                ui.heading(format!("📁 {APP_NAME}"));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.checkbox(&mut self.stay_on_top, format!("Keep {APP_NAME} always on top")).changed() {
                        self.apply_stay_on_top(ctx);
                        let _ = self.repo.set_bool(SETTING_SELF_ON_TOP, self.stay_on_top);
                    }
                });
            });
            ui.horizontal(|ui| {
                let before = self.tab;
                ui.selectable_value(&mut self.tab, Tab::Paths, "📁 Paths");
                ui.selectable_value(&mut self.tab, Tab::Browser, "🔗 Browser Bookmarks");
                ui.selectable_value(&mut self.tab, Tab::OnTop, "📌 Always on Top");
                if before != self.tab && self.tab == Tab::OnTop {
                    self.panel.invalidate();
                }
            });
            ui.add_space(2.0);
        });

        egui::TopBottomPanel::bottom("status").show(ctx, |ui| {
            ui.weak(if self.status.0.is_empty() { "Ready" } else { self.status.0.as_str() });
        });

        egui::CentralPanel::default().show(ctx, |ui| match self.tab {
            Tab::Paths => self.paths.ui(ui, &self.repo, &self.launcher, &mut self.status),
            Tab::Browser => self.browser.ui(ui, &self.repo, &self.launcher, &mut self.status),
            Tab::OnTop => {
                if let Some(keep) = self.panel.ui(ui, &mut self.pinner) {
                    let _ = self.repo.set_bool(SETTING_KEEP_PINS, keep);
                }
            }
        });

        if let Some(text) = take_copy_request() {
            ctx.copy_text(text);
            self.status.0 = "Copied to clipboard".into();
        }
    }

    /// Pinned windows must not outlive the app unless the user opted in.
    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        self.pinner.release_on_exit();
    }
}

/// Start the desktop application.
pub fn run(repo: Repository) -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(APP_NAME)
            .with_inner_size([980.0, 680.0])
            .with_min_inner_size([700.0, 480.0])
            .with_drag_and_drop(true),
        ..Default::default()
    };
    eframe::run_native(APP_NAME, options, Box::new(|_cc| Ok(Box::new(PinnerApp::new(repo)))))
}
