# FloatingWindowManagerPy.py
from PyQt5.QtCore import QObject, QSize, QTimer, pyqtSignal
from FloatingWindow import FloatingWindow
from PickerConfigManager import ConfigManager

class FloatingWindowManager(QObject):
    """悬浮窗生命周期统一管理器"""
    
    # 信号：悬浮窗被单击隐藏时通知主窗口
    windowHidden = pyqtSignal()

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self._config_revision = -1  # 初始化时标记为无效版本
        self.parent = parent_window
        self._windows = []  # 存储所有悬浮窗实例
        self._config_snapshot = {}  # 配置快照，用于对比变更
    
    def initialize(self):
        """初始化：根据当前配置创建悬浮窗"""
        config = ConfigManager.load_cached()
        self._sync_configuration(config, force_create=True)
    
    def _sync_configuration(self, config: dict, force_create=False):
        """
        核心方法：根据配置同步悬浮窗状态
        - 分析配置变更，智能决定重建或更新
        - force_create: 强制重建（用于初始化）
        """
        # 1. 快速路径：版本未变且非强制
        current_revision = config.get(ConfigManager.KEY_INTERNAL_REVISION, 0)
        if not force_create and current_revision == self._config_revision:
            return  # 配置完全相同，直接跳过
        
        print(f"[FLOAT] 配置变更检测: 旧版本={self._config_revision}, 新版本={current_revision}")

        # 更新版本号
        self._config_revision = current_revision
        
        # 2.提取关键配置项
        current_cfg = {
            'show': config.get(ConfigManager.KEY_SHOW_FLOATING, True),
            'double': config.get(ConfigManager.KEY_DOUBLE_FLOATING_WINDOW, False),
            'autostick': config.get(ConfigManager.KEY_FLOATING_AUTOSTICK, False),
            'size_x': config.get(ConfigManager.KEY_FLOATING_X_SIZE, 100),
            'size_y': config.get(ConfigManager.KEY_FLOATING_Y_SIZE, 100),
            'image_path': config.get(ConfigManager.KEY_FLOATING_IMAGE, None),
        }

        # 3. 决策：重建 vs 更新
        if not current_cfg['show']:
            self._destroy_all()
        elif self._needs_rebuild(current_cfg):
            self._rebuild_windows(current_cfg)
        else:
            self._update_windows(current_cfg)   # 仅更新属性

        # 更新快照
        self._config_snapshot = current_cfg.copy()
    
    def _needs_rebuild(self, cfg: dict) -> bool:
        """判断是否需要重建悬浮窗实例"""
        rebuild_flags = [
            len(self._windows) != (2 if cfg['double'] else 1),
            cfg['double'] and [w.side for w in self._windows] != ["left", "right"],
            self._config_snapshot.get('image_path') != cfg['image_path']  # 仅图片路径变化重建
        ]
        return any(rebuild_flags)
    
    def _rebuild_windows(self, cfg: dict):
        """重建所有悬浮窗实例"""
        print(f"[FLOAT] 重建悬浮窗: 双窗={cfg['double']}, 吸附={cfg['autostick']}")
        
        # 安全销毁旧实例
        self._destroy_all()
        
        # 批量创建新实例
        sides = ["left", "right"] if cfg['double'] else [None]
        for side in sides:
            window = FloatingWindow(
                size_x=cfg['size_x'],
                size_y=cfg['size_y'],
                autostick=cfg['autostick'],
                parent=self.parent,
                side=side if cfg['autostick'] else None,
                image_path=cfg['image_path']
            )
            # 连接隐藏信号
            window.hidden.connect(self._on_window_hidden)
            self._windows.append(window)
            
            # 延迟初始化位置，确保窗口系统已就绪
            if cfg['autostick']:
                QTimer.singleShot(50, window.initialize_position)

    def _update_windows(self, cfg: dict):
        """仅更新现有实例属性"""
        print(f"[FLOAT] 更新悬浮窗属性: 尺寸=({cfg['size_x']},{cfg['size_y']}), 吸附={cfg['autostick']}, 图片={cfg['image_path']}")
        for win in self._windows:
            if win.size() != QSize(cfg['size_x'], cfg['size_y']):
                win.setFixedSize(cfg['size_x'], cfg['size_y'])
                win.update()
            win.set_autostick(cfg['autostick'])
            win._load_image(cfg['image_path'])
    
    def _destroy_all(self):
        """销毁所有实例"""
        for win in self._windows:
            win.close()
            win.deleteLater()
        self._windows.clear()
    
    def show_all(self, parent_geometry=None):
        """批量显示所有悬浮窗"""
        if not self._windows:
            return
        
        for win in self._windows:
            # **传递父窗口几何信息**
            if parent_geometry is not None:
                win.set_parent_geometry(parent_geometry)
            win.show()
            win.raise_()
    
    def hide_all(self):
        """批量隐藏所有悬浮窗"""
        print('[FLOAT] Hide')
        for win in self._windows:
            win._user_hidden = True
            win.hide()
    
    def reset_positions(self):
        """重置所有窗口吸附状态"""
        for win in self._windows:
            win.reset_snapped_state()
    
    def get_window_states(self) -> dict:
        """获取当前悬浮窗状态（用于配置保存）"""
        return {
            ConfigManager.KEY_SHOW_FLOATING: len(self._windows) > 0,
            ConfigManager.KEY_DOUBLE_FLOATING_WINDOW: len(self._windows) == 2,
        }
    
    def _on_window_hidden(self):
        """悬浮窗被单击隐藏时的回调"""
        # 重置所有窗口的用户隐藏标志
        self.windowHidden.emit()
        self.hide_all()
        for win in self._windows:
            win._user_hidden = False
        # 更新配置
        config = ConfigManager.load_cached()
        config[ConfigManager.KEY_FLOATING_MODE] = "window"
        try:
            ConfigManager.save_atomic(config)
        except RuntimeError as e:
            print(f"[FLOAT] 配置保存失败: {e}")

    def force_sync(self):
        """外部调用的强制同步入口"""
        print("[FLOAT] 收到强制同步指令")
        self._config_revision = -1  # 重置版本号，下次同步必定触发
        config = ConfigManager.load_cached()
        self._sync_configuration(config, force_create=True)

    def soft_sync(self, config: dict = None):
        """悬浮窗同步（用于高频事件，如窗口移动）"""
        if config is None:
            config = ConfigManager.load_cached()
        
        current_cfg = {
            'show': config.get(ConfigManager.KEY_SHOW_FLOATING, True),
            'size_x': config.get(ConfigManager.KEY_FLOATING_X_SIZE, 100),
            'size_y': config.get(ConfigManager.KEY_FLOATING_Y_SIZE, 100),
        }
        
        if self._windows and not self._needs_rebuild(current_cfg):
            for win in self._windows:
                win.setFixedSize(current_cfg['size_x'], current_cfg['size_y'])

    def get_window_count(self) -> int:
        return len(self._windows)