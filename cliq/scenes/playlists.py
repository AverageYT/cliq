"""Playlists: make lists of songs and play them in order or shuffled.

Left: your playlists. Right: the songs in the highlighted one, each with its
own game mode and difficulty. Press A to pick songs from your library.
"""

from __future__ import annotations

import time

import pygame

from ..charting.profiles import load_profiles
from ..library.playlists import PlaylistBook
from ..modes import MODES, get_mode
from ..render import vector as V
from ..render.fx import clamp01, ease_out_back
from ..render.widgets import Button, TextInput, panel
from ..runs import PlaylistRun
from ..util import darken, format_time, hex_to_rgb
from .base import Scene
from .run_flow import launch_stage, stage_label

ROW_H, CARD_H = 54, 70


class PlaylistsScene(Scene):
    def __init__(self, app, select: str | None = None):
        super().__init__(app)
        self.book = PlaylistBook()
        self.index = 0
        self.entry = 0
        self.focus = "lists"            # or "songs"
        self.picker: dict | None = None  # {"index": int, "scroll": float, "t": float}
        self.renaming = False
        self._confirm = (None, 0.0)
        self.t = 0.0
        w, h = self.size
        theme = self.theme
        self.left = pygame.Rect(self.s(36), self.s(92), self.s(390), h - self.s(92) - self.s(36))
        self.right = pygame.Rect(self.s(450), self.s(92), w - self.s(486), h - self.s(92) - self.s(36))
        self.left_img = panel(self.left.size, self.ui)
        self.right_img = panel(self.right.size, self.ui)
        r = self.right
        bh, by = self.s(54), r.bottom - self.s(54) - self.s(18)
        specs = [("Play", self.play, theme.c("accent"), 150, "Enter"),
                 ("Shuffle", self.shuffle_play, theme.c("accent5"), 150, "S"),
                 ("Add songs", self.open_picker, theme.c("accent3"), 170, "A"),
                 ("Rename", self.start_rename, theme.c("panel_light"), 130, "F2"),
                 ("Delete", self.delete, theme.c("bad"), 120, "Del")]
        x = r.x + self.s(20)
        self.buttons = []
        for label, cb, color, bw, sub in specs:
            self.buttons.append(Button(self.ui, (x, by, self.s(bw), bh), label, cb, color=color, size=22,
                                       sublabel=sub))
            x += self.s(bw) + self.s(10)
        self.new_btn = Button(self.ui, (self.left.x + self.s(18), self.left.bottom - bh - self.s(18),
                                        self.left.width - self.s(36), bh), "New playlist", self.new_playlist,
                              color=theme.c("accent4"), size=22, sublabel="N")
        self.name_input = TextInput(self.ui, (r.x + self.s(20), r.y + self.s(16), r.width - self.s(40), self.s(50)),
                                    "Playlist name", on_submit=self.finish_rename, size=24)
        self.picker_rect = pygame.Rect(0, 0, self.s(720), self.s(560))
        self.picker_rect.center = (w // 2, h // 2 + self.s(20))
        self.picker_img = panel(self.picker_rect.size, self.ui, alpha=250)
        self.shade = pygame.Surface(self.size, pygame.SRCALPHA)
        self.shade.fill((*darken(theme.c("ink"), 0.4), 150))
        if select:
            self.index = next((i for i, p in enumerate(self.book.playlists) if p.id == select), 0)
        elif app.settings.last_playlist:
            self.index = next((i for i, p in enumerate(self.book.playlists) if p.id == app.settings.last_playlist), 0)

    # ------------------------------------------------------------ data
    @property
    def playlist(self):
        pl = self.book.playlists
        return pl[self.index] if 0 <= self.index < len(pl) else None

    def enter(self) -> None:
        self.app.library.scan()
        self._preview()

    def resume(self, **result) -> None:
        self.book.load()
        self.app.library.scan()
        self.index = min(self.index, max(0, len(self.book.playlists) - 1))
        self._preview()

    def _song(self, song_id):
        return self.app.library.get(song_id)

    def _preview(self) -> None:
        pl = self.playlist
        if pl and pl.entries:
            e = pl.entries[min(self.entry, len(pl.entries) - 1)]
            song = self._song(e.song_id)
            if song:
                self.app.menu_music.play(song)

    def _save(self) -> None:
        self.book.save()
        if self.playlist:
            self.app.settings.last_playlist = self.playlist.id

    def _ask(self, action: str, message: str) -> bool:
        now = time.perf_counter()
        if self._confirm[0] == action and now - self._confirm[1] < 3.0:
            self._confirm = (None, 0.0)
            return True
        self._confirm = (action, now)
        self.app.toasts.show(message, self.theme.c("bad"))
        return False

    # ------------------------------------------------------------ actions
    def select(self, i: int) -> None:
        pl = self.book.playlists
        if pl:
            i = max(0, min(len(pl) - 1, i))
            if i != self.index:
                self.index, self.entry = i, 0
                self.app.sfx("ui_move")
                self._preview()

    def select_entry(self, i: int) -> None:
        pl = self.playlist
        if pl and pl.entries:
            i = max(0, min(len(pl.entries) - 1, i))
            if i != self.entry:
                self.entry = i
                self.app.sfx("ui_move")
                self._preview()

    def new_playlist(self) -> None:
        pl = self.book.create(f"Playlist {len(self.book.playlists) + 1}")
        self.index = len(self.book.playlists) - 1
        self.entry = 0
        self._save()
        self.start_rename()
        self.name_input.set_text(pl.name)

    def start_rename(self) -> None:
        if self.playlist is None:
            return
        self.renaming = True
        self.name_input.set_text(self.playlist.name)
        self.name_input.focused = True
        pygame.key.start_text_input()

    def finish_rename(self, text: str | None = None) -> None:
        if self.renaming and self.playlist is not None:
            name = (text if text is not None else self.name_input.text).strip()
            if name:
                self.playlist.name = name[:40]
                self._save()
        self.renaming = False
        self.name_input.focused = False
        pygame.key.stop_text_input()

    def delete(self) -> None:
        pl = self.playlist
        if pl is None:
            return
        if self.focus == "songs" and pl.entries:
            entry = pl.entries.pop(min(self.entry, len(pl.entries) - 1))
            self.entry = max(0, min(self.entry, len(pl.entries) - 1))
            self._save()
            song = self._song(entry.song_id)
            self.app.toasts.show(f"Removed {song.title if song else 'song'} from {pl.name}")
            return
        if self._ask("delete", f"Press Delete again to delete \"{pl.name}\""):
            self.book.delete(pl.id)
            self.index = max(0, self.index - 1)
            self.app.toasts.show(f"Deleted \"{pl.name}\"")

    def _start(self, shuffle: bool) -> None:
        pl = self.playlist
        if pl is None or not pl.entries:
            self.app.toasts.show("Add some songs first (A)", self.theme.c("bad"))
            return
        pl.shuffle = shuffle
        self._save()
        self.app.settings.save()
        run = PlaylistRun.from_playlist(pl, shuffle=shuffle, modifiers=list(self.app.settings.enabled_modifiers))
        launch_stage(self.app, run)

    def play(self) -> None:
        self._start(False)

    def shuffle_play(self) -> None:
        self._start(True)

    def change_entry(self, what: str, delta: int) -> None:
        pl = self.playlist
        if pl is None or not pl.entries:
            return
        e = pl.entries[self.entry]
        if what == "mode":
            ids = list(MODES)
            e.mode = ids[(ids.index(e.mode) + delta) % len(ids)] if e.mode in ids else "keys"
        else:
            ids = list(load_profiles())
            e.difficulty = ids[(ids.index(e.difficulty) + delta) % len(ids)] if e.difficulty in ids else ids[1]
        self.app.sfx("ui_move")
        self._save()

    def move_entry(self, delta: int) -> None:
        pl = self.playlist
        if pl:
            new = pl.move(self.entry, delta)
            if new != self.entry:
                self.entry = new
                self._save()

    # ------------------------------------------------------------ picker
    def open_picker(self) -> None:
        if self.playlist is None:
            self.new_playlist()
            self.finish_rename()
        songs = self.app.library.songs
        if not songs:
            self.app.toasts.show("Your library is empty - add songs in Pick a song", self.theme.c("bad"))
            return
        self.picker = {"index": 0, "scroll": 0.0, "t": 0.0}

    def picker_toggle(self, i: int) -> None:
        pl = self.playlist
        songs = self.app.library.songs
        if pl is None or not 0 <= i < len(songs):
            return
        song = songs[i]
        if pl.contains(song.id):
            pl.entries = [e for e in pl.entries if e.song_id != song.id]
            self.app.sfx("ui_back")
        else:
            settings = self.app.settings
            diff = settings.last_difficulty if settings.last_difficulty in load_profiles() else \
                settings.default_difficulty
            pl.add(song.id, settings.last_mode if settings.last_mode in MODES else "keys", diff)
            self.app.sfx("ui_select")
        self.entry = min(self.entry, max(0, len(pl.entries) - 1))
        self._save()

    def _picker_rows(self):
        r = self.picker_rect
        top = r.y + self.s(84)
        rows = (r.height - self.s(84) - self.s(56)) // self.s(ROW_H)
        return top, rows

    def _picker_event(self, e) -> None:
        songs = self.app.library.songs
        p = self.picker
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_ESCAPE, pygame.K_a, pygame.K_TAB):
                self.picker = None
                self.app.sfx("ui_back")
            elif e.key == pygame.K_UP:
                p["index"] = max(0, p["index"] - 1)
            elif e.key == pygame.K_DOWN:
                p["index"] = min(len(songs) - 1, p["index"] + 1)
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.picker_toggle(p["index"])
            return
        if e.type == pygame.MOUSEWHEEL:
            p["index"] = max(0, min(len(songs) - 1, p["index"] - e.y))
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if not self.picker_rect.collidepoint(e.pos):
                self.picker = None
                return
            top, rows = self._picker_rows()
            first = self._picker_first(rows)
            i = first + (e.pos[1] - top) // self.s(ROW_H)
            if e.pos[1] >= top and first <= i < min(len(songs), first + rows):
                p["index"] = i
                self.picker_toggle(i)

    def _picker_first(self, rows: int) -> int:
        n = len(self.app.library.songs)
        return max(0, min(n - rows, self.picker["index"] - rows // 2))

    # ------------------------------------------------------------ events
    def handle_event(self, e) -> None:
        if self.renaming:
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.renaming = False
                self.name_input.focused = False
                pygame.key.stop_text_input()
                return
            if e.type == pygame.MOUSEBUTTONDOWN and not self.name_input.rect.collidepoint(e.pos):
                self.finish_rename()
                return
            self.name_input.handle_event(e)
            return
        if self.picker is not None:
            self._picker_event(e)
            return
        if e.type == pygame.KEYDOWN:
            k, mods = e.key, e.mod
            alt = mods & pygame.KMOD_ALT
            if k == pygame.K_ESCAPE:
                if self.focus == "songs":
                    self.focus = "lists"
                else:
                    self.app.sfx("ui_back")
                    self.app.pop()
            elif k == pygame.K_UP:
                if self.focus == "songs":
                    self.move_entry(-1) if alt else self.select_entry(self.entry - 1)
                else:
                    self.select(self.index - 1)
            elif k == pygame.K_DOWN:
                if self.focus == "songs":
                    self.move_entry(1) if alt else self.select_entry(self.entry + 1)
                else:
                    self.select(self.index + 1)
            elif k == pygame.K_RIGHT:
                if self.focus == "lists" and self.playlist and self.playlist.entries:
                    self.focus = "songs"
                    self.app.sfx("ui_move")
                elif self.focus == "songs":
                    self.change_entry("difficulty", 1)
            elif k == pygame.K_LEFT:
                if self.focus == "songs":
                    if mods & pygame.KMOD_SHIFT or alt:
                        self.change_entry("difficulty", -1)
                    else:
                        self.focus = "lists"
                        self.app.sfx("ui_move")
            elif k in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET) and self.focus == "songs":
                self.change_entry("difficulty", -1 if k == pygame.K_LEFTBRACKET else 1)
            elif k == pygame.K_m and self.focus == "songs":
                self.change_entry("mode", -1 if mods & pygame.KMOD_SHIFT else 1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.play()
            elif k == pygame.K_s:
                self.shuffle_play()
            elif k == pygame.K_a:
                self.open_picker()
            elif k == pygame.K_n:
                self.new_playlist()
            elif k == pygame.K_F2:
                self.start_rename()
            elif k in (pygame.K_DELETE, pygame.K_BACKSPACE):
                self.delete()
            return
        if e.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.right.collidepoint(self.app.display.to_render(pos)):
                self.select_entry(self.entry - e.y)
            else:
                self.select(self.index - e.y)
            return
        for b in self.buttons + [self.new_btn]:
            if b.handle_event(e):
                return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for rect, i in self._card_rects():
                if rect.collidepoint(e.pos):
                    self.focus = "lists"
                    self.select(i)
                    return
            for rect, i, zones in self._entry_rects():
                if rect.collidepoint(e.pos):
                    self.focus = "songs"
                    self.select_entry(i)
                    if zones["mode"].collidepoint(e.pos):
                        self.change_entry("mode", 1)
                    elif zones["diff"].collidepoint(e.pos):
                        self.change_entry("difficulty", 1)
                    return
            if self.right.y < e.pos[1] < self.right.y + self.s(70) and self.right.collidepoint(e.pos):
                self.start_rename()

    # ------------------------------------------------------------ layout
    def _card_rects(self):
        r = self.left
        step = self.s(CARD_H + 10)
        top = r.y + self.s(18)
        rows = (r.height - self.s(100)) // step
        first = max(0, min(len(self.book.playlists) - rows, self.index - rows // 2))
        out = []
        for i in range(first, min(len(self.book.playlists), first + rows)):
            out.append((pygame.Rect(r.x + self.s(16), top + (i - first) * step, r.width - self.s(32), self.s(CARD_H)),
                        i))
        return out

    def _entry_rects(self):
        pl = self.playlist
        if pl is None:
            return []
        r = self.right
        top = r.y + self.s(84)
        step = self.s(ROW_H)
        rows = max(1, (r.height - self.s(84) - self.s(90)) // step)
        first = max(0, min(len(pl.entries) - rows, self.entry - rows // 2))
        out = []
        for i in range(first, min(len(pl.entries), first + rows)):
            rect = pygame.Rect(r.x + self.s(16), top + (i - first) * step, r.width - self.s(32), step - self.s(6))
            mode = pygame.Rect(rect.right - self.s(270), rect.y, self.s(110), rect.height)
            diff = pygame.Rect(rect.right - self.s(150), rect.y, self.s(140), rect.height)
            out.append((rect, i, {"mode": mode, "diff": diff}))
        return out

    # ------------------------------------------------------------ frame
    def update(self, dt: float) -> None:
        self.t += dt
        for b in self.buttons + [self.new_btn]:
            b.update(dt)
        self.name_input.update(dt)
        if self.picker is not None:
            self.picker["t"] += dt
        has = self.playlist is not None
        for b in self.buttons:
            b.enabled = has
        if self.focus == "songs" and not (self.playlist and self.playlist.entries):
            self.focus = "lists"

    def draw(self, surf) -> None:
        self.app.background.draw(surf)
        w, h = self.size
        theme = self.theme
        self.fonts.draw(surf, "Playlists", (self.s(40), self.s(20)), "display", 46, (255, 255, 255), outline=5,
                        shadow=6)
        hint = "Enter play  -  S shuffle  -  A add songs  -  Right: edit songs  -  M mode  -  [ ] difficulty  -  Esc back"
        self.fonts.draw(surf, hint, (w - self.s(36), self.s(40)), "ui", 16, theme.c("text_dim"), anchor="midright",
                        outline=2, max_width=820)
        surf.blit(self.left_img, self.left)
        surf.blit(self.right_img, self.right)
        self._draw_cards(surf)
        self._draw_entries(surf)
        for b in self.buttons:
            b.draw(surf)
        self.new_btn.draw(surf)
        if self.picker is not None:
            self._draw_picker(surf)

    def _draw_cards(self, surf) -> None:
        theme = self.theme
        if not self.book.playlists:
            self.fonts.draw(surf, "No playlists yet", (self.left.centerx, self.left.y + self.s(120)), "display", 28,
                            (255, 255, 255), anchor="center", outline=3)
            self.fonts.draw(surf, "Press N to make one", (self.left.centerx, self.left.y + self.s(160)), "bold", 19,
                            theme.c("text_dim"), anchor="center", outline=2)
            return
        for rect, i in self._card_rects():
            pl = self.book.playlists[i]
            selected = i == self.index
            color = theme.c("accent") if selected else theme.c("panel_light")
            edge = theme.c("accent2") if selected and self.focus == "lists" else theme.c("ink")
            card = V.rounded_rect(rect.size, self.s(18), color, edge, outline=max(2, self.s(3.5 if selected else 3)))
            surf.blit(card, rect.move(self.s(10) if selected else 0, 0))
            x = rect.x + self.s(18) + (self.s(10) if selected else 0)
            self.fonts.draw(surf, pl.name, (x, rect.y + self.s(8)), "bold", 23, (255, 255, 255), outline=3,
                            max_width=300)
            total = sum((self._song(e.song_id).duration if self._song(e.song_id) else 0.0) for e in pl.entries)
            info = f"{len(pl.entries)} song{'s' if len(pl.entries) != 1 else ''}  -  {format_time(total)}"
            if pl.shuffle:
                info += "  -  shuffle"
            self.fonts.draw(surf, info, (x, rect.y + self.s(40)), "ui", 17,
                            (255, 240, 248) if selected else theme.c("text_dim"))

    def _draw_entries(self, surf) -> None:
        theme = self.theme
        r = self.right
        pl = self.playlist
        if pl is None:
            self.fonts.draw(surf, "Make a playlist to group songs together,", (r.centerx, r.y + self.s(150)), "bold",
                            22, theme.c("text_dim"), anchor="center", outline=2)
            self.fonts.draw(surf, "then play them in order or shuffled.", (r.centerx, r.y + self.s(184)), "bold", 22,
                            theme.c("text_dim"), anchor="center", outline=2)
            return
        if self.renaming:
            self.name_input.draw(surf)
            self.fonts.draw(surf, "Enter to save, Esc to cancel", (r.x + self.s(22), r.y + self.s(70)), "ui", 15,
                            theme.c("text_dim"))
        else:
            self.fonts.draw(surf, pl.name, (r.x + self.s(22), r.y + self.s(16)), "display", 34, (255, 255, 255),
                            outline=4, shadow=4, max_width=640)
            self.fonts.draw(surf, "click or F2 to rename", (r.right - self.s(22), r.y + self.s(30)), "ui", 15,
                            theme.c("text_dim"), anchor="topright")
        if not pl.entries:
            self.fonts.draw(surf, "No songs yet - press A to add some", (r.centerx, r.y + self.s(170)), "bold", 22,
                            theme.c("text_dim"), anchor="center", outline=2)
            return
        for rect, i, zones in self._entry_rects():
            e = pl.entries[i]
            song = self._song(e.song_id)
            selected = i == self.entry
            if selected:
                col = darken(theme.c("accent"), 0.1) if self.focus == "songs" else theme.c("panel_light")
                pygame.draw.rect(surf, col, rect, border_radius=self.s(14))
                if self.focus == "songs":
                    pygame.draw.rect(surf, theme.c("accent2"), rect, max(2, self.s(3)), border_radius=self.s(14))
            self.fonts.draw(surf, f"{i + 1}", (rect.x + self.s(26), rect.centery), "display", 20,
                            theme.c("text_dim"), anchor="center", outline=2)
            title = song.title if song else "(deleted song)"
            self.fonts.draw(surf, title, (rect.x + self.s(52), rect.y + self.s(4)), "bold", 21,
                            (255, 255, 255) if song else theme.c("bad"), outline=2, max_width=330)
            if song:
                self.fonts.draw(surf, f"{song.artist}  -  {format_time(song.duration)}",
                                (rect.x + self.s(52), rect.y + self.s(27)), "ui", 15, theme.c("text_dim"),
                                max_width=330)
            mode = get_mode(e.mode)
            for zone, label, color in ((zones["mode"], mode.name, hex_to_rgb(mode.color)),
                                       (zones["diff"], stage_label(e).split()[-1], self._diff_color(e.difficulty))):
                pill = zone.inflate(-self.s(8), -self.s(14))
                img = V.rounded_rect(pill.size, pill.height / 2, color, theme.c("ink"), outline=max(2, self.s(2.5)))
                txt = self.fonts.render(label, "bold", 16, theme.c("ink"))
                img.blit(txt, txt.get_rect(center=(pill.width / 2, pill.height / 2)))
                surf.blit(img, pill)

    def _diff_color(self, difficulty: str):
        prof = load_profiles().get(difficulty)
        return hex_to_rgb(prof.color) if prof else self.theme.c("accent2")

    def _draw_picker(self, surf) -> None:
        theme = self.theme
        surf.blit(self.shade, (0, 0))
        k = ease_out_back(clamp01(self.picker["t"] / 0.25))
        r = self.picker_rect
        img = self.picker_img
        if k < 0.995:
            img = pygame.transform.smoothscale(img, (max(1, int(r.width * k)), max(1, int(r.height * k))))
            surf.blit(img, img.get_rect(center=r.center))
            return
        surf.blit(img, r)
        pl = self.playlist
        self.fonts.draw(surf, f"Add songs to {pl.name}", (r.x + self.s(24), r.y + self.s(18)), "display", 28,
                        (255, 255, 255), outline=3, max_width=640)
        self.fonts.draw(surf, "Enter/click to add or remove  -  Esc when done", (r.x + self.s(26), r.y + self.s(56)),
                        "ui", 16, theme.c("text_dim"))
        songs = self.app.library.songs
        top, rows = self._picker_rows()
        first = self._picker_first(rows)
        for j, i in enumerate(range(first, min(len(songs), first + rows))):
            song = songs[i]
            rect = pygame.Rect(r.x + self.s(16), top + j * self.s(ROW_H), r.width - self.s(32), self.s(ROW_H - 6))
            if i == self.picker["index"]:
                pygame.draw.rect(surf, theme.c("panel_light"), rect, border_radius=self.s(12))
            added = pl.contains(song.id)
            box = pygame.Rect(0, 0, self.s(28), self.s(28))
            box.midleft = (rect.x + self.s(14), rect.centery)
            pygame.draw.rect(surf, theme.c("ink"), box.inflate(self.s(4), self.s(4)), border_radius=self.s(8))
            pygame.draw.rect(surf, theme.c("good") if added else theme.c("panel"), box, border_radius=self.s(7))
            if added:
                pygame.draw.lines(surf, theme.c("ink"), False, [(box.x + box.w * 0.22, box.centery),
                                                               (box.x + box.w * 0.43, box.bottom - box.h * 0.25),
                                                               (box.right - box.w * 0.2, box.y + box.h * 0.25)],
                                  max(2, self.s(4)))
            self.fonts.draw(surf, song.title, (rect.x + self.s(56), rect.y + self.s(4)), "bold", 21, (255, 255, 255),
                            outline=2, max_width=440)
            self.fonts.draw(surf, song.artist, (rect.x + self.s(56), rect.y + self.s(27)), "ui", 15,
                            theme.c("text_dim"), max_width=440)
            self.fonts.draw(surf, format_time(song.duration), (rect.right - self.s(16), rect.centery), "bold", 18,
                            (255, 255, 255), anchor="midright", outline=2)
        self.fonts.draw(surf, f"{len(pl.entries)} in playlist", (r.centerx, r.bottom - self.s(30)), "bold", 18,
                        theme.c("accent2"), anchor="center", outline=2)
