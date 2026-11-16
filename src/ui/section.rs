//! One tab: a single tree of folders, sub-folders and the entries inside them.
//!
//! The same view powers both the *Paths* tab and the *Browser Bookmarks* tab;
//! only the [`Section`] differs.
//!
//! * Folders and sub-folders can be nested to any depth.
//! * **Paths**: entries are folder paths, files/apps and web links. Drop files or
//!   folders from the OS onto the window to add them with their full path.
//! * **Browser Bookmarks**: entries are *web links only*; bookmarks can be
//!   imported from / exported to a browser bookmarks file.

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use eframe::egui::{self, Align, Layout, RichText};

use pinner::launcher::Launcher;
use pinner::models::{allowed_kinds, Group, Item, ItemKind, Section};
use pinner::repository::Repository;
use pinner::{bookmarks, dropped};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Sel {
    Group(i64),
    Item(i64),
}

enum PromptKind {
    NewGroup(Option<i64>),
    Rename(i64),
}

struct ItemForm {
    editing: Option<i64>,
    group_id: i64,
    kind: ItemKind,
    name: String,
    target: String,
    error: Option<String>,
}

enum Modal {
    Prompt { kind: PromptKind, text: String, error: Option<String> },
    Item(ItemForm),
    ConfirmDeleteGroup(i64),
    ConfirmDeleteItem(i64),
    Message(String),
}

enum Act {
    Select(Sel),
    NewGroup(Option<i64>),
    Rename(i64),
    DeleteGroup(i64),
    AddItem(i64, ItemKind),
    EditItem(i64),
    DeleteItem(i64),
    Open(i64),
    Reveal(i64),
    TogglePin(i64),
    Move(i64, i64),
    Copy(String),
    Import(Option<i64>),
    Export(Option<i64>),
}

/// What the app shows in its status bar.
#[derive(Default)]
pub struct Status(pub String);

pub struct SectionView {
    pub section: Section,
    search: String,
    selected: Option<Sel>,
    groups: Vec<Group>,
    items: HashMap<i64, Vec<Item>>,
    dirty: bool,
    modal: Option<Modal>,
}

fn kind_icon(kind: ItemKind) -> &'static str {
    match kind {
        ItemKind::Folder => "📁",
        ItemKind::File => "📄",
        ItemKind::Url => "🔗",
    }
}

fn add_label(kind: ItemKind) -> &'static str {
    match kind {
        ItemKind::Url => "Web link…",
        ItemKind::Folder => "Folder…",
        ItemKind::File => "File / App…",
    }
}

impl SectionView {
    pub fn new(section: Section) -> Self {
        Self {
            section,
            search: String::new(),
            selected: None,
            groups: Vec::new(),
            items: HashMap::new(),
            dirty: true,
            modal: None,
        }
    }

    fn links_only(&self) -> bool {
        self.section == Section::Browser
    }

    fn reload(&mut self, repo: &Repository) {
        self.groups = repo.list_groups(self.section).unwrap_or_default();
        self.items.clear();
        for it in repo.list_section_items(self.section).unwrap_or_default() {
            self.items.entry(it.group_id).or_default().push(it);
        }
        // drop a selection that no longer exists
        self.selected = match self.selected {
            Some(Sel::Group(g)) if !self.groups.iter().any(|x| x.id == g) => None,
            Some(Sel::Item(i)) if self.find_item(i).is_none() => None,
            s => s,
        };
        self.dirty = false;
    }

    fn find_item(&self, id: i64) -> Option<&Item> {
        self.items.values().flatten().find(|i| i.id == id)
    }

    fn group_path(&self, id: i64) -> String {
        let mut parts = Vec::new();
        let mut cur = Some(id);
        while let Some(g) = cur.and_then(|c| self.groups.iter().find(|x| x.id == c)) {
            parts.push(g.name.clone());
            cur = g.parent_id;
            if parts.len() > 64 {
                break;
            }
        }
        parts.reverse();
        parts.join(" / ")
    }

    /// The folder new entries go to: the selected folder, or the folder of the selected entry.
    fn current_group_id(&self) -> Option<i64> {
        match self.selected {
            Some(Sel::Group(g)) => Some(g),
            Some(Sel::Item(i)) => self.find_item(i).map(|it| it.group_id),
            None => None,
        }
    }

