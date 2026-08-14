"""Packaged Qt widgets for the project home page and toolbar identity."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.app.application_metadata import (
    RELEASE_NOTES_UI_ENABLED,
)
from bdo_music_composer.ui.editor.bdo_instrument_lane_art_qt import InstrumentLaneArtwork
from bdo_midi import BDO_ENSEMBLE_PLAYER_LIMIT
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.core.project_paths import ASSETS_DIR


HOME_BACKGROUND_IMAGE = (
    ASSETS_DIR / "ui" / "home" / "home_aristocratic_salon_v2.png"
)
SHAI_ENSEMBLE_MARK_IMAGE = ASSETS_DIR / "icons" / "shai_ensemble_mark.png"
HOME_INSTRUMENT_IDS_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class HomeLibrarySurface(QFrame):
    """One quiet material layer for the complete home library."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeLibrarySurface")
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(14, 12, 14, 10)
        self.content_layout.setSpacing(10)


class HomeHero(QWidget):
    """Compact title block that anchors the home command column."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeHero")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(2)
        title = QLabel(tr("继续创作"))
        title.setObjectName("HomeTitle")
        subtitle = QLabel(tr("从最近工程继续，或开始一个新的编曲项目"))
        subtitle.setObjectName("HomeSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)


class HomeLibraryTabs(QFrame):
    """Fixed-height host that makes the two library tabs read as one control."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeLibraryTabs")
        self.setFixedHeight(36)
        self.content_layout = QHBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)


class HomeFooter(QWidget):
    """Public privacy footer with a dormant internal release-notes hook."""

    release_notes_requested = Signal()

    def __init__(
        self,
        version: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.version = str(version)
        self.setObjectName("HomeFooter")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 7, 2, 0)
        layout.setSpacing(8)
        self.local_badge = QLabel()
        self.local_badge.setObjectName("HomeLocalBadge")
        self.local_badge.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.local_badge)
        layout.addStretch(1)
        self.release_notes_button = QPushButton()
        self.release_notes_button.setObjectName("HomeReleaseNotesButton")
        self.release_notes_button.setProperty("kind", "ghost")
        self.release_notes_button.setCursor(Qt.PointingHandCursor)
        self.release_notes_button.clicked.connect(
            self.release_notes_requested.emit
        )
        self.release_notes_button.setVisible(RELEASE_NOTES_UI_ENABLED)
        layout.addWidget(self.release_notes_button)
        self.retranslate_dynamic_content()

    def retranslate_dynamic_content(self) -> None:
        self.local_badge.setText(tr("本地处理 · 不上传工程"))
        if RELEASE_NOTES_UI_ENABLED:
            self.release_notes_button.setText(
                trf("更新日志 · v{version}", version=self.version)
            )
        else:
            self.release_notes_button.setText("")


