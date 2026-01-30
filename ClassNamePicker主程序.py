# ClassNamePicker 主程序
import sys
import random
import time
from pathlib import Path
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QPoint, QRect, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5 import QtCore
from typing import Generator
from StudentModels import Student, Gender, StudentPool
from SingleInstanceManager import SingleInstanceManager
from FloatingWindowManagerPy import FloatingWindowManager
from ui import Ui_MainWindow
from PickerConfigManager import ConfigManager, DataFixDialog
from AutoStartManager import AutoStartManager
from version import APP_VERSION, APP_VERSION_TIME, APP_VERSION_INFO

# 常量集中管理
ANIMATION_FPS = 50  # 帧率50fps
TIMER_INTERVAL = 100  # 计时器间隔(ms)
CONFIG_SAVE_DELAY = 300  # 配置保存延迟(ms)

class SaveDebouncer:
    """智能防抖定时器：批量合并+防刷写保护"""
    
    def __init__(self, delay: int = 300, min_interval: int = 1000, callback=None):
        """
        delay: 防抖延迟时间（ms）
        min_interval: 最小写入间隔（ms）
        callback: 超时后回调函数
        """
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._on_timeout)
        
        self.delay = delay
        self.min_interval = min_interval
        self.callback = callback
        
        self._last_flush_time = time.time() * 1000  # 毫秒时间戳
        self._is_pending = False  # 是否有待执行的保存
    
    def start(self, delay: int = None):
        """启动防抖定时器"""
        if delay is None:
            delay = self.delay
        
        # 如果已有待执行请求，重置定时器
        if self._is_pending:
            self.timer.stop()
        
        self.timer.start(delay)
        self._is_pending = True
    
    def stop(self):
        """停止定时器"""
        self.timer.stop()
        self._is_pending = False
    
    def isActive(self) -> bool:
        """检查是否激活"""
        return self.timer.isActive()
    
    def _on_timeout(self):
        """定时器超时处理：检查最小间隔是否满足"""
        self._is_pending = False
        now = time.time() * 1000
        
        # 检查距离上次写入是否超过最小间隔
        if now - self._last_flush_time < self.min_interval:
            # 不满足间隔，延迟到满足条件时再执行
            remaining = self.min_interval - (now - self._last_flush_time)
            self.timer.start(int(remaining))
            self._is_pending = True
            print(f"[SAVE] 防抖保护：剩余{remaining:.0f}ms后允许写入")
            return
        
        # 满足条件，执行回调
        if self.callback:
            self._last_flush_time = now
            self.callback()

class SpeechThread(QThread):
    """
    异步语音播报线程（比较垃圾，但是能用）
    用于在后台线程中调用 pyttsx3 播报姓名，避免阻塞主界面。
    播报结束后通过 finished 信号通知主线程。
    """
    finished = pyqtSignal()
    
    def __init__(self, text, speak_speed=170):
        super().__init__()
        self.text = text
        self.speak_speed = speak_speed

    def run(self):
        try:
            import pyttsx3
            engine = pyttsx3.init(driverName='sapi5')
            engine.setProperty('rate', self.speak_speed)
            engine.say(self.text)
            engine.runAndWait()
        except Exception as e:
            print(f"语音错误: {e}")
        finally:
            self.finished.emit()

