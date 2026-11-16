//! The egui front end: header, tabs and the three tab views.

mod about;
mod icons;
mod pinner_panel;
mod section;
mod theme;

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
    About,
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

        egui::TopBottomPanel::top("header")
            .frame(egui::Frame::none().fill(ctx.style().visuals.panel_fill).inner_margin(egui::Margin::symmetric(18.0, 12.0)))
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.add(icons::image("app", 34.0));
                    ui.heading(APP_NAME);
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.checkbox(&mut self.stay_on_top, format!("Keep {APP_NAME} always on top")).changed() {
                            self.apply_stay_on_top(ctx);
                            let _ = self.repo.set_bool(SETTING_SELF_ON_TOP, self.stay_on_top);
                        }
                    });
                });
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    let before = self.tab;
                    for (tab, icon, label) in [
                        (Tab::Paths, "folder", "Paths"),
                        (Tab::Browser, "url", "Browser Bookmarks"),
                        (Tab::OnTop, "window_pin", "Always on Top"),
                        (Tab::About, "github", "About"),
                    ] {
                        let active = self.tab == tab;
                        let image = if active { icons::image(icon, 16.0).tint(egui::Color32::WHITE) } else { icons::mono(ui, icon, 16.0) };
                        let text = if active {
                            egui::RichText::new(label).strong().color(egui::Color32::WHITE)
                        } else {
                            egui::RichText::new(label)
                        };
                        let mut b = egui::Button::image_and_text(image, text).min_size(egui::vec2(0.0, 32.0));
                        if active {
                            b = b.fill(icons::ACCENT);
                        } else {
                            b = b.frame(false);
                        }
                        if ui.add(b).clicked() {
                            self.tab = tab;
                        }
                    }
                    if before != self.tab && self.tab == Tab::OnTop {
                        self.panel.invalidate();
                    }
                });
            });

        egui::TopBottomPanel::bottom("status").frame(egui::Frame::none().fill(ctx.style().visuals.panel_fill).inner_margin(egui::Margin::symmetric(18.0, 6.0))).show(ctx, |ui| {
            ui.weak(if self.status.0.is_empty() { "Ready" } else { self.status.0.as_str() });
        });

        egui::CentralPanel::default().frame(egui::Frame::none().fill(ctx.style().visuals.panel_fill).inner_margin(egui::Margin::symmetric(18.0, 4.0))).show(ctx, |ui| match self.tab {
            Tab::Paths => self.paths.ui(ui, &self.repo, &self.launcher, &mut self.status),
            Tab::Browser => self.browser.ui(ui, &self.repo, &self.launcher, &mut self.status),
            Tab::About => {
                if let Some(link) = about::ui(ui) {
                    if let Err(e) = self.launcher.open_url(link) {
                        self.status.0 = e.to_string();
                    }
                }
            }
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
    let mut viewport = egui::ViewportBuilder::default()
            .with_title(APP_NAME)
            .with_inner_size([980.0, 680.0])
            .with_min_inner_size([700.0, 480.0])
            .with_drag_and_drop(true);
    if let Some(icon) = icons::app_icon(256) {
        viewport = viewport.with_icon(icon);
    }
    let options = eframe::NativeOptions { viewport, ..Default::default() };
    eframe::run_native(APP_NAME, options, Box::new(|cc| {
        egui_extras::install_image_loaders(&cc.egui_ctx);
        theme::apply(&cc.egui_ctx);
        Ok(Box::new(PinnerApp::new(repo)))
    }))
}
