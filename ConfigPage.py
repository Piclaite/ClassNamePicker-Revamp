# ConfigPage.py
import os
from PyQt5 import QtWidgets, QtGui, QtCore
from config_ui import Ui_ConfigMainWindow
from PickerConfigManager import ConfigManager, DataFixDialog
from AutoStartManager import AutoStartManager

class ConfigWindow(QtWidgets.QMainWindow, Ui_ConfigMainWindow):
    closed = QtCore.pyqtSignal(bool)
    # 信号：配置已应用
    config_applied = QtCore.pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle('配置面板')
        
        # 窗口标志
        flags = self.windowFlags()
        self.setWindowFlags(flags & ~QtCore.Qt.WindowMaximizeButtonHint & 
                           ~QtCore.Qt.WindowMinimizeButtonHint | QtCore.Qt.WindowStaysOnTopHint)
        
        # 初始化
        self.load_and_init_ui()
        self._connect_signals()
        self._setup_validators()
        
        # 系统兼容性
        if not AutoStartManager.is_supported():
            self.auto_start_checkbox.setEnabled(False)
    
    def load_and_init_ui(self):
        """合并 load_config 和 init_ui（精简：一次完成）"""
        config = ConfigManager.load_cached()
        name_changes = ConfigManager.load_name_changes()
        
        # 设置控件值
        self.save_checkbox.setChecked(config.get(ConfigManager.KEY_IS_SAVE, False))
        self.speak_checkbox.setChecked(config.get(ConfigManager.KEY_SPEAK_NAME, True))
        self.float_chackbox.setChecked(config.get(ConfigManager.KEY_SHOW_FLOATING, True))
        self.f_autostick_checkBox.setChecked(config.get(ConfigManager.KEY_FLOATING_AUTOSTICK, False))
        self.animation_checkBox.setChecked(config.get(ConfigManager.KEY_ANIMATION, True))
        self.double_floating_w_checkbox.setChecked(config.get(ConfigManager.KEY_DOUBLE_FLOATING_WINDOW, False))

        
        # 高级设置
        self.ani_time_edit.setText(str(config.get(ConfigManager.KEY_ANIMATION_TIME, 0.8)))
        self.floatsize_x_edit.setText(str(config.get(ConfigManager.KEY_FLOATING_X_SIZE, 100)))
        self.floatsize_y_edit.setText(str(config.get(ConfigManager.KEY_FLOATING_Y_SIZE, 100)))
        self.speed_edit.setText(str(config.get(ConfigManager.KEY_SPEAK_SPEED, 170)))
        self.image_path_edit.setText(config.get(ConfigManager.KEY_FLOATING_IMAGE, ''))
        
        # 防重复次数
        total = ConfigManager.get_name_count()
        no_dup = min(config.get(ConfigManager.KEY_NO_DUPLICATE, 0), max(total - 1, 0))
        self.no_duplicate_edit.setText(str(no_dup))
        
        # 多音字
        for i, c in enumerate('abc'):
            field1 = getattr(self, f'{c}1')
            field2 = getattr(self, f'{c}2')
            field1.setText(name_changes.get(f'speak_change_{c}1', ''))
            field2.setText(name_changes.get(f'speak_change_{c}2', ''))
        
        # 自启动状态同步
        actual_state = AutoStartManager.is_enabled()
        cfg_state = config.get(ConfigManager.KEY_AUTO_START, False)
        if actual_state != cfg_state:
            self._show_sync_warning(actual_state, cfg_state)
        self.auto_start_checkbox.setChecked(actual_state)
    
    def _show_sync_warning(self, actual, cfg):
        """自启动状态不一致警告"""
        QtWidgets.QMessageBox.information(
            self, "状态同步",
            f"自启动状态不一致，已自动修正为：{'启用' if actual else '禁用'}"
        )
        config = ConfigManager.load_cached()
        config[ConfigManager.KEY_AUTO_START] = actual
        ConfigManager.save_atomic(config)
    
    def _connect_signals(self):
        """批量连接信号"""
        self.save_button.clicked.connect(self.save_config)
        self.cancel_button.clicked.connect(self.load_and_init_ui)
        self.name_button.clicked.connect(lambda: self.open_file('names'))
        self.gname_button.clicked.connect(lambda: self.open_file('girls'))
        self.update_button.clicked.connect(self.github_menu)
        self.image_button.clicked.connect(self.select_image)
    
    def _setup_validators(self):
        """设置验证器"""
        total_names = ConfigManager.get_name_count()
        max_no_duplicate = max(0, total_names - 1)  # 确保至少为0
        self.ani_time_edit.setValidator(QtGui.QDoubleValidator(0.1, 5.0, 2))
        self.speed_edit.setValidator(QtGui.QIntValidator(50, 300))
        self.floatsize_x_edit.setValidator(QtGui.QIntValidator(50, 750))
        self.floatsize_y_edit.setValidator(QtGui.QIntValidator(50, 750))
        self.no_duplicate_edit.setValidator(QtGui.QIntValidator(0, max_no_duplicate))
        
        # 多音字验证
        for c in 'abc':
            for i in (1, 2):
                field = getattr(self, f'{c}{i}')
                field.setMaxLength(15)
    
    def save_config(self):
        """收集数据并保存"""
        config = ConfigManager.load_cached()
        
        config.update({
            ConfigManager.KEY_IS_SAVE: self.save_checkbox.isChecked(),
            ConfigManager.KEY_SPEAK_NAME: self.speak_checkbox.isChecked(),
            ConfigManager.KEY_SHOW_FLOATING: self.float_chackbox.isChecked(),
            ConfigManager.KEY_FLOATING_AUTOSTICK: self.f_autostick_checkBox.isChecked(),
            ConfigManager.KEY_ANIMATION: self.animation_checkBox.isChecked(),
            ConfigManager.KEY_DOUBLE_FLOATING_WINDOW: self.double_floating_w_checkbox.isChecked(),
            ConfigManager.KEY_ANIMATION_TIME: float(self.ani_time_edit.text()),
            ConfigManager.KEY_FLOATING_X_SIZE: int(self.floatsize_x_edit.text()),
            ConfigManager.KEY_FLOATING_Y_SIZE: int(self.floatsize_y_edit.text()),
            ConfigManager.KEY_SPEAK_SPEED: int(self.speed_edit.text()),
            ConfigManager.KEY_NO_DUPLICATE: int(self.no_duplicate_edit.text()),
            ConfigManager.KEY_FLOATING_IMAGE: self.image_path_edit.text(),
        })
        
        # 自启动处理
        self._handle_auto_start(config)
        
        # 多音字
        self._save_name_changes()
        
        try:
            ConfigManager.save_atomic(config)
        except RuntimeError as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"保存失败: {e}")
            return
        
        # 广播新配置
        self.config_applied.emit(config)
        self.closed.emit(True)
        self.close()
    
    def _handle_auto_start(self, config):
        """自启动设置"""
        old_state = config.get(ConfigManager.KEY_AUTO_START, False)
        new_state = self.auto_start_checkbox.isChecked()
        
        if old_state == new_state:
            return
        
        success, msg = (AutoStartManager.enable() if new_state else AutoStartManager.disable())
        if not success:
            QtWidgets.QMessageBox.warning(self, "自启动失败", msg)
            self.auto_start_checkbox.setChecked(old_state)
            return
        
        config[ConfigManager.KEY_AUTO_START] = new_state
        QtWidgets.QMessageBox.information(self, "提示", msg)
    
    def _save_name_changes(self):
        """保存多音字"""
        changes = {f'{c}{i}': getattr(self, f'{c}{i}').text() 
                  for c in 'abc' for i in (1, 2)}
        ConfigManager.save_name_changes(changes)

    def open_file(self, file_type):
        """打开名单文件前自动检测并修复数据问题"""
        ConfigManager.initialize()
        
        all_names = {line.strip() for line in ConfigManager.NAMES_FILE.read_text(encoding='utf-8').splitlines() 
                    if line.strip() and not line.startswith('#')}
        g_names = {line.strip() for line in ConfigManager.G_NAMES_FILE.read_text(encoding='utf-8').splitlines() 
                if line.strip() and not line.startswith('#')}
        invalid = g_names - all_names
        
        if invalid:
            dialog = DataFixDialog(self, invalid)
            dialog.exec()
            
            clicked = dialog.clickedButton().text()
            
            # 执行修复
            if clicked == "在总名单中添加":
                success, msg = ConfigManager._quick_fix_name_file('add_to_all')
            elif clicked == "从女生名单删除":
                success, msg = ConfigManager._quick_fix_name_file('remove_from_girl')
            else:  # "退出程序"
                return  # 不打开文件
            
            if success:
                QtWidgets.QMessageBox.information(self, "修复完成", msg)
            else:
                QtWidgets.QMessageBox.critical(self, "修复失败", msg)
                return  # 修复失败也不打开文件
        
        # 修复成功后打开文件
        file_path = ConfigManager.G_NAMES_FILE if file_type == 'girls' else ConfigManager.NAMES_FILE
        try:
            os.startfile(str(file_path))
            ConfigManager.open_text = True
            QtCore.QTimer.singleShot(2000, self._update_no_duplicate_validator)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '打开失败', str(e))
    
    def open_file(self, file_type):
        """合并：统一打开文件"""
        ConfigManager.initialize()
        
        if file_type == 'girls':
            # 快速修复女生名单
            ConfigManager._quick_fix_name_file('remove_from_girl')
            file_path = ConfigManager.G_NAMES_FILE
        else:
            ConfigManager._quick_fix_name_file('add_to_all')
            file_path = ConfigManager.NAMES_FILE
        
        try:
            os.startfile(str(file_path))
            ConfigManager.open_text = True
            # 文件编辑后，延迟2秒更新验证器
            QtCore.QTimer.singleShot(2000, self._update_no_duplicate_validator)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '打开失败', str(e))

    def _update_no_duplicate_validator(self):
        """动态更新防重复验证器的上限"""
        total_names = ConfigManager.get_name_count()
        max_no_duplicate = max(0, total_names - 1)
        
        # 重新创建验证器
        self.no_duplicate_edit.setValidator(QtGui.QIntValidator(0, max_no_duplicate))
        
        # 如果当前值超过上限，自动修正
        current_value = int(self.no_duplicate_edit.text() or 0)
        if current_value > max_no_duplicate:
            self.no_duplicate_edit.setText(str(max_no_duplicate))
            QtWidgets.QMessageBox.information(
                self, 
                "值已调整", 
                f"防重复次数已自动调整为最大值: {max_no_duplicate}"
            )
    
    def select_image(self):
        """选择图片文件"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 
            "选择悬浮窗图片", 
            "", 
            "图片文件 (*.png *.jpg *.jpeg *.ico *.bmp)"
        )
        if file_path:
            self.image_path_edit.setText(file_path)

    @staticmethod
    def github_menu():
        import webbrowser
        webbrowser.open("https://github.com/Piclaite/ClassNamePicker-Revamp/releases")