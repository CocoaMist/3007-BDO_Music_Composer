"""Reserved network-room UI for cross-party performance coordination."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QDateTime, QRegularExpression, QTimer, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.ui.i18n import tr, trf


DEFAULT_ROOM_PORT = 31_307


@dataclass(frozen=True, slots=True)
class NetworkRoomDraft:
    """Immutable future hand-off for an asynchronous room transport."""

    role: str
    address: str
    port: int
    pin: str
    countdown_seconds: float
    global_bpm: int
    meter: int

    @property
    def valid_endpoint(self) -> bool:
        return bool(self.address.strip()) and 1 <= self.port <= 65_535


class MultiplayerSyncDialog(QDialog):
    """Room-shaped design preview; intentionally performs no network I/O."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        global_bpm: int,
        meter: int,
    ) -> None:
        super().__init__(parent)
        self.global_bpm = max(1, int(global_bpm))
        self.meter = max(1, int(meter))
        self.setObjectName("MultiplayerSyncDialog")
        self.setWindowTitle(tr("多人同步器"))
        self.setModal(True)
        self.setMinimumSize(760, 640)
        self.resize(860, 680)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        title = QLabel(tr("网络合奏房间"))
        title.setObjectName("PanelTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        layout.addLayout(heading)

        scope = QLabel(
            tr(
                "用于协调黑色沙漠双队伍或 FF14 合奏的共同开始时刻；不控制游戏按键。"
            )
        )
        scope.setObjectName("Muted")
        scope.setWordWrap(True)
        layout.addWidget(scope)

        summary_card = QFrame()
        summary_card.setObjectName("RoomSummaryCard")
        summary_layout = QGridLayout(summary_card)
        summary_layout.setContentsMargins(16, 11, 16, 11)
        summary_layout.setHorizontalSpacing(28)
        summary_layout.setVerticalSpacing(3)
        time_label = QLabel(tr("北京时间"))
        time_label.setObjectName("RoomMetricLabel")
        summary_layout.addWidget(time_label, 0, 0)
        self.beijing_time = QLabel()
        self.beijing_time.setObjectName("RoomMetricValue")
        self.beijing_time.setProperty("i18nSkip", True)
        summary_layout.addWidget(self.beijing_time, 1, 0)
        tempo_label = QLabel(tr("工程节拍"))
        tempo_label.setObjectName("RoomMetricLabel")
        summary_layout.addWidget(tempo_label, 0, 1)
        self.tempo_value = QLabel(
            trf("{bpm} BPM · {meter}/4", bpm=self.global_bpm, meter=self.meter)
        )
        self.tempo_value.setObjectName("RoomMetricValue")
        self.tempo_value.setProperty("i18nSkip", True)
        summary_layout.addWidget(self.tempo_value, 1, 1)
        state_label = QLabel(tr("房间状态"))
        state_label.setObjectName("RoomMetricLabel")
        summary_layout.addWidget(state_label, 0, 2)
        self.room_state = QLabel(tr("未连接 · 功能预留"))
        self.room_state.setObjectName("RoomStateValue")
        summary_layout.addWidget(self.room_state, 1, 2)
        summary_layout.setColumnStretch(0, 3)
        summary_layout.setColumnStretch(1, 2)
        summary_layout.setColumnStretch(2, 2)
        layout.addWidget(summary_card)

        connection_card = QFrame()
        self.connection_card = connection_card
        connection_card.setObjectName("RoomConnectionCard")
        connection_layout = QVBoxLayout(connection_card)
        connection_layout.setContentsMargins(16, 12, 16, 14)
        connection_layout.setSpacing(8)
        connection_title = QLabel(tr("连接设置"))
        connection_title.setObjectName("SectionLabel")
        connection_layout.addWidget(connection_title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(7)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.room_role = QComboBox()
        self.room_role.setObjectName("NetworkRoomRole")
        self.room_role.setMinimumWidth(360)
        self.room_role.addItem(tr("创建房间"), "host")
        self.room_role.addItem(tr("加入房间"), "guest")
        self.ip_address = QLineEdit("127.0.0.1")
        self.ip_address.setObjectName("NetworkRoomAddress")
        self.ip_address.setMinimumWidth(360)
        self.ip_address.setPlaceholderText(tr("IP 地址或主机名"))
        self.port = QSpinBox()
        self.port.setObjectName("NetworkRoomPort")
        self.port.setMinimumWidth(160)
        self.port.setRange(1, 65_535)
        self.port.setValue(DEFAULT_ROOM_PORT)
        self.pin = QLineEdit()
        self.pin.setObjectName("NetworkRoomPin")
        self.pin.setMinimumWidth(240)
        self.pin.setMaxLength(6)
        self.pin.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.pin.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self.pin)
        )
        self.pin.setPlaceholderText(tr("6 位数字 PIN"))
        self.countdown_seconds = QDoubleSpinBox()
        self.countdown_seconds.setObjectName("NetworkRoomCountdown")
        self.countdown_seconds.setMinimumWidth(160)
        self.countdown_seconds.setRange(3.0, 60.0)
        self.countdown_seconds.setDecimals(1)
        self.countdown_seconds.setSingleStep(0.5)
        self.countdown_seconds.setValue(10.0)
        self.countdown_seconds.setSuffix(tr(" 秒"))
        form.addRow(tr("方式"), self.room_role)
        form.addRow(tr("IP 地址"), self.ip_address)
        form.addRow(tr("端口号"), self.port)
        form.addRow(tr("PIN 码"), self.pin)
        form.addRow(tr("倒计时时间"), self.countdown_seconds)
        connection_layout.addLayout(form)
        layout.addWidget(connection_card)

        protocol_card = QFrame()
        self.protocol_card = protocol_card
        protocol_card.setObjectName("RoomProtocolCard")
        protocol_layout = QVBoxLayout(protocol_card)
        protocol_layout.setContentsMargins(16, 10, 16, 11)
        protocol_layout.setSpacing(5)
        protocol_heading = QHBoxLayout()
        protocol_title = QLabel(tr("同步设计"))
        protocol_title.setObjectName("SectionLabel")
        protocol_heading.addWidget(protocol_title)
        protocol_heading.addStretch(1)
        self.network_quality = QLabel(tr("延迟 -- ms · 偏移 -- ms · 抖动 -- ms"))
        self.network_quality.setObjectName("RoomNetworkQuality")
        protocol_heading.addWidget(self.network_quality)
        protocol_layout.addLayout(protocol_heading)
        protocol_detail = QLabel(
            tr(
                "房主广播未来的绝对开始时刻；成员先估计时钟偏移与往返延迟，"
                "再用本机单调时钟倒计时。PIN 只用于房间验证，不等同于加密。"
            )
        )
        protocol_detail.setObjectName("Muted")
        protocol_detail.setWordWrap(True)
        protocol_layout.addWidget(protocol_detail)
        layout.addWidget(protocol_card)

        member_heading = QHBoxLayout()
        member_title = QLabel(tr("房间成员"))
        member_title.setObjectName("SectionLabel")
        member_heading.addWidget(member_title)
        member_heading.addStretch(1)
        self.member_count = QLabel(tr("0 人在线"))
        self.member_count.setObjectName("Muted")
        member_heading.addWidget(self.member_count)
        layout.addLayout(member_heading)

        self.member_list = QListWidget()
        self.member_list.setObjectName("NetworkRoomMembers")
        for text in (
            tr("A 队 · 队长 · 等待连接"),
            tr("B 队 · 队长 · 等待连接"),
            tr("成员加入后显示队伍、角色、就绪状态和延迟"),
        ):
            item = QListWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.member_list.addItem(item)
        self.member_list.setMinimumHeight(120)
        layout.addWidget(self.member_list, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.create_button = buttons.addButton(
            tr("创建房间"), QDialogButtonBox.ActionRole
        )
        self.join_button = buttons.addButton(
            tr("加入房间"), QDialogButtonBox.ActionRole
        )
        self.create_button.setEnabled(False)
        self.join_button.setEnabled(False)
        self.create_button.setToolTip(tr("网络协议尚未启用；当前仅完成房间界面和数据边界"))
        self.join_button.setToolTip(self.create_button.toolTip())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(250)
        self.clock_timer.timeout.connect(self._refresh_beijing_time)
        self.clock_timer.start()
        self._refresh_beijing_time()

    def room_draft(self) -> NetworkRoomDraft:
        return NetworkRoomDraft(
            role=str(self.room_role.currentData() or "guest"),
            address=self.ip_address.text().strip(),
            port=self.port.value(),
            pin=self.pin.text(),
            countdown_seconds=self.countdown_seconds.value(),
            global_bpm=self.global_bpm,
            meter=self.meter,
        )

    def _refresh_beijing_time(self) -> None:
        utc = QDateTime.currentDateTimeUtc()
        self.beijing_time.setText(
            utc.addSecs(8 * 60 * 60).toString("yyyy-MM-dd HH:mm:ss")
        )


__all__ = ["DEFAULT_ROOM_PORT", "MultiplayerSyncDialog", "NetworkRoomDraft"]
