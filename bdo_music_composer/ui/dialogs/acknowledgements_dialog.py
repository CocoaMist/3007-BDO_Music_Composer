"""Focused credits and license dialog for the desktop application.

The curated credit data lives in :mod:`third_party_credits`; this module owns
only its Qt presentation.  Keeping both concerns outside the main window makes
the acknowledgements surface independently testable and prevents license UI
changes from growing the application orchestrator.
"""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.app.application_metadata import GITHUB_REPOSITORY_URL
from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.core.third_party_credits import (
    BASIC_PITCH_LICENSE_URL,
    BASIC_PITCH_MODEL_URL,
    BASIC_PITCH_NOTICE_URL,
    CREDIT_ENTRIES,
    CREDIT_SECTION_SOURCES,
    RESEARCH_CITATIONS,
)


THIRD_PARTY_NOTICES_URL = (
    f"{GITHUB_REPOSITORY_URL}/blob/master/THIRD_PARTY_NOTICES.md"
)


def _credits_html(*, dark_theme: bool) -> str:
    """Build the translated, escaped HTML used by the credits browser."""

    body_color = "#d8d3cc" if dark_theme else "#45413d"
    heading_color = "#f0c66f" if dark_theme else "#8a5a00"
    section_sources = dict(CREDIT_SECTION_SOURCES)
    credit_sections: list[str] = []
    for section_key, _source in CREDIT_SECTION_SOURCES:
        rows = []
        for entry in CREDIT_ENTRIES:
            if entry.section != section_key:
                continue
            rows.append(
                '<p class="credit">'
                f"<b>{escape(entry.name)}</b><br>"
                f"{escape(tr('许可证'))}: "
                f"{escape(tr(entry.license_label))}<br>"
                f'<a href="{escape(entry.github_url)}">'
                f"{escape(entry.github_url)}</a>"
                "</p>"
            )
        credit_sections.append(
            f"<h2>{escape(tr(section_sources[section_key]))}</h2>"
            + "".join(rows)
        )

    citation_rows = []
    for citation in RESEARCH_CITATIONS:
        citation_rows.append(
            '<p class="credit">'
            f"<b>{escape(citation.name)}</b><br>"
            f"{escape(citation.citation)}<br>"
            f'<a href="{escape(citation.github_url)}">'
            f"{escape(citation.github_url)}</a><br>"
            f'<a href="{escape(citation.publication_url)}">'
            f"{escape(tr('论文'))}: {escape(citation.publication_url)}</a>"
            "</p>"
        )

    return f"""
        <style>
            body {{ color: {body_color}; font-family: "Microsoft YaHei UI"; font-size: 12px; margin: 0; }}
            h2 {{ color: {heading_color}; font-size: 16px; margin-top: 18px; margin-bottom: 7px; }}
            p {{ margin: 7px 0; line-height: 150%; }}
            b {{ color: {heading_color}; }}
            a {{ color: #70aee8; text-decoration: none; }}
            .credit {{ margin-bottom: 11px; }}
        </style>
        <h2>{escape(tr("Basic Pitch 代码与模型许可"))}</h2>
        <p>{escape(tr("Basic Pitch 0.4.0 的代码、随包 nmp.onnx、LICENSE 与 NOTICE 位于同一官方发行树；未发现模型目录中的单独限制性许可证。按 Apache-2.0 再分发时必须附带 LICENSE 并保留 NOTICE。"))}</p>
        <p>
          <a href="{escape(BASIC_PITCH_MODEL_URL)}">nmp.onnx · GitHub</a><br>
          <a href="{escape(BASIC_PITCH_LICENSE_URL)}">LICENSE · GitHub</a><br>
          <a href="{escape(BASIC_PITCH_NOTICE_URL)}">NOTICE · GitHub</a>
        </p>

        {''.join(credit_sections)}

        <h2>{escape(tr("论文引用"))}</h2>
        {''.join(citation_rows)}

        <h2>{escape(tr("社区、测试与音乐交流"))}</h2>
        <p>• <b>CN Server · Rainbow Club / 彩虹乐队</b></p>
        <p>• <b>{escape(tr("开源维护者、文档作者、测试者与社区玩家"))}</b></p>
        <p>{escape(tr("本程序未内置 OpenAI API 或云端模型；OpenAI 仅列为开发协作致谢。"))}</p>

        <h2>{escape(tr("完整许可清单"))}</h2>
        <p>{escape(tr("这里是便于阅读的致谢；每次构建仍会生成并随 EXE 嵌入完整的依赖、许可证、NOTICE 与二进制哈希清单。"))}</p>
        <p><a href="{THIRD_PARTY_NOTICES_URL}">{THIRD_PARTY_NOTICES_URL}</a></p>
    """


class AcknowledgementsDialog(QDialog):
    """Display curated credits without owning their source data."""

    def __init__(
        self,
        *,
        dark_theme: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("致谢"))
        self.resize(860, 640)
        self.setMinimumSize(700, 520)
        self.setObjectName("ThanksDialog")
        self.setProperty("uiSurface", "utility")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("ThanksHeader")
        header.setProperty("uiRole", "dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 13)
        header_layout.setSpacing(2)
        title = QLabel(tr("致谢"))
        title.setObjectName("ThanksTitle")
        title.setProperty("uiRole", "dialogTitle")
        header_layout.addWidget(title)
        subtitle = QLabel(tr("感谢以下项目、作者与社区。"))
        subtitle.setObjectName("ThanksSubtitle")
        subtitle.setProperty("uiRole", "dialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        text_panel = QFrame()
        text_panel.setObjectName("ThanksTextPanel")
        text_panel.setProperty("uiRole", "dialogBody")
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(24, 16, 24, 18)
        text_layout.setSpacing(10)
        text_title = QLabel(tr("项目、作者与社区"))
        text_title.setObjectName("ThanksSectionLabel")
        text_title.setProperty("uiRole", "sectionTitle")
        text_layout.addWidget(text_title)

        self.credits_browser = QTextBrowser()
        self.credits_browser.setObjectName("ThanksText")
        self.credits_browser.setReadOnly(True)
        self.credits_browser.setOpenExternalLinks(True)
        self.credits_browser.setHtml(_credits_html(dark_theme=dark_theme))
        text_layout.addWidget(self.credits_browser, stretch=1)
        layout.addWidget(text_panel, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.setObjectName("ThanksButtons")
        buttons.setProperty("uiRole", "dialogButtonRow")
        copy_button = buttons.addButton(
            tr("复制致谢名单"),
            QDialogButtonBox.ActionRole,
        )
        copy_button.setProperty("kind", "secondary")
        copy_button.setToolTip(tr("复制为纯文本，便于放入项目说明或发布页面"))
        copy_button.clicked.connect(self._copy_credits)
        buttons.button(QDialogButtonBox.Ok).setText(tr("关闭"))
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        buttons.accepted.connect(self.accept)

        footer = QFrame()
        footer.setObjectName("ThanksFooter")
        footer.setProperty("uiRole", "dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 10, 24, 10)
        footer_layout.setSpacing(0)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)

    def _copy_credits(self) -> None:
        QApplication.clipboard().setText(
            self.credits_browser.toPlainText().strip()
        )


__all__ = ["AcknowledgementsDialog", "THIRD_PARTY_NOTICES_URL"]