    fn children_of(&self, parent: Option<i64>) -> impl Iterator<Item = &Group> {
        self.groups.iter().filter(move |g| g.parent_id == parent)
    }

    /// Folders that have to be shown while searching: those with matches plus their ancestors.
    fn visible_groups(&self, needle: &str) -> Option<HashSet<i64>> {
        if needle.is_empty() {
            return None;
        }
        let mut visible = HashSet::new();
        for (gid, items) in &self.items {
            if items.iter().any(|i| matches(i, needle)) {
                let mut cur = Some(*gid);
                while let Some(g) = cur {
                    if !visible.insert(g) {
                        break;
                    }
                    cur = self.groups.iter().find(|x| x.id == g).and_then(|x| x.parent_id);
                }
            }
        }
        Some(visible)
    }

    // ----------------------------------------------------------------- UI
    pub fn ui(&mut self, ui: &mut egui::Ui, repo: &Repository, launcher: &Launcher, status: &mut Status) {
        if self.dirty {
            self.reload(repo);
        }
        let mut acts: Vec<Act> = Vec::new();
        let modal_open = self.modal.is_some();

        let hint = if self.links_only() {
            "Bookmarks hold web links only - files and folders can't be added here.\n\
             Tip: use Import / Export to share bookmarks with Chrome, Edge, Firefox or Safari."
        } else {
            "Create a folder (e.g. one per customer), add sub-folders, then pin folders, files and links inside.\n\
             Tip: drag files or folders from your file manager onto this window."
        };
        ui.weak(hint);
        ui.add_space(4.0);

        ui.horizontal_wrapped(|ui| {
            ui.add(egui::TextEdit::singleline(&mut self.search).hint_text("🔍 Search name or location").desired_width(240.0));
            if !self.search.is_empty() && ui.button("✖").on_hover_text("Clear search").clicked() {
                self.search.clear();
            }
            ui.separator();
            if ui.button("📁 New folder").clicked() {
                acts.push(Act::NewGroup(None));
            }
            let target_group = self.current_group_id();
            ui.add_enabled_ui(target_group.is_some(), |ui| {
                if self.links_only() {
                    if ui.button("＋ Link").on_hover_text("Add a web link to the selected folder").clicked() {
                        acts.push(Act::AddItem(target_group.unwrap(), ItemKind::Url));
                    }
                } else {
                    ui.menu_button("＋ Add ▾", |ui| {
                        for &kind in allowed_kinds(self.section) {
                            if ui.button(format!("{} {}", kind_icon(kind), add_label(kind))).clicked() {
                                acts.push(Act::AddItem(target_group.unwrap(), kind));
                                ui.close_menu();
                            }
                        }
                    })
                    .response
                    .on_hover_text("Add a link, folder or file to the selected folder");
                }
            });
            let selected_item = matches!(self.selected, Some(Sel::Item(_)));
            if ui.add_enabled(selected_item, egui::Button::new("▶ Open")).clicked() {
                if let Some(Sel::Item(i)) = self.selected {
                    acts.push(Act::Open(i));
                }
            }
            if self.links_only() {
                ui.separator();
                let into = match self.selected {
                    Some(Sel::Group(g)) => Some(g),
                    _ => None,
                };
                if ui.button("⬇ Import…").on_hover_text("Import a browser bookmarks file").clicked() {
                    acts.push(Act::Import(into));
                }
                if ui.button("⬆ Export…").on_hover_text("Export bookmarks as an HTML file").clicked() {
                    acts.push(Act::Export(None));
                }
            }
        });
        ui.separator();

        let needle = self.search.trim().to_lowercase();
        let visible = self.visible_groups(&needle);

        egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
            if self.groups.is_empty() {
                ui.weak("No folders yet - click “New folder”.");
            }
            if visible.as_ref().is_some_and(|v| v.is_empty()) {
                ui.weak("Nothing matches your search.");
            }
            let roots: Vec<Group> = self.children_of(None).cloned().collect();
            for g in &roots {
                self.group_ui(ui, g, &needle, visible.as_ref(), &mut acts);
            }
            // click on empty space clears the selection
            let rest = ui.available_rect_before_wrap();
            if ui.interact(rest, ui.id().with("empty"), egui::Sense::click()).clicked() {
                self.selected = None;
            }
        });

        if !modal_open {
            self.handle_keys(ui.ctx(), &mut acts);
            self.handle_drops(ui.ctx(), repo, status);
        }
        for act in acts {
            self.apply(act, repo, launcher, status);
        }
        self.modal_ui(ui.ctx(), repo, status);
    }

    fn handle_keys(&mut self, ctx: &egui::Context, acts: &mut Vec<Act>) {
        if ctx.wants_keyboard_input() {
            return;
        }
        if ctx.input(|i| i.key_pressed(egui::Key::Enter)) {
            if let Some(Sel::Item(i)) = self.selected {
                acts.push(Act::Open(i));
            }
        }
        if ctx.input(|i| i.key_pressed(egui::Key::Delete)) {
            match self.selected {
                Some(Sel::Item(i)) => acts.push(Act::DeleteItem(i)),
                Some(Sel::Group(g)) => acts.push(Act::DeleteGroup(g)),
                None => {}
            }
        }
    }

    /// Files / folders dropped from the OS onto the window.
    fn handle_drops(&mut self, ctx: &egui::Context, repo: &Repository, status: &mut Status) {
        let files: Vec<PathBuf> = ctx.input(|i| i.raw.dropped_files.iter().filter_map(|f| f.path.clone()).collect());
        if files.is_empty() {
            return;
        }
        let Some(gid) = self.current_group_id().or_else(|| self.groups.first().map(|g| g.id)) else {
            self.modal = Some(Modal::Message("Create a folder first, then drop files onto it.".into()));
            return;
        };
        let sources: Vec<String> = files.iter().map(|p| p.display().to_string()).collect();
        match dropped::add_sources(repo, gid, &sources) {
            Ok(res) => {
                status.0 = format!("{} (in “{}”)", res.summary(), self.group_path(gid));
                if !res.failed.is_empty() {
                    self.modal = Some(Modal::Message(res.failed.join("\n")));
                }
                self.dirty = true;
            }
            Err(e) => self.modal = Some(Modal::Message(e.to_string())),
        }
    }

    fn group_ui(&self, ui: &mut egui::Ui, group: &Group, needle: &str, visible: Option<&HashSet<i64>>, acts: &mut Vec<Act>) {
        if visible.is_some_and(|v| !v.contains(&group.id)) {
            return;
        }
        let selected = self.selected == Some(Sel::Group(group.id));
        let title = RichText::new(format!("📂 {}", group.name)).strong();
        let title = if selected { title.underline() } else { title };
        let mut header = egui::CollapsingHeader::new(title)
            .id_salt(("group", group.id))
            .default_open(true);
        if visible.is_some() {
            header = header.open(Some(true));
        }
        let resp = header.show(ui, |ui| {
            let subs: Vec<Group> = self.children_of(Some(group.id)).cloned().collect();
            for sub in &subs {
                self.group_ui(ui, sub, needle, visible, acts);
            }
            for item in self.items.get(&group.id).into_iter().flatten() {
                if needle.is_empty() || matches(item, needle) {
                    self.item_ui(ui, item, acts);
                }
            }
        });
        let head = resp.header_response;
        if head.clicked() {
            acts.push(Act::Select(Sel::Group(group.id)));
        }
        head.context_menu(|ui| {
            acts.push(Act::Select(Sel::Group(group.id)));
            if ui.button("📁 New sub-folder").clicked() {
                acts.push(Act::NewGroup(Some(group.id)));
                ui.close_menu();
            }
            if self.links_only() {
                if ui.button("🔗 Add link…").clicked() {
                    acts.push(Act::AddItem(group.id, ItemKind::Url));
                    ui.close_menu();
                }
            } else {
                ui.menu_button("＋ Add", |ui| {
                    for &kind in allowed_kinds(self.section) {
                        if ui.button(format!("{} {}", kind_icon(kind), add_label(kind))).clicked() {
                            acts.push(Act::AddItem(group.id, kind));
                            ui.close_menu();
                        }
                    }
                });
            }
            if self.links_only() {
                if ui.button("Import bookmarks here…").clicked() {
                    acts.push(Act::Import(Some(group.id)));
                    ui.close_menu();
                }
                if ui.button("Export this folder…").clicked() {
                    acts.push(Act::Export(Some(group.id)));
                    ui.close_menu();
                }
            }
            ui.separator();
            if ui.button("Rename…").clicked() {
                acts.push(Act::Rename(group.id));
                ui.close_menu();
            }
            if ui.button("Delete folder…").clicked() {
                acts.push(Act::DeleteGroup(group.id));
                ui.close_menu();
            }
        });
    }

    fn item_ui(&self, ui: &mut egui::Ui, item: &Item, acts: &mut Vec<Act>) {
        let selected = self.selected == Some(Sel::Item(item.id));
        ui.horizontal(|ui| {
            let star = if item.is_pinned { "★ " } else { "" };
            let label = format!("{} {star}{}", kind_icon(item.kind), item.name);
            let resp = ui.selectable_label(selected, label).on_hover_text(&item.target);
            ui.weak(shorten(&item.target, 70));
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui.button(RichText::new("Open").color(egui::Color32::from_rgb(40, 160, 80))).clicked() {
                    acts.push(Act::Open(item.id));
                }
            });
            if resp.clicked() {
                acts.push(Act::Select(Sel::Item(item.id)));
            }
            if resp.double_clicked() {
                acts.push(Act::Open(item.id));
            }
            resp.context_menu(|ui| {
                acts.push(Act::Select(Sel::Item(item.id)));
                if ui.button(format!("{} Open", kind_icon(item.kind))).clicked() {
                    acts.push(Act::Open(item.id));
                    ui.close_menu();
                }
                if item.kind != ItemKind::Url && ui.button("Show in folder").clicked() {
                    acts.push(Act::Reveal(item.id));
                    ui.close_menu();
                }
                if ui.button("Edit…").clicked() {
                    acts.push(Act::EditItem(item.id));
                    ui.close_menu();
                }
                let pin = if item.is_pinned { "Unpin from top" } else { "Pin to top of folder" };
                if ui.button(pin).clicked() {
                    acts.push(Act::TogglePin(item.id));
                    ui.close_menu();
                }
                let copy = if self.links_only() { "Copy link" } else { "Copy path / link" };
                if ui.button(copy).clicked() {
                    acts.push(Act::Copy(item.target.clone()));
                    ui.close_menu();
                }
                ui.menu_button("Move to", |ui| {
                    for g in self.groups.iter().filter(|g| g.id != item.group_id) {
                        if ui.button(self.group_path(g.id)).clicked() {
                            acts.push(Act::Move(item.id, g.id));
                            ui.close_menu();
                        }
                    }
                });
                ui.separator();
                if ui.button("Remove…").clicked() {
                    acts.push(Act::DeleteItem(item.id));
                    ui.close_menu();
                }
            });
        });
    }

    // ------------------------------------------------------------ actions
    fn error(&mut self, msg: impl ToString) {
        self.modal = Some(Modal::Message(msg.to_string()));
    }

    fn apply(&mut self, act: Act, repo: &Repository, launcher: &Launcher, status: &mut Status) {
        match act {
            Act::Select(s) => self.selected = Some(s),
            Act::NewGroup(parent) => {
                self.modal = Some(Modal::Prompt { kind: PromptKind::NewGroup(parent), text: String::new(), error: None });
            }
            Act::Rename(id) => {
                if let Some(g) = self.groups.iter().find(|g| g.id == id) {
                    self.modal = Some(Modal::Prompt { kind: PromptKind::Rename(id), text: g.name.clone(), error: None });
                }
            }
            Act::DeleteGroup(id) => self.modal = Some(Modal::ConfirmDeleteGroup(id)),
            Act::DeleteItem(id) => self.modal = Some(Modal::ConfirmDeleteItem(id)),
            Act::AddItem(group_id, kind) => {
                self.modal = Some(Modal::Item(ItemForm {
                    editing: None,
                    group_id,
                    kind,
                    name: String::new(),
                    target: String::new(),
                    error: None,
                }));
            }
            Act::EditItem(id) => {
                if let Some(it) = self.find_item(id) {
                    self.modal = Some(Modal::Item(ItemForm {
                        editing: Some(id),
                        group_id: it.group_id,
                        kind: it.kind,
                        name: it.name.clone(),
                        target: it.target.clone(),
                        error: None,
                    }));
                }
            }
            Act::Open(id) => {
                if let Some(it) = self.find_item(id).cloned() {
                    if let Err(e) = launcher.open_item(&it) {
                        self.error(e);
                    }
                }
            }
            Act::Reveal(id) => {
                if let Some(it) = self.find_item(id).cloned() {
                    if let Err(e) = launcher.reveal(&it.target) {
                        self.error(e);
                    }
                }
            }
            Act::TogglePin(id) => {
                if let Some(pinned) = self.find_item(id).map(|i| i.is_pinned) {
                    match repo.set_pinned(id, !pinned) {
                        Ok(_) => self.dirty = true,
                        Err(e) => self.error(e),
                    }
                }
            }
            Act::Move(id, gid) => match repo.move_item(id, gid) {
                Ok(_) => {
                    status.0 = format!("Moved to “{}”", self.group_path(gid));
                    self.dirty = true;
                }
                Err(e) => self.error(e),
            },
            Act::Copy(text) => {
                // set through the egui context in `ui`; see `copy_pending`
                COPY_PENDING.with(|c| *c.borrow_mut() = Some(text));
            }
            Act::Import(into) => self.import(repo, into, status),
            Act::Export(group) => self.export(repo, group, status),
        }
    }

    fn import(&mut self, repo: &Repository, into: Option<i64>, status: &mut Status) {
        let Some(path) = rfd::FileDialog::new()
            .set_title("Import bookmarks")
            .add_filter("Bookmark files", &["html", "htm", "json"])
            .add_filter("All files", &["*"])
            .pick_file()
        else {
            return;
        };
        let result = bookmarks::read_bookmark_file(&path).and_then(|tree| bookmarks::import_bookmarks(repo, &tree, into));
        match result {
            Ok(res) => {
                status.0 = format!("Imported: {}", res.summary());
                self.dirty = true;
            }
            Err(e) => self.error(e),
        }
    }

    fn export(&mut self, repo: &Repository, group: Option<i64>, status: &mut Status) {
        let Some(path) = rfd::FileDialog::new()
            .set_title("Export bookmarks")
            .set_file_name("pinner-bookmarks.html")
            .add_filter("Bookmarks HTML", &["html"])
            .save_file()
        else {
            return;
        };
        match bookmarks::export_to_file(repo, &path, group) {
            Ok(res) => status.0 = format!("{} to {}", res.summary(), res.path.display()),
            Err(e) => self.error(e),
        }
    }

    // ------------------------------------------------------------- dialogs
    fn modal_ui(&mut self, ctx: &egui::Context, repo: &Repository, status: &mut Status) {
        let Some(mut modal) = self.modal.take() else { return };
        let mut keep_open = true;
        match &mut modal {
            Modal::Message(text) => {
                window(ctx, "Pinner").show(ctx, |ui| {
                    ui.label(text.as_str());
                    ui.add_space(8.0);
                    if ui.button("OK").clicked() {
                        keep_open = false;
                    }
                });
            }
            Modal::ConfirmDeleteGroup(id) => {
                let name = self.groups.iter().find(|g| g.id == *id).map(|g| g.name.clone()).unwrap_or_default();
                window(ctx, "Delete folder").show(ctx, |ui| {
                    ui.label(format!("Delete “{name}” with all its sub-folders and entries?"));
                    ui.add_space(8.0);
                    ui.horizontal(|ui| {
                        if ui.button("Delete").clicked() {
                            match repo.delete_group(*id) {
                                Ok(()) => self.dirty = true,
                                Err(e) => status.0 = e.to_string(),
                            }
                            keep_open = false;
                        }
                        if ui.button("Cancel").clicked() {
                            keep_open = false;
                        }
                    });
                });
            }
            Modal::ConfirmDeleteItem(id) => {
                let name = self.find_item(*id).map(|i| i.name.clone()).unwrap_or_default();
                window(ctx, "Remove entry").show(ctx, |ui| {
                    ui.label(format!("Remove “{name}”? (The file or folder itself is not touched.)"));
                    ui.add_space(8.0);
                    ui.horizontal(|ui| {
                        if ui.button("Remove").clicked() {
                            match repo.delete_item(*id) {
                                Ok(()) => self.dirty = true,
                                Err(e) => status.0 = e.to_string(),
                            }
                            keep_open = false;
                        }
                        if ui.button("Cancel").clicked() {
                            keep_open = false;
                        }
                    });
                });
            }
            Modal::Prompt { kind, text, error } => {
                let title = match kind {
                    PromptKind::NewGroup(Some(_)) => "New sub-folder",
                    PromptKind::NewGroup(None) => "New folder",
                    PromptKind::Rename(_) => "Rename folder",
                };
                window(ctx, title).show(ctx, |ui| {
                    let edit = ui.add(egui::TextEdit::singleline(text).hint_text("Folder name").desired_width(280.0));
                    edit.request_focus();
                    if let Some(e) = error {
                        ui.colored_label(egui::Color32::LIGHT_RED, e.as_str());
                    }
                    ui.add_space(6.0);
                    let enter = edit.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
                    ui.horizontal(|ui| {
                        if ui.button("OK").clicked() || enter {
                            let res = match kind {
                                PromptKind::NewGroup(parent) => {
                                    repo.create_group(self.section, text, *parent).map(|g| Sel::Group(g.id))
                                }
                                PromptKind::Rename(id) => repo.rename_group(*id, text).map(|g| Sel::Group(g.id)),
                            };
                            match res {
                                Ok(sel) => {
                                    self.selected = Some(sel);
                                    self.dirty = true;
                                    keep_open = false;
                                }
                                Err(e) => *error = Some(e.to_string()),
                            }
                        }
                        if ui.button("Cancel").clicked() {
                            keep_open = false;
                        }
                    });
                });
            }
            Modal::Item(form) => {
                self.item_form_ui(ctx, form, repo, &mut keep_open);
            }
        }
        if keep_open && self.modal.is_none() {
            self.modal = Some(modal);
        }
    }

    fn item_form_ui(&mut self, ctx: &egui::Context, form: &mut ItemForm, repo: &Repository, keep_open: &mut bool) {
        // Files dropped while the dialog is open fill the target.
        if let Some(p) = ctx.input(|i| i.raw.dropped_files.iter().find_map(|f| f.path.clone())) {
            if let Ok((kind, name, target)) = dropped::entry_from_source(&p.display().to_string()) {
                if allowed_kinds(self.section).contains(&kind) {
                    form.kind = kind;
                    form.target = target;
                    if form.name.trim().is_empty() {
                        form.name = name;
                    }
                }
            }
        }
        let title = match (form.editing.is_some(), form.kind) {
            (true, _) => "Edit entry",
            (false, ItemKind::Url) => "Add web link",
            (false, ItemKind::Folder) => "Add folder",
            (false, ItemKind::File) => "Add file / app",
        };
        let kinds = allowed_kinds(self.section);
        window(ctx, title).show(ctx, |ui| {
            egui::Grid::new("item_form").num_columns(2).spacing([8.0, 8.0]).show(ui, |ui| {
                if kinds.len() > 1 {
                    ui.label("Type");
                    egui::ComboBox::from_id_salt("kind").selected_text(form.kind.label()).show_ui(ui, |ui| {
                        for &k in kinds {
                            ui.selectable_value(&mut form.kind, k, k.label());
                        }
                    });
                    ui.end_row();
                }
                ui.label(if form.kind == ItemKind::Url { "Link" } else { "Path" });
                ui.horizontal(|ui| {
                    ui.add(egui::TextEdit::singleline(&mut form.target).desired_width(320.0));
                    if form.kind != ItemKind::Url && ui.button("Browse…").clicked() {
                        let picked = if form.kind == ItemKind::Folder {
                            rfd::FileDialog::new().pick_folder()
                        } else {
                            rfd::FileDialog::new().pick_file()
                        };
                        if let Some(p) = picked {
                            form.target = p.display().to_string();
                        }
                    }
                });
                ui.end_row();
                ui.label("Display name");
                ui.add(egui::TextEdit::singleline(&mut form.name).hint_text("optional").desired_width(320.0));
                ui.end_row();
            });
            if form.kind != ItemKind::Url {
                ui.weak("Tip: drop a file or folder here to fill in the path.");
            }
            if let Some(e) = &form.error {
                ui.colored_label(egui::Color32::LIGHT_RED, e);
            }
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                if ui.button("Save").clicked() {
                    let name = if form.name.trim().is_empty() { default_name(form.kind, &form.target) } else { form.name.clone() };
                    let res = match form.editing {
                        Some(id) => repo.update_item(id, Some(&name), Some(&form.target), Some(form.kind)),
                        None => repo.add_item(form.group_id, form.kind, &name, &form.target, false),
                    };
                    match res {
                        Ok(item) => {
                            self.selected = Some(Sel::Item(item.id));
                            self.dirty = true;
                            *keep_open = false;
                        }
                        Err(e) => form.error = Some(e.to_string()),
                    }
                }
                if ui.button("Cancel").clicked() {
                    *keep_open = false;
                }
            });
        });
    }
}