class PickName(QMainWindow, Ui_MainWindow, QWidget):
    def __init__(self):
        super().__init__()  # 初始化QMainWindow
        self.setupUi(self)  # 使用UI设置界面
        self.original_status_bar = self.statusBar()
        # 配置窗口实例
        self.config_window = None
        # 语音线程实例
        self.speech_thread = None

        # 版本信息
        self.version = APP_VERSION
        self.version_time = APP_VERSION_TIME
        self.version_info = APP_VERSION_INFO

        # 核心数据模型
        self.student_pool: StudentPool = None
        self.current_gender = Gender.UNKNOWN

        # 动画相关
        self.animation_timer = QTimer()
        self.animation_timer.setInterval(1000 // ANIMATION_FPS)
        self.animation_timer.timeout.connect(self._update_animation)
        self.animation_start_time = 0
        self.animation_idx_pool = []

        # 背书计时器
        self.recite_timer = QTimer()
        self.recite_timer.setInterval(TIMER_INTERVAL)
        self.recite_timer.timeout.connect(self._update_recite_timer)
        self.recite_elapsed = 0.0

        # 计时状态
        self._recite_state = {
            'mode': 'countdown',  # 模式：'countdown' 或 'elapsed'
            'target_time': 0,     # 倒计时目标秒数
            'start_time': 0,      # 开始时间戳
            'elapsed': 0,         # 已用时间
        }

        self._debounce_timer = SaveDebouncer(
            delay=CONFIG_SAVE_DELAY,  # 300ms
            min_interval=1000,         # 最小1秒写入间隔
            callback=self._flush_all_saves
        )
        self._save_queue = set()        # 保存原因

        # 功能状态变量
        self.pick_balanced = False      # 是否平衡抽取
        self.animation_time = 0.8       # 动画时长
        self.picked_count = 0           # 已抽取次数
        self.floating_x_size = 100      # 悬浮窗宽度
        self.floating_y_size = 100      # 悬浮窗高度
        self.f_autostick = False        # 悬浮窗自动吸附
        self.speak_speed = 170          # 语音播报速度
        self.is_running = False         # 是否正在运行
        self.is_animation_enabled = True # 是否启用动画
        self.is_recite_mode = False      # 是否背书计时模式
        self.is_saving_results = False   # 是否保存抽取结果
        self.is_speech_enabled = True    # 是否启用语音播报
        self.is_floating_visible = True  # 是否显示悬浮窗
        self.no_duplicate = 0            # 几次内不重复抽取，0表示无限制
        self.no_duplicate_cache = 0      # 缓存的防重复值（用于切换时恢复）

        self._data_issues = {'is_valid': True, 'invalid_female': set()} # 数据问题状态

        # 窗口拖动状态跟踪
        self._is_moving = False             # 窗口是否在移动中
        self._drag_start_pos = None         # 鼠标按下时的全局位置
        self._drag_window_start_pos = None  # 窗口起始位置
        self._last_valid_position = None    # 最后有效位置
        self._is_internal_move = False      # 是否内部调整

        #self.setupUi(self)  # 使用UI设置界面
        self.setWindowTitle(
            "课堂随机点名{}- ClassNamePicker - {}({})".format(self.version_info, self.version, self.version_time))
        self.head_label.setText("课堂随机点名{}- ClassNamePicker - {}({})".format(self.version_info, self.version, self.version_time))
        # 禁用最大化按钮
        #self.setWindowFlags(self.windowFlags() & ~Qt.WindowMaximizeButtonHint)
        # 禁用最小化按钮
        #self.setWindowFlags(self.windowFlags() & ~Qt.WindowMinimizeButtonHint)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        # 启用无框窗口
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        # 绑定控件信号
        #self.reset_button.setEnabled(True)
        self.reset_button.clicked.connect(self._reset_with_confirm)                     # 重置按钮
        self.pick_time_checkbox.stateChanged.connect(self.set_recite)                   # 背书模式
        self.timer_label.hide()                                                     # 初始隐藏计时标签
        self.pick_again_checkbox.stateChanged.connect(self._on_toggle_repeat)           # 允许重复抽取
        self.pick_name_button.clicked.connect(self._pick_name)                          # 抽取按钮
        self.b_names_pick_checkbox.stateChanged.connect(self._on_gender_filter_changed) # 只抽男生
        self.g_names_pick_checkbox.stateChanged.connect(self._on_gender_filter_changed) # 只抽女生
        self.gender_checkBox.stateChanged.connect(self.set_gender_ui_widget_visible)    # 性别选项
        self.exit_button.clicked.connect(self._perform_full_exit)                       # 退出按钮
        self.close_button.clicked.connect(self.close)                                   # 关闭窗口按钮
        self.config_button.clicked.connect(self.open_config_page)                       # 配置按钮

        # 链接 Action
        '''self.about_action.triggered.connect(self.about_menu)                            # 关于菜单
        self.github_action.triggered.connect(self.github_menu)                          # GitHub菜单
        self.exit_action.triggered.connect(self._perform_full_exit)                     # 退出菜单
        self.config_action.triggered.connect(self.open_config_page)                     # 配置菜单'''

        # 当前配置窗口引用
        self.config_window = None

        # 尝试初始化配置(防止配置不存在)
        ConfigManager.initialize()
        
        # 加载顺序：先数据 → 再配置 → 最后UI
        self._load_student_data()  # 加载学生名单到StudentPool
        self._restore_application_config()  # 恢复应用配置
        self._restore_window_state()  # 恢复窗口状态
        self._update_statistics()  # 更新统计信息显示

        # 确保自启动状态同步
        self._sync_auto_start_state()

        # 初始化悬浮窗管理器（在加载配置后）
        self.floating_manager = FloatingWindowManager(self)
        self.floating_manager.initialize()
        
        # 连接管理器信号
        self.floating_manager.windowHidden.connect(lambda: self.show())

        # ========= 单实例管理器 ==========
        self._init_single_instance()

    # ========== 单实例管理初始化 ==========
    def _init_single_instance(self):
        """初始化单实例管理器（必须在所有属性准备完成后）"""
        self.single_instance_manager = SingleInstanceManager()
        self.single_instance_manager.show_window_signal.connect(
            self.handle_single_instance_request
        )
        
        # 检测是否已有实例
        if self.single_instance_manager.check_existing():
            # 已有实例，标记退出
            self._should_exit = True
            return
        
        # 没有实例，启动服务器监听
        self.single_instance_manager.start_server()

    def handle_single_instance_request(self):
        """处理来自其他实例的显示请求"""
        print("[SINGLE] 收到显示主窗口请求...")
        
        # 1. 确保窗口不是最小化状态
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        
        # 2. 显示主窗口
        self.show()
        self.raise_()
        
        # 3. 强制窗口管理器注意（Windows特殊处理）
        current_flags = self.windowFlags()
        self.setWindowFlags(current_flags & ~Qt.WindowStaysOnTopHint)
        self.show()
        QApplication.processEvents()
        self.setWindowFlags(current_flags | Qt.WindowStaysOnTopHint)
        self.show()
        
        # ========== 通过管理器处理悬浮窗 ==========
        
        # 4. 通过管理器隐藏所有悬浮窗
        if hasattr(self, 'floating_manager'):
            self.floating_manager.hide_all()
            self.floating_manager.reset_positions()  # 重置吸附状态
        
        # 5. 更新配置状态并立即保存
        config = ConfigManager.load_cached()
        config[ConfigManager.KEY_FLOATING_MODE] = "window"  # 改为窗口模式
        try:
            ConfigManager.save_atomic(config)
            print("[SINGLE] 悬浮窗状态已同步到配置")
        except RuntimeError as e:
            print(f"[SINGLE] 配置保存失败: {e}")
        
        # 6. 强制UI刷新
        QApplication.processEvents()

    # ========== 阶段1：加载学生数据 ==========
    def _load_student_data(self) -> None:
        """加载学生数据并构建StudentPool"""
        MAX_RETRIES = 2
        retry_count = 0
        # 加载防重复设置
        self.no_duplicate = ConfigManager.load_cached().get(ConfigManager.KEY_NO_DUPLICATE, 0)
        
        while retry_count <= MAX_RETRIES:
            try:
                # 加载数据
                all_students = list(self._parse_student_file(
                    ConfigManager.NAMES_FILE, 
                    default_gender=Gender.UNKNOWN
                ))
                female_students = list(self._parse_student_file(
                    ConfigManager.G_NAMES_FILE, 
                    default_gender=Gender.FEMALE
                ))
                
                # 一致性校验
                all_names = {s.original_name for s in all_students}
                female_names = {s.original_name for s in female_students}
                invalid_female = female_names - all_names
                
                if invalid_female:
                    # 数据错误：强制修复，无忽略选项
                    if self._show_fix_dialog_and_execute(invalid_female):
                        retry_count += 1
                        continue  # 修复后重试
                    else:
                        sys.exit(1)
                
                # 数据正常
                self._data_issues = {'is_valid': True}
                self.student_pool = StudentPool(all_students, female_students)
                
                # 防重复设置验证
                total = len(self.student_pool.get_all_students())
                if self.no_duplicate >= total:
                    old_value = self.no_duplicate
                    self.no_duplicate = max(0, total - 1)
                    self.status_label.setText(f"防重复次数已从 {old_value} 自动调整为 {self.no_duplicate}")
                
                print(f"[DATA] 加载成功: 总共{total}人, 女生{len(self.student_pool.get_female_students())}人")
                return
                
            except FileNotFoundError:
                # 文件不存在 → 尝试初始化文件
                ConfigManager.initialize()
                retry_count += 1
                continue  # 转换后重试
            except UnicodeDecodeError as e:
                print(f"[DATA] 编码错误: {e}")
                if retry_count == 0:  # 只在第一次尝试转换
                    print("[DATA] 尝试自动转换为UTF-8...")
                    self._convert_files()
                    retry_count += 1
                    continue  # 转换后重试
                else:
                    # 转换后仍然失败
                    print("[DATA] 转换后仍失败，使用空名单")
                    self.student_pool = StudentPool(['加载失败'], ['加载失败'])
                    self._data_issues = {'is_valid': False, 'invalid_female': set()}
                    self.status_label.setText("编码转换失败，使用空名单")
                    return
            except Exception as e:
                print(f"[DATA] 加载失败，使用空名单: {e}")
                self.student_pool = StudentPool(['加载失败'], ['加载失败'])
                self._data_issues = {'is_valid': False, 'invalid_female': set()}
                self.status_label.setText(f"名单加载失败：{e}")
                return
        
        # 重试次数用尽
        print("[DATA] 多次修复失败，退出程序")
        QMessageBox.critical(self, "严重错误", "无法修复名单配置，程序即将退出！")
        sys.exit(1)

    def _convert_files(self) -> None:
        """提示应该转换名单文件编码为UTF-8"""
        # 创建非阻塞确认框
        self._convert_dialog = QMessageBox(self)
        self._convert_dialog.setWindowTitle("转换格式确认")
        self._convert_dialog.setText("文件编码不正确，是否尝试自动转换为UTF-8？")
        self._convert_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        self._convert_dialog.setDefaultButton(QMessageBox.Yes)
        
        # 关键：连接finished信号而非exec_()阻塞
        self._convert_dialog.finished.connect(self._on_convert_dialog_finished)
        self._convert_dialog.open()
        self._convert_dialog.exec()

    def _on_convert_dialog_finished(self, result: int) -> None:
        """确认框关闭后的回调"""
        if result == QMessageBox.Yes:
            self._convert_files_to_utf8()  # 调用核心转换函数
        else:
            print("[RESET] 用户取消转换")
        
        # 清理对话框对象
        self._convert_dialog.deleteLater()
        self._convert_dialog = None

    def _show_fix_dialog_and_execute(self, invalid_names: set) -> bool:
        """
        显示修复对话框并执行修复
        :return: True=修复成功需重试, False=用户选择退出
        """
        dialog = DataFixDialog(self, invalid_names)
        dialog.exec()
        
        clicked = dialog.clickedButton().text()
        
        # 执行对应操作
        if clicked == "在总名单中添加":
            success, msg = ConfigManager._quick_fix_name_file('add_to_all')
        elif clicked == "从女生名单删除":
            success, msg = ConfigManager._quick_fix_name_file('remove_from_girl')
        else:  # "退出程序"
            return False
        
        # 显示结果
        if success:
            QMessageBox.information(self, "修复成功", msg)
            return True
        else:
            QMessageBox.critical(self, "修复失败", msg)
            # 修复失败也退出，避免无限循环
            return False
        
    def _convert_files_to_utf8(self) -> bool:
        """
        自动将名单文件转换为UTF-8编码

        - ！！！本函数检测功能有bug，但可以应对简单情况，实际也罕见，懒得修

        - 优先尝试UTF-16系列编码
        - 确保文件系统刷新
        :return: 是否成功转换至少一个文件
        """
        print("[DATA] 开始自动编码转换...")
        
        # 优化编码尝试顺序：UTF-16系列优先，中文编码在后
        encodings_to_try = [
            'utf-8', 'utf-16', 'utf-16le', 'utf-16be',  # UTF-16系列优先
            'gb18030', 'gbk', 'gb2312'         # 中文编码在后
        ]
        
        backup_dir = ConfigManager.CONFIG_DIR / "encoding_backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        any_converted = False
        
        for file_key, file_path in [
            ('names', ConfigManager.NAMES_FILE),
            ('g_names', ConfigManager.G_NAMES_FILE)
        ]:
            if not file_path.exists():
                print(f"[DATA] {file_key} 文件不存在，跳过")
                continue
            
            # 创建备份
            try:
                backup_path = backup_dir / f"{file_key}_backup_{timestamp}.txt"
                backup_path.write_bytes(file_path.read_bytes())
                print(f"[DATA] 备份创建: {backup_path}")
            except Exception as e:
                print(f"[DATA] 备份失败 {file_key}: {e}")
                continue
            
            # 读取并转换
            converted = False
            last_error = None
            for encoding in encodings_to_try:
                try:
                    print(f"[DATA] 尝试用 {encoding} 读取 {file_key}...")
                    # 使用 'strict' 模式确保准确检测
                    content = file_path.read_text(encoding=encoding, errors='strict')
                    if encoding == 'utf-8':
                        print(f"[DATA] {file_key} 已是 UTF-8 编码，无需转换")
                        converted = True
                        # 删除文件
                        file_path = Path(str(backup_path))
                        if file_path.exists():
                            file_path.unlink()
                            print(f"[DATA] {backup_path} 已成功删除")
                        break
                    # 移除可能的BOM头
                    if content.startswith('\ufeff'):
                        content = content[1:]
                    
                    # 保存为UTF-8 with BOM（确保Windows记事本等软件正确识别）
                    file_path.write_text(content, encoding='utf-8-sig')
                    converted = True
                    any_converted = True
                    print(f"[DATA] {file_key} 成功转换为 UTF-8")
                    break
                except Exception as e:
                    last_error = e
                    print(f"[DATA] {encoding} 失败: {e}")
                    continue
            
            if not converted:
                print(f"[DATA] 无法转换 {file_key}，恢复备份: {last_error}")
                try:
                    backup_path.replace(file_path)
                except Exception as e:
                    print(f"[DATA] 恢复备份失败: {e}")
        
        print("[DATA] 编码转换完成")
        
        # 确保文件系统刷新
        QApplication.processEvents()
        #time.sleep(0.1)  # 短暂延迟确保写入完成
        
        return any_converted

    def _parse_student_file(self, file_path: Path, default_gender: Gender) -> Generator[Student, None, None]:
        """解析学生文件，生成Student对象"""
        if not file_path.exists():
            return  # 生成器直接结束
        
        # 使用'utf-8-sig'自动处理BOM头
        with file_path.open('r', encoding='utf-8-sig') as f:
            for line_num, line in enumerate(f, 1):
                #解包，line_num防止line变为int类型
                stripped = line.strip()
                
                # 跳过空行和注释
                if not stripped or stripped.startswith('#'):
                    continue
                
                # 创建Student对象（数据模型）
                yield Student(
                    original_name=line.rstrip('\n'),  # 保留原始格式
                    display_name=stripped,           # 去空格用于显示
                    gender=default_gender
                )
    
    # ========== 阶段2：恢复应用配置 ==========
    
    def _restore_application_config(self) -> None:
        """
        从配置恢复应用状态
        - 抽取次数、性别筛选、语音设置等
        - 不依赖UI控件（在setupUi之前调用）
        """
        config = ConfigManager.load_cached()
        
        # 恢复抽取次数
        self.picked_count = config.get(ConfigManager.KEY_PICKED_COUNT, 0)
        
        # 恢复性别筛选（先设置，UI在setupUi后同步）
        gender_str = config.get(ConfigManager.KEY_GENDER_FILTER, 'unknown')
        self.current_gender = Gender(gender_str)
        
        # 恢复语音设置
        self.speak_speed = config.get(ConfigManager.KEY_SPEAK_SPEED, 170)
        
        # 恢复多音字替换（缓存到内存，避免每次读取文件）
        self._name_changes_cache = ConfigManager.load_name_changes()
        
        # 恢复抽取模式
        self.is_saving_results = config.get(ConfigManager.KEY_IS_SAVE, False)
        self.pick_balanced = config.get(ConfigManager.KEY_PICK_BALANCED, False)

        #恢复动画时长
        self.animation_time = config.get(ConfigManager.KEY_ANIMATION_TIME, 0.8)
        
        # 恢复自启动设置（并验证实际状态）
        auto_start_config = config.get(ConfigManager.KEY_AUTO_START, False)
        #from AutoStartManager import AutoStartManager
        if auto_start_config != AutoStartManager.is_enabled():
            AutoStartManager.set_enabled(auto_start_config)

        # 恢复悬浮窗相关配置
        config[ConfigManager.KEY_FLOATING_MODE] = "window"
        self.floating_x_size = config.get(ConfigManager.KEY_FLOATING_X_SIZE, 100)
        self.floating_y_size = config.get(ConfigManager.KEY_FLOATING_Y_SIZE, 100)
        self.f_autostick = config.get(ConfigManager.KEY_FLOATING_AUTOSTICK, False)
        self.double_floating_window = config.get(ConfigManager.KEY_DOUBLE_FLOATING_WINDOW, False)
        self.floating_image = config.get(ConfigManager.KEY_FLOATING_IMAGE, None)

        # 重建StudentPool（需要传递no_duplicate参数）
        # 需要在_load_student_data后调用
        self._rebuild_student_pool()

        # ========== 自动恢复可抽取名单池和统计信息 ==========
        try:
            saved_names = set(config.get('saved_available_names', []))
            if self.is_saving_results and saved_names:
                self.student_pool.restore_available_names(saved_names)
                print(f"[恢复] 已恢复{len(saved_names)}个可用名字")
            else:
                print("[恢复] 使用默认全可用状态")
        except Exception as e:
            print(f"[恢复失败]: {e}")
                # 更新统计显示
            self._update_statistics()
    
    # ========== 窗口几何配置 ==========

    def _restore_window_state(self) -> None:
        """
        恢复窗口几何和控件状态
        - 必须在setupUi之后调用
        - 控件信号应在此时连接
        """
        config = ConfigManager.load_cached()
        
        # 1. 恢复窗口几何（使用Qt原生二进制格式）
        geometry_data = config.get(ConfigManager.KEY_WINDOW_GEOMETRY_QT)
        if geometry_data:
            # 从base64解码并恢复（确保可序列化）
            from base64 import b64decode
            try:
                self.restoreGeometry(b64decode(geometry_data))
                print("[WINDOW] 窗口几何已恢复")
            except Exception as e:
                print(f"[WINDOW] 恢复几何失败，使用默认值: {e}")
                self.setGeometry(100, 100, 577, 601)

        self.set_gender_ui_widget_visible()

        # 按照悬浮窗显示设置决定self.close_button的可见性
        self.close_button.setVisible(config.get(ConfigManager.KEY_SHOW_FLOATING, True))
        
        # 恢复UI控件状态（双向绑定）
        # 注意：先blockSignals防止级联触发
        self._block_ui_signals(True)
        
        self.pick_again_checkbox.setChecked(
            config.get(ConfigManager.KEY_PICK_AGAIN, True)
        )
        self.g_names_pick_checkbox.setChecked(
            self.current_gender == Gender.FEMALE
        )
        self.b_names_pick_checkbox.setChecked(
            self.current_gender == Gender.MALE
        )
        self.pick_time_checkbox.setChecked(
            config.get(ConfigManager.KEY_RECITE_MODE, False)
        )
        
        self._block_ui_signals(False)
        
        # 恢复悬浮窗状态（但不立即显示）
        self.is_floating_visible = config.get(ConfigManager.KEY_SHOW_FLOATING, True)
    
    def _block_ui_signals(self, block: bool) -> None:
        """批量阻塞/恢复控件信号"""
        widgets = [
            self.pick_again_checkbox,
            self.g_names_pick_checkbox,
            self.b_names_pick_checkbox,
            self.pick_time_checkbox,
            self.gender_checkBox,
            # ... 其他控件
        ]
        for widget in widgets:
            widget.blockSignals(block)
    
    def request_save(self, *reasons: str):
        """
        注册保存请求
        
        1. 'geometry' 类型请求自动覆盖（只保留最后一次）
        2. 'state' 和 'floating' 合并为 'ui_state'
        3. 超过队列长度限制时触发紧急保存
        """
        # 几何状态去重：如果已存在geometry请求，先移除（保留新状态）
        if 'geometry' in reasons and 'geometry' in self._save_queue:
            self._save_queue.discard('geometry')  # 移除旧的geometry请求
            print("[SAVE] 合并重复的geometry请求")
        
        # 批量注册新请求
        new_requests = set(reasons)
        self._save_queue.update(new_requests)
        
        # 如果队列过长（>5个），立即触发保存防止积压
        if len(self._save_queue) > 5:
            print(f"[SAVE] 队列积压{len(self._save_queue)}个，触发紧急保存")
            self._debounce_timer.stop()
            self._flush_all_saves()
            return
        
        # 正常防抖流程
        self._debounce_timer.stop()
        self._debounce_timer.start(CONFIG_SAVE_DELAY)
        
        print(f"[SAVE] 注册保存请求: {list(self._save_queue)} (共{len(self._save_queue)}个待保存)")
    
    def _flush_all_saves(self):
        """
        执行批量保存
        
        优化策略：
        1. 将多个reason合并为最小配置更新集合
        2. 对比内存中的_config_cache，仅写入变更字段
        3. 对geometry使用Qt原生base64编码（保持原有逻辑）
        """
        if not hasattr(self, '_save_queue') or not self._save_queue:
            return
        
        reasons_to_process = self._save_queue.copy()
        self._save_queue.clear()  # 立即清空，防止重入
        
        print(f"[SAVE] 开始批量保存: {list(reasons_to_process)}")

        config = ConfigManager.load_cached()  # 从内存缓存读取
        
        # 将多个reason合并为统一的配置更新字典
        updates = {}
        
        # geometry变更（高频）：单独处理
        if 'geometry' in reasons_to_process:
            from base64 import b64encode
            geometry_data = b64encode(self.saveGeometry()).decode('ascii')
            
            # 对比内存缓存，只有真正变化才写入
            if config.get(ConfigManager.KEY_WINDOW_GEOMETRY_QT) != geometry_data:
                updates[ConfigManager.KEY_WINDOW_GEOMETRY_QT] = geometry_data
                print("[SAVE] 窗口几何已变更，准备写入")
            else:
                print("[SAVE] 窗口几何未变化，跳过写入")
        
        # UI状态变更：批量合并
        if {'state', 'floating'}.intersection(reasons_to_process):
            # 批量收集UI状态（避免重复读取控件状态）
            new_ui_state = {
                ConfigManager.KEY_PICKED_COUNT: self.picked_count,
                ConfigManager.KEY_NO_DUPLICATE: self.no_duplicate,
                ConfigManager.KEY_PICK_BALANCED: self.pick_balanced,
                ConfigManager.KEY_RECITE_MODE: self.is_recite_mode,
                ConfigManager.KEY_PICK_AGAIN: self.pick_again_checkbox.isChecked(),
                ConfigManager.KEY_SPEAK_SPEED: self.speak_speed,
                ConfigManager.KEY_SHOW_FLOATING: self.is_floating_visible,
                ConfigManager.KEY_AUTO_START: AutoStartManager.is_enabled(),
                ConfigManager.KEY_ANIMATION: self.is_animation_enabled,
            }
            
            # 从悬浮窗管理器获取状态（如果已初始化）
            if hasattr(self, 'floating_manager'):
                new_ui_state[ConfigManager.KEY_DOUBLE_FLOATING_WINDOW] = (
                    self.floating_manager.get_window_count() == 2
                )
            
            # 增量对比：只添加变更的字段
            for key, new_value in new_ui_state.items():
                if config.get(key) != new_value:
                    updates[key] = new_value
                    print(f"[SAVE] 状态变更 {key}: {config.get(key)} -> {new_value}")
        
        # 可抽取名单池：仅在启用自动保存时写入
        if hasattr(self, 'student_pool') and self.is_saving_results:
            saved_names = list(self.student_pool.get_available_names())
            if set(config.get(ConfigManager.KEY_SAVED_AVAILABLE_NAMES, [])) != set(saved_names):
                updates[ConfigManager.KEY_SAVED_AVAILABLE_NAMES] = saved_names
                print(f"[SAVE] 可抽取名单已更新，共{len(saved_names)}人")
        
        # 悬浮窗几何从管理器获取
        if 'floating' in reasons_to_process and hasattr(self, 'floating_manager'):
            # 获取悬浮窗状态（但不直接写入，由管理器处理）
            floating_states = self.floating_manager.get_window_states()
            for key, value in floating_states.items():
                if config.get(key) != value:
                    updates[key] = value
        
        if not updates:
            print("[SAVE] 配置无实际变更，取消写入")
            return
        
        try:
            # 只更新变更的字段（而非整个config）
            config.update(updates)
            ConfigManager.save_atomic(config)  # 内部有SHA256变更检测
            print(f"[SAVE] 成功写入{len(updates)}个变更字段")
        except RuntimeError as e:
            print(f"[SAVE] 保存失败: {e}")
            # 失败时将reasons放回队列，延迟重试
            self._save_queue.update(reasons_to_process)
            QTimer.singleShot(1000, self._flush_all_saves)  # 1秒后重试
        
    def _save_application_state(self):
        """触发应用状态保存（供外部调用）"""
        self.request_save('state')
    
    def _sync_auto_start_state(self) -> None:
        """
        同步自启动状态（以注册表为准）
        - 注册表与配置不一致时，自动修正
        """
        config = ConfigManager.load_cached()
        config_state = config.get(ConfigManager.KEY_AUTO_START, False)
        actual_state = AutoStartManager.is_enabled()
        
        if config_state != actual_state:
            print(f"[CONFIG] 自启动状态不一致，修正为: {actual_state}")
            config[ConfigManager.KEY_AUTO_START] = actual_state
            ConfigManager.save(config)

    def _rebuild_student_pool(self):
        """重建学生池以应用新的防重复设置"""
        if not hasattr(self, 'student_pool') or not self.student_pool:
            return
        
        if hasattr(self, 'animation_timer') and self.animation_timer.isActive():
            self.animation_timer.stop()
            print("[重建] 停止动画定时器")
        
        if hasattr(self, 'animation_idx_pool'):
            delattr(self, 'animation_idx_pool')
            print("[重建] 清理动画池")
        
        old_pool = self.student_pool

        # 保存当前状态
        current_available = old_pool.get_available_names()

        # 保存防重复位图状态
        old_recent_bitmap = getattr(old_pool, '_recent_bitmap', None)

        if self.pick_again_checkbox.isChecked() and self.no_duplicate == 0:
            self.no_duplicate = self.no_duplicate_cache

        # 重建池子
        self.student_pool = StudentPool(
            old_pool.get_all_students(),
            old_pool.get_female_students(),
            self.no_duplicate
        )

        # 恢复状态
        self.student_pool.restore_available_names(current_available)
        
        # 5. 恢复防重复状态
        if self.no_duplicate > 0 and old_recent_bitmap is not None:
            # 直接复制位图
            self.student_pool._recent_bitmap = old_recent_bitmap.copy()

    def moveEvent(self, event):
        super().moveEvent(event)
        # 仅在非移动状态下保存（避免拖拽时频繁触发）
        if not getattr(self, '_is_moving', False):
            self.request_save('geometry')

    # 在窗口移动时设置标志
    def mousePressEvent(self, event):
        """记录拖动起始状态"""
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self._is_moving = True
            self._drag_start_pos = event.globalPos()
            self._drag_window_start_pos = self.pos()
            self._last_valid_position = self.pos()
            self.setCursor(Qt.OpenHandCursor)  # 拖动时显示抓手光标
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """拖动时实时限制移动范围"""
        if event.buttons() == Qt.LeftButton and self._is_moving:
            # 计算鼠标移动距离
            delta = event.globalPos() - self._drag_start_pos
            # 计算新位置（未经边界检查）
            raw_new_pos = self._drag_window_start_pos + delta
            
            # 获取屏幕可用区域（自动排除任务栏）
            screen = QApplication.primaryScreen().availableGeometry()
            
            # 计算窗口在目标位置时的几何矩形
            window_rect = QRect(raw_new_pos, self.size())
            
            # 检测是否将要超出边界
            exceed_left = window_rect.left() < screen.left() - window_rect.width() * 9 // 10
            exceed_right = window_rect.right() > screen.right() + window_rect.width() *9 // 10
            exceed_top = window_rect.top() < screen.top() - window_rect.height() *9 // 10
            exceed_bottom = window_rect.bottom() > screen.bottom() + window_rect.height() *9 // 10
            
            # 如果将要越界，阻止该方向移动
            if exceed_left or exceed_right or exceed_top or exceed_bottom:
                # 显示禁止光标，不更新窗口位置
                self.setCursor(Qt.ForbiddenCursor)
                return  # 直接返回，不移动窗口
            
            # 在允许范围内，正常移动并记录有效位置
            self.setCursor(Qt.ClosedHandCursor)
            self._last_valid_position = raw_new_pos
            self.move(raw_new_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """拖动结束，检查是否需要回弹"""
        if event.button() == Qt.LeftButton and self._is_moving:
            # 恢复光标
            self.unsetCursor()
            
            # 获取屏幕可用区域
            screen = QApplication.primaryScreen().availableGeometry()
            
            # 计算边界临界点位置
            window_rect = QRect(self._last_valid_position, self.size())
            final_x = self._last_valid_position.x()
            final_y = self._last_valid_position.y()
            
            needs_adjust = False
            
            # 检查水平边界
            if window_rect.left() < (screen.left() - window_rect.width() * 9 // 10):
                final_x = screen.left()
                needs_adjust = True
            elif window_rect.right() > (screen.right() + window_rect.width() * 9 // 10):
                final_x = screen.right() - self.width()
                needs_adjust = True
            
            # 检查垂直边界
            if window_rect.top() < (screen.top() - window_rect.height() * 9 // 10):
                final_y = screen.top()
                needs_adjust = True
            elif window_rect.bottom() > (screen.bottom() + window_rect.height() * 9 // 10):
                final_y = screen.bottom() - self.height()
                needs_adjust = True
            
            # 如果需要回弹，使用平滑动画(似乎没用)
            if needs_adjust:
                self.move(final_x, final_y)  # 直接跳转到正确位置
                self._last_valid_position = QPoint(final_x, final_y)
            
            # 重置状态并保存
            self._is_moving = False
            self.request_save('geometry')  # 保存最终位置
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def set_recite(self):
        if not self.is_recite_mode:
            self.is_recite_mode = True
            self.timer_label.show()

        elif self.is_recite_mode:
            self.is_recite_mode = False
            self.is_running = False
            self.timer_label.hide()
    
    def sync_floating_config(self):
        """供配置页调用的同步接口"""
        self.floating_manager.force_sync()

    @pyqtSlot()
    def _on_gender_filter_changed(self):
        """性别筛选优化"""
        sender = self.sender()
        is_checked = sender.isChecked()

        # ===== 数据问题拦截 =====
        if not self._data_issues['is_valid'] and is_checked:
            # 如果数据有问题，禁止筛选并提示
            reply = QMessageBox.warning(
                self,
                "数据配置错误",
                "名单配置存在错误，无法使用性别筛选功能。\n"
                "请先在配置中修复名单文件。",
                QMessageBox.Ok
            )
            # 取消勾选
            sender.setChecked(False)
            return
        
        # 状态检查
        if sender == self.g_names_pick_checkbox and is_checked:
            if self.b_names_pick_checkbox.isChecked():
                self.b_names_pick_checkbox.setChecked(False)
            self.current_gender = Gender.FEMALE
        elif sender == self.b_names_pick_checkbox and is_checked:
            if self.g_names_pick_checkbox.isChecked():
                self.g_names_pick_checkbox.setChecked(False)
            self.current_gender = Gender.MALE
        else:
            self.current_gender = Gender.UNKNOWN
        
        # 智能重置确认
        if is_checked and self.student_pool.get_stats(self.current_gender)[1] == 0:
            reply = QMessageBox.question(
                self, "重置名单", "该性别名单已抽完，是否重置？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.student_pool.reset(self.current_gender)
        
        self._update_statistics()
    
    def _on_toggle_repeat(self):
        """切换重复模式时处理防重复逻辑"""
        is_checked = self.pick_again_checkbox.isChecked()
        print(f"[MODE] 切换重复模式: {'启用' if is_checked else '禁用'}")
        self.reset_silently()
        
        if is_checked:
            # 启用重复模式时，应用防重复设置
            config = ConfigManager.load_cached()
            self.no_duplicate = config.get(ConfigManager.KEY_NO_DUPLICATE, 0)
            
            # 如果防重复次数大于0，显示提示
            if self.no_duplicate > 0:
                self.status_label.setText(
                    f"防重复模式：最近{self.no_duplicate}次不会重复"
                )
            
            # 重建池子以启用队列
            self._rebuild_student_pool()
        else:
            # 禁用重复模式时，忽略防重复
            self.no_duplicate_cache = self.no_duplicate
            self.no_duplicate = 0
            
            # 重建池子以禁用队列
            self._rebuild_student_pool()
        
        self._update_statistics()

    @pyqtSlot()
    def _pick_name(self):
        """优化后的抽取逻辑"""
        self.pick_name_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        
        try:
            allow_repeat = self.pick_again_checkbox.isChecked()
            display_name = self.student_pool.pick(self.current_gender, remove=not allow_repeat)
        except IndexError as e:
        # ===== 新增：智能错误诊断 =====
            if not self._data_issues['is_valid']:
                # 数据有问题导致的空池
                QMessageBox.critical(
                    self,
                    "无法抽取",
                    "由于名单配置错误，无法抽取学生。\n\n"
                    "错误原因：g_names.txt 中存在不在总名单中的名字\n"
                    "请打开配置面板，检查并修正名单文件。"
                )
            else:
                # 正常抽完
                self._show_completion_message()

            self.pick_name_button.setEnabled(True)
            return
        
        # 启动动画或显示结果
        stats = self.student_pool.get_stats(self.current_gender)  # 获取性别过滤统计
        if self.is_animation_enabled and stats[1] > 2:  # stats[1] = available
            self._start_animation(display_name)
        else:
            self._display_result(display_name)
    
    def _show_completion_message(self):
        """显示重置名单提示"""
        self.name_label.setText("请重置")
        self.name_label.setStyleSheet("color: red")
        QMessageBox.information(self, "提示", "所有名字已抽取完毕，请重置")
        self.reset_button.setEnabled(True)
        self.pick_name_button.setEnabled(False)

    def _start_animation(self, final_name: str):
        """修复版动画启动：正确采样多个索引"""
        self.animation_start_time = time.time()
        
        # 获取候选索引（改为调用新的位图方法）
        candidate_bitmap = self.student_pool._get_candidate_bitmap(self.current_gender)
        available_indices = [i for i, bit in enumerate(candidate_bitmap) if bit]
        
        # 空池保护
        if not available_indices:
            print("[ANIMATION] 警告：动画池为空，直接显示结果")
            self._display_result(final_name)
            return
        
        # 最多采样50个
        max_animation = min(len(available_indices), 50)
        self.animation_idx_pool = random.sample(available_indices, max_animation)
        self.animation_final_name = final_name
        self.animation_timer.start()
        
        print(f"[ANIMATION] 启动动画，采样池大小: {max_animation}")

    def _update_animation(self):
        """动画帧更新 - 从名字池随机选择"""
        elapsed = time.time() - self.animation_start_time
        if elapsed < self.animation_time:
            # 从预采样的id池选择，避免每帧生成
            random_id = random.choice(self.animation_idx_pool)
            rdm_name = self.student_pool._students[random_id].display_name
            self.name_label.setText(rdm_name)
        else:
            self.animation_timer.stop()
            self._display_result(self.animation_final_name)

    def _display_result(self, display_name: str):
        """显示最终结果"""
        self.name_label.setText(display_name)
        
        # 异步语音播报
        if self.is_speech_enabled:
            self._speak_name_async(display_name)
        
        # 更新状态（单次查找）
        
        self.picked_count += 1
        # 如果不允许重复，启用重置按钮
        if not self.pick_again_checkbox.isChecked():
            self.reset_button.setEnabled(True)
        
        if self.is_recite_mode:
            self._start_recite_timer()

        QTimer.singleShot(50, self._update_statistics)

    def _speak_name_async(self, text):

        # 如果有语音线程在运行，直接返回，避免并发
        if self.speech_thread and self.speech_thread.isRunning():
            #print("语音线程正在播报，等待播报结束后再抽取")
            return

        self.speech_thread = SpeechThread(
            text, 
            speak_speed=self.speak_speed
        )
        self.speech_thread.finished.connect(self._on_speech_finished)
        self.pick_name_button.setEnabled(False)  # 语音播报时禁用按钮
        self.speech_thread.start()

    def _on_speech_finished(self):
        self.pick_name_button.setEnabled(True)

    def _apply_name_changes(self, name: str) -> str:
        """应用多音字替换（带缓存）"""
        if not hasattr(self, '_name_changes_cache'):
            self._name_changes_cache = ConfigManager.load_name_changes()
        # 使用字典查找替代循环
        for i in range(1, 4):
            orig = self._name_changes_cache.get(f'speak_change_{chr(96+i)}1', '')
            if name == orig:
                self.speak_name = self._name_changes_cache.get(f'speak_change_{chr(96+i)}2', name)
                return self.speak_name
        return name

    def _update_recite_timer(self):
        """
        背书计时器核心槽函数
        - 支持倒计时模式（3.0 → 0.0）
        - 支持正计时模式（0.0 → 持续增加）
        """
        current_time = time.time()
        
        # ========== 倒计时模式 ==========
        if self._recite_state['mode'] == 'countdown':
            elapsed = current_time - self._recite_state['start_time']
            remaining = self._recite_state['target_time'] - elapsed
            
            if remaining > 0:
                # 显示剩余时间（红色）
                self.timer_label.setText(f"{remaining:.1f}s")
                self.timer_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                # 倒计时结束，切换到正计时
                self._recite_state['mode'] = 'elapsed'
                self._recite_state['start_time'] = current_time
                self.timer_label.setStyleSheet("color: black;")
        
        # ========== 正计时模式 ==========
        elif self._recite_state['mode'] == 'elapsed':
            elapsed = current_time - self._recite_state['start_time']
            self.timer_label.setText(f"{elapsed:.1f}s")

    def _start_recite_timer(self, initial_seconds: float = 3.0):
        """
        启动背书计时器
        """
        # 重置状态
        self._recite_state = {
            'mode': 'countdown',
            'target_time': initial_seconds,
            'start_time': time.time(),
            'elapsed': 0,
        }
        
        # 显示标签
        self.timer_label.show()
        
        # 启动定时器
        self.recite_timer.start()
        
        print(f"[RECITE] 倒计时启动: {initial_seconds}秒")

    def _stop_recite_timer(self):
        """
        停止背书计时器
        """
        if self.recite_timer.isActive():
            self.recite_timer.stop()
        
        self.timer_label.hide()
        self._recite_state = {
            'mode': 'countdown',
            'target_time': 0,
            'start_time': 0,
            'elapsed': 0,
        }
        
        print("[RECITE] 计时器停止")
    
    def reset(self) -> None:
        """
        重置当前性别池到初始状态，并重新加载名单文件
        - 从names.txt和g_names.txt重新读取最新数据
        - 清空已抽取集合
        - 恢复所有学生到可抽取状态
        - 自动更新统计信息
        """
        # ========== 新增：重新加载名单文件 ==========
        try:
            # 先停止定时器，避免加载期间UI刷新
            if self.animation_timer.isActive():
                self.animation_timer.stop()
            if self.recite_timer.isActive():
                self.recite_timer.stop()
            
            # 重新加载学生数据（从txt文件）
            self._load_student_data()
            
            # 加载成功后显示提示
            total_count = len(self.student_pool._students)
            female_count = len(self.student_pool.get_female_students())
            self.status_label.setText(f"名单已刷新：共{total_count}人（女生{female_count}人）")
            print(f"[RESET] 名单已刷新，当前可抽取人数: {total_count}")
            
        except Exception as e:
            # 加载失败时不中断重置流程，使用旧数据
            print(f"[RESET] 刷新名单失败，使用现有数据: {e}")
            self.status_label.setText(f"刷新失败：{e}")

        # ========== 原有：重置池子状态和UI ==========
        
        # 清理动画临时数据
        self.animation_final_name = None
        self.animation_final_student = None
        
        # 重置计数器（根据需求决定是否保留）
        # self.picked_count = 0  # 如果想保留总次数，注释掉此行
        
        # 重置UI显示
        self.name_label.setText("请抽取")
        self.name_label.setStyleSheet("color: black")
        self.timer_label.setText("0.0s")
        
        # 更新统计信息
        self._update_statistics()
        
        # 保存配置（如果启用自动保存）
        if self.is_saving_results:
            self.request_save('state')

        # 恢复抽取按钮状态
        self.pick_name_button.setEnabled(True)

        _, available, _ = self.student_pool.get_stats()  # 使用get_stats()
        print(f"[RESET] 重置完成，性别池{self.current_gender}已就绪, 当前可抽取人数: {available}")

    # ========== UI交互封装（分离职责） ==========
    def _reset_with_confirm(self) -> None:
        """
        带确认的重置（UI层）
        - 弹出确认对话框（非阻塞）
        - 用户确认后调用reset()
        """
        # 创建非阻塞确认框
        self._confirm_dialog = QMessageBox(self)
        self._confirm_dialog.setWindowTitle("重置确认")
        self._confirm_dialog.setText("确定要重置点名名单吗？将清空已抽取记录。")
        self._confirm_dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        self._confirm_dialog.setDefaultButton(QMessageBox.No)
        
        # 关键：连接finished信号而非exec_()阻塞
        self._confirm_dialog.finished.connect(self._on_reset_dialog_finished)
        self._confirm_dialog.open()
    
    def _on_reset_dialog_finished(self, result: int) -> None:
        """确认框关闭后的回调"""
        if result == QMessageBox.Yes:
            self.reset()  # 调用核心重置函数
            self.status_label.setText("已重置名单")  # 临时提示
        else:
            print("[RESET] 用户取消重置")
        
        # 清理对话框对象
        self._confirm_dialog.deleteLater()
        self._confirm_dialog = None

    # ========== 静默重置（无UI，供程序内部调用） ==========
    def reset_silently(self) -> None:
        """
        静默重置
        - 不弹窗,不提示
        """
        print("[RESET] 静默重置触发")
        self.reset()  # 复用核心逻辑
    
    # ========== 快捷重置（双击状态栏等） ==========???
    '''def reset_quick(self) -> None:
        """快速重置（跳过确认，直接执行）"""
        # 可添加Shift键检测：按住Shift跳过确认
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self.reset()  # 跳过确认
        else:
            self._reset_with_confirm()  # 正常确认'''

    def _update_statistics(self):
        """更新状态栏统计信息"""
        total, available, picked= self.student_pool.get_stats(self.current_gender)
        
        repeat_info = ""
        if self.pick_again_checkbox.isChecked() and self.no_duplicate > 0:
            #recent_count = len(self.student_pool._recent_pick_ids)
            repeat_info = f" | 防重复: {self.no_duplicate}"#{recent_count}/{self.no_duplicate}"
        
        if not self.pick_again_checkbox.isChecked():
            probability = f"{(1 / available * 100):.2f}" if available > 0 else "0"
            stats_text = (
                f"总人数: {total}  |  "
                f"已抽取: {picked}  |  "
                f"可抽取: {available}  |  "
                f"概率: {probability}%{repeat_info}"
            )
        else:
            stats_text = f"总抽取次数: {self.picked_count}{repeat_info}"
        
        self.status_label.setText(stats_text)
        
    def set_gender_ui_widget_visible(self):
        self.gender_ui_widget.setVisible(self.gender_checkBox.isChecked())
        self.g_names_pick_checkbox.setChecked(False)
        self.b_names_pick_checkbox.setChecked(False)
        self.pick_name_button.setChecked(False)

    def closeEvent(self, event: QtCore.QEvent) -> None:
        self._stop_recite_timer() # 停止背书计时器
        # 立即停止防抖定时器并强制刷新
        self._debounce_timer.stop()
        if self._save_queue:
            self._flush_all_saves()  # 强制完成挂起的保存
        self.animation_timer.stop()
        
        # 捕获当前所有状态（包括UI控件实时值）
        self._capture_final_state()
        
        # 根据模式执行退出
        if hasattr(self, 'speech_thread') and self.speech_thread and self.speech_thread.isRunning():
            self.speech_thread.quit()
            self.speech_thread.wait()
        
        config = ConfigManager.load_cached()
        if config.get(ConfigManager.KEY_SHOW_FLOATING, True):
            # 如果是悬浮窗模式，确保配置正确
            config[ConfigManager.KEY_FLOATING_MODE] = "floating"
            ConfigManager.save_atomic(config)
            
            # 显示悬浮窗（管理器会自动同步）
            self.trayify_and_show_fw()
            event.ignore()
        else:
            self._perform_full_exit()
            event.accept()

    def _capture_final_state(self):
        """捕获最终状态"""
        # 从UI控件直接读取状态
        config = ConfigManager.load_cached()
        config.update({
            ConfigManager.KEY_PICK_AGAIN: self.pick_again_checkbox.isChecked(),
            ConfigManager.KEY_RECITE_MODE: self.pick_time_checkbox.isChecked(),
            ConfigManager.KEY_GENDER_FILTER: self.current_gender.value,
            ConfigManager.KEY_IS_SAVE: hasattr(self, 'is_saving_results') and self.is_saving_results,
            ConfigManager.KEY_PICK_BALANCED: hasattr(self, 'pick_balanced') and self.pick_balanced,
            
            # 悬浮窗状态必须从管理器获取（最准确）
            ConfigManager.KEY_SHOW_FLOATING: self.is_floating_visible,  #len(self.floating_manager._windows) > 0,
            ConfigManager.KEY_DOUBLE_FLOATING_WINDOW: self.floating_manager.get_window_count() == 2,
        })
        
        # 立即保存
        ConfigManager.save_atomic(config)

    def _perform_full_exit(self) -> None:
        """释放所有资源并终止应用"""
        # ========== 清理单实例服务器 ==========
        self.single_instance_manager.cleanup()
        
        # 保存配置
        self.no_duplicate = self.no_duplicate_cache

        self.request_save('geometry', 'state', 'floating')
        self._flush_all_saves()  # 立即执行，不等待防抖
        try:
            # 立即保存关键配置
            config = ConfigManager.load_cached()
            # ... 更新配置 ...
            ConfigManager.save_atomic(config)
            print("[CLOSE] 配置已立即保存")
        except Exception as e:
            print(f"[CLOSE] 保存失败: {e}")
        
        # 退出事件循环
        QApplication.quit()
        
    def trayify_and_show_fw(self):
        """最小化到托盘并显示悬浮窗：完全委托给管理器"""
        parent_geometry = self.geometry()
        # 隐藏主窗口
        self.hide()
        QApplication.processEvents()
        
        # 确保管理器已初始化
        if not hasattr(self, 'floating_manager'):
            print("[TRAY] 悬浮窗管理器未初始化，忽略")
            return
        
        # ========== 通过管理器同步配置并显示 ==========
        
        # 1. 从当前配置同步悬浮窗状态（自动处理重建/更新）
        config = ConfigManager.load_cached()
        self.floating_manager._sync_configuration(config)
        
        # 2. 显示所有悬浮窗（管理器会自动处理位置）
        self.floating_manager.show_all(parent_geometry)
        
        print("[TRAY] 已切换到悬浮窗模式")
        
    def resizeEvent(self, event):
        """重写窗口大小变化事件处理"""
        super().resizeEvent(event)
        self.request_save('geometry')
        # print(f"窗口尺寸已改变 → 宽度: {current_width}px, 高度: {current_height}px")

    def open_config_page(self):
        """打开配置窗口"""
        if not self.config_window:
            from ConfigPage import ConfigWindow
            self.config_window = ConfigWindow()
            # 连接新信号
            self.config_window.config_applied.connect(self._on_config_applied)
            self.config_window.destroyed.connect(lambda: setattr(self, 'config_window', None))
        
        self.config_window.show()
        self.config_window.raise_()  # 窗口置顶

    def _on_config_applied(self, new_config: dict):
        """配置应用后的快速路径（无需重新加载文件）"""
        print("[CONFIG] 收到配置应用信号，立即同步")

        self.close_button.setVisible(new_config.get(ConfigManager.KEY_SHOW_FLOATING, True))
        
        # 应用防重复设置（带验证）
        old_no_dup = self.no_duplicate
        self.no_duplicate = new_config.get(ConfigManager.KEY_NO_DUPLICATE, 0)
        if old_no_dup != self.no_duplicate:
            self._rebuild_student_pool()
            self.status_label.setText(f"防重复次数已更新: {self.no_duplicate}")

        # 应用语速和音量
        self.speak_speed = new_config.get(ConfigManager.KEY_SPEAK_SPEED, 170)
        
        # 应用动画时长
        self.animation_time = new_config.get(ConfigManager.KEY_ANIMATION_TIME, 0.8)
        
        # 悬浮窗强制同步（携带配置，避免二次加载）
        self.floating_manager._sync_configuration(new_config, force_create=True)
        
        # 静默重置名单
        if ConfigManager.open_text:
            ConfigManager.open_text = False
            self.reset_silently()
        
        # 保存所有状态（几何、状态、悬浮窗）
        self.request_save('geometry', 'state', 'floating')
        self._flush_all_saves()  # 立即执行，不等待防抖
        
        self.status_label.setText("配置已更新")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = PickName()
    
    # 检查是否应该退出（因为已有实例）
    if getattr(window, '_should_exit', False):
        print("[MAIN] 已有实例在运行，退出当前进程")
        sys.exit(0)
    
    # 正常启动
    #if window._data_issues['is_valid']:
    window.show()
    sys.exit(app.exec_())
