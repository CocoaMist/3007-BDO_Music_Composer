"""Automated baseline audit for QWidget accessibility contracts."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QLineEdit, QWidget


@dataclass(frozen=True, slots=True)
class AccessibilityFinding:
    code: str
    object_name: str
    widget_type: str


def audit_widget_tree(root: QWidget) -> tuple[AccessibilityFinding, ...]:
    """Find visible interactive widgets lacking names or keyboard focus."""

    interactive_types = (QAbstractButton, QAbstractSlider, QLineEdit)
    findings: list[AccessibilityFinding] = []
    widgets = (root, *root.findChildren(QWidget))
    for widget in widgets:
        if not widget.isVisibleTo(root) or not widget.isEnabled():
            continue
        if not isinstance(widget, interactive_types):
            continue
        identity = widget.objectName() or "<unnamed>"
        label = widget.accessibleName().strip()
        if not label and isinstance(widget, QAbstractButton):
            label = widget.text().replace("&", "").strip()
        if not label and isinstance(widget, QLineEdit):
            label = widget.placeholderText().strip()
        if not label:
            findings.append(AccessibilityFinding(
                "missing-accessible-name", identity, type(widget).__name__
            ))
        if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
            findings.append(AccessibilityFinding(
                "not-keyboard-focusable", identity, type(widget).__name__
            ))
    return tuple(findings)


__all__ = ["AccessibilityFinding", "audit_widget_tree"]
