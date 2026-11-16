//! Look and feel: rounded corners, roomy spacing, layered surfaces and one accent colour.
//! Light and dark palettes are tuned separately; the user can pick System / Light / Dark.

use eframe::egui::{self, Color32, FontId, Rounding, Shadow, Stroke, TextStyle, ThemePreference};

use super::icons::ACCENT;

pub const SETTING_THEME: &str = "theme";

/// The user's choice, stored in the settings table.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    System,
    Light,
    Dark,
}

impl Mode {
    pub fn parse(s: Option<&str>) -> Mode {
        match s {
            Some("light") => Mode::Light,
            Some("dark") => Mode::Dark,
            _ => Mode::System,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::System => "system",
            Mode::Light => "light",
            Mode::Dark => "dark",
        }
    }
    pub fn next(self) -> Mode {
        match self {
            Mode::System => Mode::Light,
            Mode::Light => Mode::Dark,
            Mode::Dark => Mode::System,
        }
    }
    pub fn icon(self) -> &'static str {
        match self {
            Mode::System => "monitor",
            Mode::Light => "sun",
            Mode::Dark => "moon",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Mode::System => "Theme: follow system",
            Mode::Light => "Theme: light",
            Mode::Dark => "Theme: dark",
        }
    }
    pub fn apply(self, ctx: &egui::Context) {
        ctx.set_theme(match self {
            Mode::System => ThemePreference::System,
            Mode::Light => ThemePreference::Light,
            Mode::Dark => ThemePreference::Dark,
        });
    }
}

/// Raised surface used by the header, status bar and cards.
pub fn surface(visuals: &egui::Visuals) -> Color32 {
    if visuals.dark_mode { Color32::from_rgb(29, 32, 41) } else { Color32::WHITE }
}

pub fn apply(ctx: &egui::Context) {
    ctx.all_styles_mut(|style| {
        style.spacing.item_spacing = egui::vec2(8.0, 7.0);
        style.spacing.button_padding = egui::vec2(12.0, 6.0);
        style.spacing.interact_size.y = 28.0;
        style.spacing.window_margin = egui::Margin::same(18.0);
        style.spacing.indent = 18.0;
        style.spacing.scroll.bar_width = 8.0;
        style.spacing.scroll.floating = true;

        let text = &mut style.text_styles;
        text.insert(TextStyle::Heading, FontId::proportional(22.0));
        text.insert(TextStyle::Body, FontId::proportional(14.5));
        text.insert(TextStyle::Button, FontId::proportional(14.0));
        text.insert(TextStyle::Small, FontId::proportional(12.0));

        let dark = style.visuals.dark_mode;
        let v = &mut style.visuals;

        // palette
        let (bg, card, border, text_col, _weak_text, input, idle, hover, press) = if dark {
            (
                Color32::from_rgb(20, 22, 28),
                Color32::from_rgb(29, 32, 41),
                Color32::from_rgb(45, 49, 62),
                Color32::from_rgb(226, 230, 240),
                Color32::from_rgb(132, 140, 158),
                Color32::from_rgb(15, 17, 22),
                Color32::from_rgb(41, 45, 58),
                Color32::from_rgb(54, 59, 76),
                Color32::from_rgb(66, 72, 93),
            )
        } else {
            (
                Color32::from_rgb(241, 244, 249),
                Color32::WHITE,
                Color32::from_rgb(220, 226, 237),
                Color32::from_rgb(30, 36, 50),
                Color32::from_rgb(110, 119, 138),
                Color32::WHITE,
                Color32::from_rgb(232, 236, 244),
                Color32::from_rgb(219, 226, 240),
                Color32::from_rgb(203, 213, 235),
            )
        };

        v.panel_fill = bg;
        v.window_fill = card;
        v.faint_bg_color = card;
        v.extreme_bg_color = input;
        v.window_stroke = Stroke::new(1.0_f32, border);
        v.window_rounding = Rounding::same(14.0);
        v.menu_rounding = Rounding::same(10.0);
        v.window_shadow = Shadow {
            offset: egui::vec2(0.0, 8.0),
            blur: 28.0,
            spread: 0.0,
            color: Color32::from_black_alpha(if dark { 120 } else { 40 }),
        };
        v.popup_shadow = Shadow {
            offset: egui::vec2(0.0, 4.0),
            blur: 16.0,
            spread: 0.0,
            color: Color32::from_black_alpha(if dark { 110 } else { 35 }),
        };
        v.selection.bg_fill = ACCENT.linear_multiply(0.32);
        v.selection.stroke = Stroke::new(1.0_f32, ACCENT);
        v.hyperlink_color = ACCENT;

        let r = Rounding::same(8.0);
        let w = &mut v.widgets;
        w.noninteractive.bg_fill = card;
        w.noninteractive.bg_stroke = Stroke::new(1.0_f32, border);
        w.noninteractive.fg_stroke = Stroke::new(1.0_f32, text_col);
        w.inactive.bg_fill = idle;
        w.inactive.weak_bg_fill = idle;
        w.inactive.bg_stroke = Stroke::new(1.0_f32, border);
        w.inactive.fg_stroke = Stroke::new(1.0_f32, text_col);
        w.hovered.bg_fill = hover;
        w.hovered.weak_bg_fill = hover;
        w.hovered.bg_stroke = Stroke::new(1.0_f32, ACCENT.linear_multiply(0.8));
        w.hovered.fg_stroke = Stroke::new(1.5_f32, text_col);
        w.active.bg_fill = press;
        w.active.weak_bg_fill = press;
        w.active.bg_stroke = Stroke::new(1.0_f32, ACCENT);
        w.active.fg_stroke = Stroke::new(1.5_f32, text_col);
        w.open.bg_fill = hover;
        w.open.weak_bg_fill = hover;
        for s in [&mut w.noninteractive, &mut w.inactive, &mut w.hovered, &mut w.active, &mut w.open] {
            s.rounding = r;
        }
    });
}