thread_local! {
    static COPY_PENDING: std::cell::RefCell<Option<String>> = const { std::cell::RefCell::new(None) };
}

/// Text queued by "Copy path / link"; the app copies it to the clipboard.
pub fn take_copy_request() -> Option<String> {
    COPY_PENDING.with(|c| c.borrow_mut().take())
}

fn window(ctx: &egui::Context, title: &str) -> egui::Window<'static> {
    let _ = ctx;
    egui::Window::new(title.to_string())
        .collapsible(false)
        .resizable(false)
        .anchor(egui::Align2::CENTER_CENTER, [0.0, 0.0])
}

fn matches(item: &Item, needle: &str) -> bool {
    item.name.to_lowercase().contains(needle) || item.target.to_lowercase().contains(needle)
}

fn shorten(text: &str, max: usize) -> String {
    let n = text.chars().count();
    if n <= max {
        return text.to_string();
    }
    let tail: String = text.chars().skip(n - (max - 1)).collect();
    format!("…{tail}")
}

/// A sensible display name when the user leaves it empty.
fn default_name(kind: ItemKind, target: &str) -> String {
    let t = target.trim();
    match kind {
        ItemKind::Url => t.split_once("://").map_or(t, |(_, r)| r).split('/').next().unwrap_or(t).to_string(),
        _ => t
            .trim_end_matches(['/', '\\'])
            .rsplit(['/', '\\'])
            .next()
            .filter(|s| !s.is_empty())
            .unwrap_or(t)
            .to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_names() {
        assert_eq!(default_name(ItemKind::Url, "https://example.com/a/b"), "example.com");
        assert_eq!(default_name(ItemKind::Url, "example.com"), "example.com");
        assert_eq!(default_name(ItemKind::File, "/home/me/report.pdf"), "report.pdf");
        assert_eq!(default_name(ItemKind::Folder, "C:\\Users\\me\\Docs\\"), "Docs");
    }

    #[test]
    fn shorten_keeps_the_end() {
        assert_eq!(shorten("abc", 10), "abc");
        assert_eq!(shorten("abcdefghij", 5), "…ghij");
    }

    #[test]
    fn search_hides_unrelated_folders() {
        let repo = Repository::in_memory().unwrap();
        let a = repo.create_group(Section::Paths, "A", None).unwrap();
        let sub = repo.create_group(Section::Paths, "Sub", Some(a.id)).unwrap();
        let b = repo.create_group(Section::Paths, "B", None).unwrap();
        repo.add_item(sub.id, ItemKind::File, "needle.txt", "/x/needle.txt", false).unwrap();
        repo.add_item(b.id, ItemKind::File, "hay", "/x/hay", false).unwrap();
        let mut view = SectionView::new(Section::Paths);
        view.reload(&repo);
        let vis = view.visible_groups("needle").unwrap();
        assert!(vis.contains(&a.id) && vis.contains(&sub.id) && !vis.contains(&b.id));
        assert!(view.visible_groups("").is_none());
        assert_eq!(view.group_path(sub.id), "A / Sub");
    }
}
