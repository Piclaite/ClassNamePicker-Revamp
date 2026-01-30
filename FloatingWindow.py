# FloatingWindow.py
from PyQt5.QtGui import QFontMetrics, QPainter, QBrush, QColor, QFont, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import QTimer, Qt, QPoint, pyqtSignal, QSize, QEvent
from collections import OrderedDict
import os

class FloatingWindow(QWidget):
    """极简悬浮窗，只负责UI和交互"""
    __slots__ = ('_side', '_autostick', '_is_snapped', '_is_dragging', 
                 '_snap_opacity', '_default_opacity', '_snap_distance',
                 '_parent_geometry_cache', '_image_path', '_pixmap_cache')  # 限制属性
    
    hidden = pyqtSignal()  # 信号：窗口被单击隐藏

    _global_image_cache = OrderedDict()
    _cache_limit = 2  # 最多缓存2张图片
    
    def __init__(self, size_x, size_y, autostick, parent=None, side=None, image_path=None):
        super().__init__(parent)
        
        # 核心属性
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(size_x, size_y)
        
        # 状态管理
        self._side = side
        self._autostick = autostick
        self._is_snapped = False
        self._is_dragging = False
        self._user_hidden = False  #标记是否用户主动点击隐藏
        
        # 视觉参数
        self._snap_opacity = 0.7
        self._default_opacity = 1.0
        self._snap_distance = 20

        # 缓存父窗口几何（用于父窗口不可见时）
        self._parent_geometry_cache = None

        # 加载自定义图片
        self._pixmap = QPixmap()
        self._image_path = None
        self._load_image(image_path)
        
        # 鼠标追踪
        self._drag_start_pos = QPoint()
        self._window_start_pos = QPoint()
    
    @property
    def side(self):
        return self._side
    
    @property
    def is_snapped(self):
        return self._is_snapped

    def showEvent(self, event):
        """显示时自动初始化位置"""
        super().showEvent(event)
        if self._autostick:
            # **关键修改：单悬浮窗每次都重计算，双悬浮窗仅首次**
            if self._side is None or not self._is_snapped:
                QTimer.singleShot(30, self.initialize_position)

    def set_parent_geometry(self, geometry):
        """在父窗口隐藏前缓存其几何信息"""
        self._parent_geometry_cache = geometry
    
    def _load_image(self, image_path):
        """带LRU淘汰的共享图片缓存"""
        if not image_path or not os.path.exists(image_path):
            self._pixmap = QPixmap()
            return
        
        if image_path == self._image_path and self._pixmap is not None:
            return
        
        self._image_path = image_path
        
        # 检查全局缓存
        if image_path in FloatingWindow._global_image_cache:
            self._pixmap = FloatingWindow._global_image_cache[image_path]
            # 移动到最近使用
            FloatingWindow._global_image_cache.move_to_end(image_path)
            return
        
        # 加载新图片
        pixmap = QPixmap()
        if pixmap.load(image_path):
            # 限制缓存大小
            if len(FloatingWindow._global_image_cache) >= self._cache_limit:
                # 淘汰最久未使用的图片
                oldest_path, _ = FloatingWindow._global_image_cache.popitem(last=False)
                print(f"[IMAGE] 缓存淘汰: {oldest_path}")
            
            # 添加到缓存
            FloatingWindow._global_image_cache[image_path] = pixmap
            self._pixmap = pixmap
            print(f"[IMAGE] 加载并缓存: {image_path} ({pixmap.width()}x{pixmap.height()})")
        else:
            self._pixmap = QPixmap()  # 空图片
            
    def initialize_position(self):
        """基于主窗口位置初始化到屏幕边缘"""
        # 判断使用实时几何还是缓存几何
        if self.parent() and self.parent().isVisible():
            parent_geo = self.parent().geometry()
            center_x = parent_geo.center().x()
            screen = QApplication.screenAt(parent_geo.center()).availableGeometry()
        elif self._parent_geometry_cache:
            # 使用缓存的几何信息
            parent_geo = self._parent_geometry_cache
            center_x = parent_geo.center().x()
            screen = QApplication.screenAt(parent_geo.center()).availableGeometry()
        else:
            # fallback: 使用屏幕中心
            screen = QApplication.primaryScreen().availableGeometry()
            center_x = screen.center().x()
        
        # 根据side或主窗口位置决定吸附边
        if self._side == "left":
            target_x = screen.left() - self.width() // 2
        elif self._side == "right":
            target_x = screen.right() - self.width() // 2
        else:
            # **单悬浮窗模式：动态计算并设置side**
            dist_left = abs(center_x - screen.left())
            dist_right = abs(center_x - screen.right())
            if dist_left < dist_right:
                target_x = screen.left() - self.width() // 2
            else:
                target_x = screen.right() - self.width() // 2
        
        target_y = screen.center().y() - self.height() // 2
        self.move(target_x, target_y)
        self._set_snapped(True)
    
    def _set_snapped(self, snapped: bool):
        """内部状态设置"""
        if self._is_snapped != snapped:
            self._is_snapped = snapped
            self.setWindowOpacity(self._snap_opacity if snapped else self._default_opacity)
            self.update()  # 触发重绘
    
    def reset_snapped_state(self):
        """重置吸附状态（主窗口显示时调用）"""
        self._set_snapped(False)
    
    def set_autostick(self, enabled: bool):
        """动态更新自动吸附状态"""
        self._autostick = enabled
        if enabled and not self._is_snapped:
            self.initialize_position()
    
    def paintEvent(self, event):
        """绘制悬浮窗"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 如果图片有效，绘制图片；否则绘制文字
        if not self._pixmap.isNull():
            # 计算缩放比例，保持宽高比
            scaled_pixmap = self._pixmap.scaled(
                self.size() - QSize(20, 20),  # 留边距
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # 居中绘制
            x = (self.width() - scaled_pixmap.width()) // 2
            y = (self.height() - scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, scaled_pixmap)
        else:
            # 回退到文字模式
            brush = QBrush(QColor(180, 180, 180, 200))
            painter.setBrush(brush)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(0, 0, self.width(), self.height(), 20, 20)
            self._snap_distance = int(self.width() * 0.4)
            painter.setPen(QColor(20, 20, 20))
            text = "点点\n名名" if self._is_snapped else "随机\n点名"
            font_size = self._calc_optimal_font_size(text)
            font = QFont("黑体", font_size, QFont.Bold)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, text)
    
    def _calc_optimal_font_size(self,text: str) -> int:
        """计算最佳字体大小"""
        base_size = int(self.height() * 0.4)
        for size in range(base_size, 8, -1):
            test_font = QFont("黑体", size, QFont.Bold)
            metrics = QFontMetrics(test_font)
            if metrics.boundingRect(self.rect(), Qt.AlignCenter, text).width() <= self.width() * 0.8:
                return size
        return 8
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._snap_distance = int(self.width() * 0.4)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPos()
            self._window_start_pos = self.pos()
            self._is_dragging = False
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = event.globalPos() - self._drag_start_pos
            if delta.manhattanLength() > 3:  # 实际移动才认为是拖动
                self._is_dragging = True
                self.move(self._window_start_pos + delta)
                self._snap_to_edge()
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._is_dragging:
                # 单击事件：隐藏并通知父窗口
                self._user_hidden = True
                self.hide()
                self.hidden.emit()
                
            else:
                # 拖动结束：最终吸附检测
                self._snap_to_edge(final=True)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def _snap_to_edge(self, final=False):
        """吸附逻辑：final=True表示拖动结束"""
        if not self._autostick and not final:
            return
        
        screen = QApplication.primaryScreen().availableGeometry()
        center = self.geometry().center()
        
        distances = {
            "left": abs(center.x() - screen.left()),
            "right": abs(center.x() - screen.right())
        }
        nearest = min(distances, key=distances.get)
        
        should_snap = self._autostick or distances[nearest] < self._snap_distance
        
        if should_snap:
            target_x = screen.left() - self.width() // 2 if nearest == "left" else screen.right() - self.width() // 2
            self.move(target_x, self.y())
        
        self._set_snapped(should_snap)

    def hideEvent(self, event):
        """阻止非用户触发的隐藏事件"""
        if self._user_hidden:
            # 用户主动隐藏，允许执行
            self._user_hidden = False  # 重置标志
            super().hideEvent(event)
            print(f"[FLOAT] 用户主动隐藏窗口")
        else:
            #系统强制隐藏（如"显示桌面"），阻止并自动恢复
            event.ignore()
            print(f"[FLOAT] 阻止系统强制隐藏，准备恢复...")
            QTimer.singleShot(50, self._force_show)  # 延迟50ms后强制显示

    def _force_show(self):
        """强制将窗口置顶显示"""
        if self.parent() and self.parent().isVisible():
            print("[FLOAT] 父程序可见，不恢复悬浮窗")
            return
        
        self.show()
        self.raise_()
        self.activateWindow()
        print(f"[FLOAT] 窗口已强制恢复显示")

    def changeEvent(self, event):
        """监听窗口状态变化，防止被最小化"""
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                # 如果被最小化，立即恢复
                self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
                self.show()
                self.raise_()
                print(f"[FLOAT] 阻止最小化并恢复")
        super().changeEvent(event)

    