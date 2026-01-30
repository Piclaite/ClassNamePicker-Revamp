# PickerConfigManager.py
import binascii
import copy
import hashlib
import json
import os
from pathlib import Path
import time

from PyQt5 import QtWidgets
import bitarray

# 修复名单对话框
class DataFixDialog(QtWidgets.QMessageBox):
    def __init__(self, parent, invalid_names: set):
        super().__init__(parent)
        self.setWindowTitle("名单配置错误")
        self.setIcon(QtWidgets.QMessageBox.Critical)
        
        # 构建详细错误信息
        detail_text = "\n".join(f"{name}" for name in sorted(list(invalid_names)))#[:10]))
        
        self.setText(f"发现 {len(invalid_names)} 个女生名字不在总名单中")
        self.setDetailedText(detail_text)
        
        self.addButton("在总名单中添加", QtWidgets.QMessageBox.YesRole)      # 添加到总名单
        self.addButton("从女生名单删除", QtWidgets.QMessageBox.NoRole)     # 从女生名单删除
        self.addButton("退出程序", QtWidgets.QMessageBox.RejectRole)   # 退出

        self.setDefaultButton(None)

class ConfigManager:
    _config_cache = None
    _last_save_hash = None
    open_text = False  # 标记：是否打开过文本编辑器

    CONFIG_DIR = Path(__file__).parent / "PickNameConfig"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    NAME_CHANGES_FILE = CONFIG_DIR / "name_changes.json"
    NAMES_FILE = CONFIG_DIR / "names.txt"
    G_NAMES_FILE = CONFIG_DIR / "g_names.txt"

    # 配置键名常量
    KEY_IS_SAVE = "is_save"
    KEY_SPEAK_NAME = "speak_name"
    KEY_ANIMATION = "animation"
    KEY_ANIMATION_TIME = "animation_time"
    KEY_FLOATING_X_SIZE = "floating_x_size"
    KEY_FLOATING_Y_SIZE = "floating_y_size"
    KEY_WINDOW_GEOMETRY_QT = "window_geometry_qt"
    KEY_SPEAK_SPEED = "speak_speed"
    KEY_NO_DUPLICATE = "no_duplicate"
    KEY_AUTO_START = "auto_start"
    KEY_SHOW_FLOATING = "show_floating"
    KEY_FLOATING_AUTOSTICK = "floating_autostick"
    KEY_DOUBLE_FLOATING_WINDOW = "double_floating_window"
    KEY_SAVED_AVAILABLE_NAMES = "saved_available_names"
    KEY_PICKED_COUNT = "picked_count"
    KEY_GENDER_FILTER = "gender_filter"
    KEY_RECITE_MODE = "recite_mode"      # 背书模式（计时器）
    KEY_PICK_AGAIN = "pick_again"        # 允许重复抽取
    KEY_PICK_BALANCED = "pick_balanced"  # 确保存在
    KEY_FLOATING_MODE = "floating_mode"   # 运行时模式 "window" or "floating"
    KEY_INTERNAL_REVISION = "_revision"  # 内部修订号
    KEY_FLOATING_IMAGE = "floating_image"  # 图片路径
    
    DEFAULT_CONFIG = {
        KEY_ANIMATION_TIME: 0.8,
        KEY_FLOATING_X_SIZE: 100,
        KEY_FLOATING_Y_SIZE: 100,
        KEY_SPEAK_SPEED: 170,
        KEY_IS_SAVE: False,
        KEY_ANIMATION: True,
        KEY_RECITE_MODE: False,      # 默认关闭背书模式
        KEY_PICK_AGAIN: True,        # 默认允许重复抽取
        KEY_PICK_BALANCED: False,    # 默认关闭均衡模式
        KEY_NO_DUPLICATE: 0,
        KEY_AUTO_START: False,
        KEY_SPEAK_NAME: True,
        KEY_INTERNAL_REVISION: 0,
        KEY_SHOW_FLOATING: True,
        KEY_FLOATING_AUTOSTICK: False,
        KEY_DOUBLE_FLOATING_WINDOW: False,
        KEY_FLOATING_IMAGE: None,  # None表示使用默认文字
        KEY_WINDOW_GEOMETRY_QT: None,
        KEY_SAVED_AVAILABLE_NAMES: [],
        KEY_PICKED_COUNT: 0,
        KEY_GENDER_FILTER: 'unknown',
    }
    
    @classmethod
    def initialize(cls):
        """初始化配置目录和文件"""
        cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # 原子创建默认配置
        if not cls.CONFIG_FILE.exists():
            cls.save_atomic(cls.DEFAULT_CONFIG)
        
        # 创建名单文件
        if not cls.NAMES_FILE.exists():
            cls.NAMES_FILE.write_text("#以井号开头的行不会被读取\n名字1\n名字2\n名字3\n女名1\n女名2\n女名3\n", encoding='utf-8')
        
        if not cls.G_NAMES_FILE.exists():
            cls.G_NAMES_FILE.write_text("#以井号开头的行不会被读取\n女名1\n女名2\n女名3\n", encoding='utf-8')
        
        # 创建多音字配置
        if not cls.NAME_CHANGES_FILE.exists():
            cls.save_name_changes({f'speak_change_{c}': '' for c in 'abc'})
    
    @classmethod
    def load_cached(cls):
        """带缓存的加载"""
        if cls._config_cache is None:
            cls._config_cache = cls._load_internal()
        return copy.deepcopy(cls._config_cache)
    
    @classmethod
    def save_atomic(cls, config: dict):
        """保存和变更检测"""

        config_copy = copy.deepcopy(config)
        config_str = json.dumps(config_copy, ensure_ascii=False, sort_keys=True, indent=2)
        current_hash = hashlib.sha256(config_str.encode('utf-8')).hexdigest()

        if current_hash == cls._last_save_hash:
            print(f"[CONFIG] 配置未更改，取消保存")
            return
        
        if 'recent_bitmap' in config and isinstance(config['recent_bitmap'], bitarray):
            config['recent_bitmap'] = binascii.b2a_base64(
                config['recent_bitmap'].tobytes()
            ).decode('ascii')
        
        config_copy[cls.KEY_INTERNAL_REVISION] = config_copy.get(cls.KEY_INTERNAL_REVISION, 0) + 1

        config_str = json.dumps(config_copy, ensure_ascii=False, sort_keys=True, indent=2)
        
        tmp_file = cls.CONFIG_FILE.with_suffix('.tmp')
        tmp_file.write_text(config_str, encoding='utf-8')
        os.replace(str(tmp_file), str(cls.CONFIG_FILE))

        cls._config_cache = config_copy
        cls._last_save_hash = hashlib.sha256(config_str.encode('utf-8')).hexdigest()
        print(f"[CONFIG] 配置已保存，修订号: {config_copy[cls.KEY_INTERNAL_REVISION]}")
    
    @classmethod
    def _load_internal(cls):
        """内部加载"""
        try:
            text = cls.CONFIG_FILE.read_text(encoding='utf-8')
            config = json.loads(text)
            # 版本迁移
            config = {**cls.DEFAULT_CONFIG, **config}
            cls.save_atomic(config)
            return config
        except Exception:
            return cls.DEFAULT_CONFIG.copy()
    
    @classmethod
    def get_name_count(cls):
        """获取总名单人数（从 ConfigPage 移入）"""
        try:
            return sum(1 for line in cls.NAMES_FILE.read_text(encoding='utf-8-sig').splitlines() 
                      if line.strip() and not line.strip().startswith('#'))
        except Exception:
            return 1
    
    @classmethod
    def save_name_changes(cls, data):
        """保存多音字配置"""
        cls.NAME_CHANGES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    @classmethod
    def load_name_changes(cls):
        """加载多音字配置"""
        try:
            return json.loads(cls.NAME_CHANGES_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {f'speak_change_{c}': '' for c in 'abc'}
        

    @classmethod
    def _quick_fix_name_file(cls, fix_type: str) -> tuple[bool, str]:
        """
        核心修复逻辑
        :param fix_type: 'add_to_all' 或 'remove_from_girl'
        :return: (是否成功, 操作详情)
        """
        if fix_type not in ('add_to_all', 'remove_from_girl'):
            raise ValueError(f"无效的修复类型: {fix_type}")

        # 1. 强制备份
        backup_dir = cls.CONFIG_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        try:
            # 读取数据
            all_names = {line.strip() for line in cls.NAMES_FILE.read_text(encoding='utf-8').splitlines() 
                        if line.strip() and not line.startswith('#')}
            g_names = {line.strip() for line in cls.G_NAMES_FILE.read_text(encoding='utf-8').splitlines() 
                      if line.strip() and not line.startswith('#')}
            
            invalid = g_names - all_names
            if not invalid:
                return True, "无需修复"
            
            # 2. 执行修复（带备份）
            if fix_type == 'add_to_all':
                # 使用pathlib备份
                backup_path = backup_dir / f"names_backup_{timestamp}.txt"
                backup_path.write_bytes(cls.NAMES_FILE.read_bytes())
                
                # 修改文件
                valid = all_names | invalid
                cls.NAMES_FILE.write_text('\n'.join(['#以井号开头的行不会被读取'] + sorted(valid)), encoding='utf-8')
                return True, f"已添加 {len(invalid)} 个名字到总名单"
            
            else:  # 'remove_from_girl'
                # 使用pathlib备份
                backup_path = backup_dir / f"g_names_backup_{timestamp}.txt"
                backup_path.write_bytes(cls.G_NAMES_FILE.read_bytes())
                
                # 修改文件
                valid = g_names & all_names
                cls.G_NAMES_FILE.write_text('\n'.join(['#以井号开头的行不会被读取'] + sorted(valid)), encoding='utf-8')
                return True, f"已从女生名单删除 {len(invalid)} 个无效名字"
                
        except Exception as e:
            return False, f"修复失败: {str(e)}"