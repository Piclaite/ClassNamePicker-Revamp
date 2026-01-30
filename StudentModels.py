from dataclasses import dataclass
from enum import Enum
from typing import Set, List
from collections import deque
import random
from bitarray import bitarray

class Gender(Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"
    
@dataclass(frozen=True)
class Student:
    original_name: str
    display_name: str
    gender: Gender
    
    __slots__ = ('original_name', 'display_name', 'gender')  # 保持内存优化

    def __hash__(self):
        return hash(self.original_name)
    
    def __eq__(self, other):
        return isinstance(other, Student) and self.original_name == other.original_name

class StudentPool:
    """学生池（位图存储状态）"""
    __slots__ = (
        '_students',           # List[Student]: 只读学生列表（按索引存储）
        '_name_to_idx',        # Dict[str, int]: 名字到索引的映射
        '_female_bitmap',      # bitarray: 女生标记位图 (0->男, 1->女)
        '_bit_available',      # BitArray: 可用状态位图
        '_bit_picked',         # BitArray: 已抽取状态位图
        '_no_duplicate',       # int: 防重复次数
        '_recent_bitmap',      # bitarray: 最近抽取标记（替代deque）
        '_recent_queue'        # deque[int]: 最近抽取索引队列
    )


    def __init__(self, all_students: List[Student], female_students: List[Student], no_duplicate: int = 0):
        if not all_students:
            raise ValueError("学生名单不能为空")
        
        total = len(all_students)

        # 1. 唯一存储：学生列表（有序，索引即ID）
        self._students = all_students
        self._name_to_idx = {s.original_name: idx for idx, s in enumerate(all_students)}
        
        # 2. 女生位图（核心优化）
        self._female_bitmap = bitarray(total)
        self._female_bitmap.setall(0)  # 默认全为男生
        for s in female_students:
            if s.original_name in self._name_to_idx:
                self._female_bitmap[self._name_to_idx[s.original_name]] = 1
        
        # 3. 位图状态
        # 使用bitarray
        self._bit_available = bitarray(total)
        self._bit_available.setall(True)  # 初始全可用
        self._bit_picked = bitarray(total)
        self._bit_picked.setall(False)    # 初始全未抽取
        
        # 4. 防重复队列（存储索引而非字符串,用bitarray优化查找）
        self._no_duplicate = max(0, no_duplicate)
        self._recent_queue = deque(maxlen=no_duplicate if no_duplicate > 0 else None)
        self._recent_bitmap = bitarray(total)
        self._recent_bitmap.setall(False)

    def pick(self, gender: Gender = Gender.UNKNOWN, remove: bool = True) -> str:
        """抽取学生（位图优化版：避免构建完整列表）"""
        # 1. 获取候选位图（保持原有逻辑）
        candidates = self._get_candidate_bitmap(gender)
        
        # 2. 排除最近抽取（位图减法）
        if self._no_duplicate > 0:
            candidates &= ~self._recent_bitmap
        
        # 3. 统计可用数量
        available_count = candidates.count(True)
        if available_count == 0:
            raise IndexError(f"无可用的{gender.value}学生")
        
        # 4. 随机选择第 k 个（0-indexed），无需构建列表
        target = random.randint(0, available_count - 1)
        
        # 5. 直接遍历找到第 target 个置位位（O(n) 但无内存分配）
        # 使用 enumerate + 计数器，比 itersearch 更快（避免迭代器开销）
        count = 0
        for idx, is_available in enumerate(candidates):
            if is_available:
                if count == target:
                    picked_idx = idx
                    break
                count += 1
        
        # 6. 更新状态
        if remove:
            self._bit_available[picked_idx] = False
            self._bit_picked[picked_idx] = True
        
        # 7. 优化防重复位图更新（避免全清重设）
        if self._no_duplicate > 0:
            if len(self._recent_queue) >= self._no_duplicate:
                # 队列满时，只清除最旧的一个，而非全部重建
                oldest_idx = self._recent_queue.popleft()
                self._recent_bitmap[oldest_idx] = False
            
            self._recent_queue.append(picked_idx)
            self._recent_bitmap[picked_idx] = True
        
        return self._students[picked_idx].display_name

    def reset(self, gender: Gender = Gender.UNKNOWN):
        """重置名单（位图批量操作）"""
        if gender == Gender.UNKNOWN:
            self._bit_available.setall(True)
            self._bit_picked.setall(False)
        else:
            # 按性别重置（位图条件赋值）
            mask = self._female_bitmap if gender == Gender.FEMALE else ~self._female_bitmap
            self._bit_available |= mask
            self._bit_picked &= ~mask
        
        # 清空防重复
        self._recent_queue.clear()
        self._recent_bitmap.setall(False)
    
    ### ===== 数据导出/恢复接口 =====
    
    def get_available_names(self) -> Set[str]:
        """获取可用名字集合（用于保存）"""
        return {self._students[i].original_name for i in range(len(self._students)) if self._bit_available[i]}

    def get_picked_names(self) -> Set[str]:
        """获取已抽取名字集合（用于重建）"""
        return {self._students[i].original_name for i in range(len(self._students)) if self._bit_picked[i]}

    def restore_available_names(self, names: Set[str]):
        """从历史名单恢复位图状态（配置加载）"""
        # 先设为全不可用（相当于全部已抽取）
        self._bit_available.setall(False)
        self._bit_picked.setall(True)
        
        # 将传入的可用名单恢复为可用状态
        if names:
            for name in names:
                idx = self._name_to_idx.get(name)
                if idx is not None:
                    self._bit_available[idx] = True
                    self._bit_picked[idx] = False

    ### ===== 数据访问接口 =====
    
    def get_all_students(self) -> List[Student]:
        """获取所有学生列表"""
        return self._students
    
    def get_female_students(self) -> List[Student]:
        """获取女生对象列表"""
        return [self._students[idx] for idx in self._female_bitmap.search(bitarray('1'))]

    def get_student_by_name(self, name: str) -> Student:
        """通过名字获取学生对象"""
        idx = self._name_to_idx.get(name)
        return self._students[idx] if idx is not None else None
    
    def get_stats(self, gender: Gender = Gender.UNKNOWN) -> tuple:
        """统计（位图快速计数）"""
        if gender == Gender.UNKNOWN:
            total = len(self._students)
            available = self._bit_available.count(True)
            picked = self._bit_picked.count(True)
        else:
            # 按性别统计（位图与运算后计数）
            gender_mask = self._female_bitmap if gender == Gender.FEMALE else ~self._female_bitmap
            total = gender_mask.count(True)
            available = (self._bit_available & gender_mask).count(True)
            picked = (self._bit_picked & gender_mask).count(True)
        
        return total, available, picked
    
    ### ===== 内部辅助方法 =====
        
    def _get_candidate_bitmap(self, gender: Gender) -> bitarray:
        """获取候选位图（位图运算）"""
        if gender == Gender.UNKNOWN:
            return self._bit_available.copy()
        
        # 按性别过滤（位图与运算）
        if gender == Gender.FEMALE:
            return self._bit_available & self._female_bitmap
        else:  # MALE
            return self._bit_available & ~self._female_bitmap
    
    ### ===== 属性访问器 =====
    
    @property
    def no_duplicate(self) -> int:
        return self._no_duplicate
    
    @no_duplicate.setter
    def no_duplicate(self, value: int):
        """动态修改防重复次数"""
        self._no_duplicate = max(0, value)
        
        # 重建队列
        if self._no_duplicate > 0:
            current = list(self._recent_queue)
            self._recent_queue = deque(maxlen=self._no_duplicate)
            self._recent_queue.extend(current[-self._no_duplicate:])
            
            # 重建位图
            self._recent_bitmap.setall(False)
            for idx in self._recent_queue:
                self._recent_bitmap[idx] = True
        else:
            self._recent_queue.clear()
            self._recent_bitmap.setall(False)