class HomeIdentityBadge(QPushButton):
    """Compact Owner-ID status entry for the home brand row."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._primary = tr("Owner ID 未设置")
        self._secondary = tr("Owner ID 未设置；点击前往设置")
        self._owner_id_bound = False
        self.setObjectName("HomeOwnerIdButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(30)
        self.setMinimumWidth(134)
        self.setMaximumWidth(180)
        self.setText(self._primary)

    def set_owner_id(self, owner_id: int) -> None:
        self._owner_id_bound = bool(owner_id)
        if self._owner_id_bound:
            self._primary = tr("Owner ID 已绑定")
            self._secondary = tr("点击头像，从游戏曲谱快速设置 Owner ID")
        else:
            self._primary = tr("Owner ID 未设置")
            self._secondary = tr("点击头像，从游戏曲谱快速设置 Owner ID")
        self.setText(self._primary)
        self.setToolTip(self._secondary)
        self.setAccessibleName(self._primary)
        self.setAccessibleDescription(self._secondary)
        missing = not self._owner_id_bound
        self.setProperty("ownerIdMissing", missing)
        # Kept for callers that used the older generic identity state.
        self.setProperty("identityMissing", missing)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(154, 30)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown() or self.underMouse() or self.hasFocus():
            painter.setBrush(
                QColor(43, 39, 32, 210)
                if self.isDown()
                else QColor(35, 33, 29, 176)
            )
            painter.setPen(QPen(QColor("#5b4c36"), 1))
            painter.drawRoundedRect(bounds, 5.0, 5.0)

        # A compact anonymous avatar makes the direct identity action clear
        # without exposing the character name on the home surface.
        avatar_outline = QColor("#a68a57" if self._owner_id_bound else "#707070")
        painter.setBrush(QColor(29, 29, 29, 210))
        painter.setPen(QPen(avatar_outline, 1.1))
        painter.drawEllipse(QRectF(4.0, 3.0, 24.0, 24.0))
        painter.setBrush(avatar_outline)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(12.0, 8.0, 8.0, 8.0))
        painter.drawEllipse(QRectF(8.5, 16.0, 15.0, 8.0))

        # The status lamp is deliberately neutral while the required ID is
        # absent. It becomes green only after a valid Owner ID is loaded.
        accent = QColor("#8ead77" if self._owner_id_bound else "#777777")
        painter.setBrush(accent)
        painter.setPen(QPen(QColor("#181817"), 1))
        painter.drawEllipse(QRectF(21.0, 20.0, 7.0, 7.0))

        primary_font = QFont(painter.font())
        primary_font.setPointSize(9)
        primary_font.setBold(self._owner_id_bound)
        painter.setFont(primary_font)
        primary_rect = QRectF(
            35.0, 3.0, max(54.0, bounds.width() - 52.0), 24.0
        )
        painter.setPen(
            QColor("#e3ddd2" if self._owner_id_bound else "#999999")
        )
        painter.drawText(
            primary_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(
                self._primary, Qt.ElideRight, int(primary_rect.width())
            ),
        )
        painter.setPen(QColor("#6f6659"))
        painter.drawText(
            QRectF(bounds.right() - 16.0, 0.0, 12.0, bounds.height()),
            Qt.AlignCenter,
            "›",
        )


class EnsembleCapacityBadge(QPushButton):
    """Toolbar logo carrying Owner-ID state and quiet ensemble context."""

    def __init__(
        self,
        icon_path: Path = SHAI_ENSEMBLE_MARK_IMAGE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EnsembleCapacityBadge")
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFlat(True)
        self._player_count = 0
        self._owner_id_bound = False
        self.setProperty("ownerIdMissing", True)
        self._description_override = ""
        source = QPixmap(str(icon_path))
        self._icon = source.scaled(
            30,
            30,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        ) if not source.isNull() else QPixmap()
        self._refresh_description()

    @property
    def player_count(self) -> int:
        return self._player_count

    @property
    def is_over_limit(self) -> bool:
        return self._player_count > BDO_ENSEMBLE_PLAYER_LIMIT

    def set_player_count(
        self,
        player_count: int,
        description_override: str = "",
    ) -> None:
        normalized = max(0, int(player_count))
        normalized_description = str(description_override or "").strip()
        if (
            normalized == self._player_count
            and normalized_description == self._description_override
        ):
            return
        self._player_count = normalized
        self._description_override = normalized_description
        self._refresh_description()
        self.update()

    def set_owner_id(self, owner_id: int) -> None:
        bound = bool(owner_id)
        if bound == self._owner_id_bound:
            return
        self._owner_id_bound = bound
        self.setProperty("ownerIdMissing", not bound)
        self._refresh_description()
        self.update()

    def _refresh_description(self) -> None:
        if self._description_override:
            description = self._description_override
        elif self._player_count <= 0:
            description = tr("当前工程没有需要演奏的实体乐器")
        elif self.is_over_limit:
            description = trf(
                "当前工程预计 {count} 人演奏，超过 {limit} 人队伍上限",
                count=self._player_count,
                limit=BDO_ENSEMBLE_PLAYER_LIMIT,
            )
        else:
            description = trf(
                "当前工程预计 {count}/{limit} 人演奏；同一实体乐器只计一人",
                count=self._player_count,
                limit=BDO_ENSEMBLE_PLAYER_LIMIT,
            )
        owner_description = tr(
            "Owner ID 已绑定；点击 Logo 可更改"
            if self._owner_id_bound
            else "Owner ID 未设置；点击 Logo 快速设置"
        )
        self.setToolTip(f"{owner_description}\n{description}")
        self.setAccessibleName(tr("Owner ID 快捷设置"))
        self.setAccessibleDescription(f"{owner_description}。{description}")

    def retranslate_dynamic_content(self) -> None:
        self._refresh_description()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not self._icon.isNull():
            painter.save()
            painter.setOpacity(0.9)
            painter.drawPixmap(3, 3, self._icon)
            painter.restore()

        # Owner identity is carried by the logo itself, so the state remains
        # available on both home and editor pages without another home widget.
        painter.setPen(Qt.NoPen)
        painter.setBrush(
            QColor("#8ead77")
            if self._owner_id_bound
            else QColor("#777777")
        )
        painter.drawEllipse(QRectF(27.0, 26.0, 6.0, 6.0))


class HomeBackdrop(QFrame):
    """Cached full-bleed home artwork with fixed readability gradients."""

    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeShell")
        self._source = QPixmap(str(image_path))
        self._cover = QPixmap()
        self._refresh_cover()

    @property
    def has_artwork(self) -> bool:
        return not self._source.isNull()

    def _refresh_cover(self) -> None:
        if self._source.isNull() or self.width() <= 0 or self.height() <= 0:
            self._cover = QPixmap()
            return
        self._cover = self._source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_cover()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111214"))
        if not self._cover.isNull():
            # Anchor the crop to the right so the character remains visible at
            # every supported window aspect ratio.
            source_x = max(0, self._cover.width() - self.width())
            source_y = max(0, (self._cover.height() - self.height()) // 2)
            painter.drawPixmap(
                self.rect(),
                self._cover,
                self._cover.rect().adjusted(
                    source_x,
                    source_y,
                    0,
                    -source_y,
                ),
            )

        # The illustration is intentionally prominent, but a light full-image
        # wash keeps the bright valley from competing with every control in the
        # functional layer.  The stronger left gradient below is reserved for
        # text readability and fades gradually instead of forming a black wall.
        painter.fillRect(self.rect(), QColor(14, 15, 15, 24))

        readability = QLinearGradient(
            0.0,
            0.0,
            float(self.width()),
            0.0,
        )
        readability.setColorAt(0.0, QColor(8, 9, 10, 158))
        readability.setColorAt(0.24, QColor(9, 10, 11, 138))
        readability.setColorAt(0.46, QColor(10, 11, 12, 88))
        readability.setColorAt(0.66, QColor(11, 12, 13, 38))
        readability.setColorAt(1.0, QColor(11, 12, 13, 18))
        painter.fillRect(self.rect(), readability)

        vignette = QLinearGradient(
            0.0,
            0.0,
            0.0,
            float(self.height()),
        )
        vignette.setColorAt(0.0, QColor(8, 9, 10, 28))
        vignette.setColorAt(0.58, QColor(8, 9, 10, 0))
        vignette.setColorAt(1.0, QColor(8, 9, 10, 96))
        painter.fillRect(self.rect(), vignette)


class HomeEntryDelegate(QStyledItemDelegate):
    """Paint compact score rows with cached game-style instrument art."""

    def __init__(
        self,
        artwork: InstrumentLaneArtwork,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.artwork = artwork

    @staticmethod
    def _row_fonts(base_font: QFont) -> tuple[QFont, QFont]:
        label_font = QFont(base_font)
        label_font.setBold(True)
        detail_font = QFont(base_font)
        if detail_font.pointSizeF() > 8.5:
            detail_font.setPointSizeF(detail_font.pointSizeF() - 1.0)
        return label_font, detail_font

    @staticmethod
    def _ensemble_text(instrument_count: int) -> str:
        if instrument_count <= 0:
            return ""
        if instrument_count <= BDO_ENSEMBLE_PLAYER_LIMIT:
            return trf("{count} 人", count=instrument_count)
        return trf(
            "上限 {limit} 人",
            limit=BDO_ENSEMBLE_PLAYER_LIMIT,
        )

    def sizeHint(self, option, index) -> QSize:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        label, _separator, _detail = styled.text.partition("\n")
        label_font, detail_font = self._row_fonts(styled.font)
        available_width = self._available_content_width(option)
        title_height = self._title_height(
            label,
            label_font,
            available_width,
        )
        info_height = max(QFontMetrics(detail_font).height() + 2, 20)
        inherited = super().sizeHint(styled, index)
        return QSize(
            inherited.width(),
            max(68, 8 + title_height + 5 + info_height + 8),
        )

    def _available_content_width(self, option) -> int:
        parent = self.parent()
        if isinstance(parent, QListWidget):
            width = parent.viewport().width()
        else:
            width = option.rect.width()
        return max(220, int(width) - 22)

    @staticmethod
    def _title_text_flags() -> int:
        return (
            int(Qt.AlignmentFlag.AlignLeft)
            | int(Qt.AlignmentFlag.AlignTop)
            | int(Qt.TextFlag.TextWordWrap)
            | int(Qt.TextFlag.TextWrapAnywhere)
        )

    @classmethod
    def _title_height(cls, text: str, font: QFont, width: int) -> int:
        metrics = QFontMetrics(font)
        bounds = metrics.boundingRect(
            QRect(0, 0, max(1, int(width)), 10_000),
            cls._title_text_flags(),
            text,
        )
        return max(metrics.height(), bounds.height())

    def paint(self, painter: QPainter, option, index) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        styled.text = ""
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            styled,
            painter,
            styled.widget,
        )

        raw_ids = index.data(HOME_INSTRUMENT_IDS_ROLE)
        instrument_ids = tuple(raw_ids) if isinstance(raw_ids, (list, tuple)) else ()
        max_icons = 3
        visible_ids = instrument_ids[:max_icons]
        overflow = max(0, len(instrument_ids) - len(visible_ids))
        icon_size = 20.0
        icon_gap = 4.0
        icon_slots = len(visible_ids) + int(overflow > 0)
        icon_width = (
            icon_slots * icon_size + max(0, icon_slots - 1) * icon_gap
            if icon_slots
            else 0.0
        )

        content = QRectF(option.rect).adjusted(12.0, 8.0, -10.0, -8.0)
        player_text = self._ensemble_text(len(instrument_ids))
        label_font, detail_font = self._row_fonts(styled.font)
        player_font = detail_font
        painter.save()
        painter.setFont(player_font)
        player_width = (
            float(painter.fontMetrics().horizontalAdvance(player_text)) + 4.0
            if player_text
            else 0.0
        )
        painter.restore()
        right_width = icon_width + player_width
        if icon_slots and player_text:
            right_width += 10.0
        label, _separator, detail = text.partition("\n")
        selected = bool(
            option.state & QStyle.StateFlag.State_Selected
        )

        painter.save()
        painter.setFont(label_font)
        painter.setPen(QColor("#f1e9dc") if selected else QColor("#ddd8cf"))
        label_height = float(self._title_height(
            label,
            label_font,
            round(content.width()),
        ))
        title_rect = QRectF(
            content.left(),
            content.top(),
            content.width(),
            label_height,
        )
        painter.drawText(
            title_rect,
            self._title_text_flags(),
            label,
        )

        painter.setFont(detail_font)
        painter.setPen(QColor("#a99b82") if selected else QColor("#8d8982"))
        detail_metrics = painter.fontMetrics()
        info_top = title_rect.bottom() + 4.0
        info_height = max(
            float(detail_metrics.height() + 2),
            icon_size,
        )
        detail_right = content.right() - right_width - (12.0 if right_width else 0.0)
        detail_rect = QRectF(
            content.left(),
            info_top,
            max(24.0, detail_right - content.left()),
            info_height,
        )
        painter.drawText(
            detail_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                detail,
                Qt.TextElideMode.ElideRight,
                max(0, round(detail_rect.width())),
            ),
        )

        icon_x = content.right() - player_width - icon_width
        if player_text:
            icon_x -= 10.0 if icon_slots else 0.0
        icon_y = info_top + (info_height - icon_size) * 0.5
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for instrument_id in visible_ids:
            target = QRectF(icon_x, icon_y, icon_size, icon_size)
            image = self.artwork.pixmap_for(int(instrument_id))
            if image is not None:
                painter.setOpacity(0.78 if selected else 0.62)
                painter.drawImage(target, image, QRectF(image.rect()))
            else:
                painter.setOpacity(0.74)
                painter.setPen(QColor("#d7b15a"))
                painter.drawText(
                    target,
                    Qt.AlignmentFlag.AlignCenter,
                    f"{int(instrument_id):02X}",
                )
            icon_x += icon_size + icon_gap
        if overflow:
            painter.setOpacity(1.0)
            painter.setPen(QColor("#c7b78f"))
            painter.drawText(
                QRectF(icon_x, icon_y, icon_size, icon_size),
                Qt.AlignmentFlag.AlignCenter,
                f"+{overflow}",
            )
        if player_text:
            painter.setOpacity(1.0)
            painter.setFont(player_font)
            painter.setPen(QColor("#c6a55d") if selected else QColor("#9e8b65"))
            painter.drawText(
                QRectF(
                    content.right() - player_width,
                    info_top,
                    player_width,
                    info_height,
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                player_text,
            )
        painter.restore()


__all__ = [
    "HOME_BACKGROUND_IMAGE",
    "HOME_INSTRUMENT_IDS_ROLE",
    "SHAI_ENSEMBLE_MARK_IMAGE",
    "EnsembleCapacityBadge",
    "HomeBackdrop",
    "HomeEntryDelegate",
    "HomeFooter",
    "HomeHero",
    "HomeIdentityBadge",
    "HomeLibrarySurface",
    "HomeLibraryTabs",
]
