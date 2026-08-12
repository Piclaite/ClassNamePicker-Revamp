# StudentModels.py
from dataclasses import dataclass
from enum import Enum
from typing import Set, List, Dict, Deque, Optional
from collections import deque
import random

class Gender(Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"
    
@dataclass(frozen=True)
class Student:
    original_name: str
    display_name: str
    gender: Gender
    
    __slots__ = ('original_name', 'display_name', 'gender')  # 内存优化

    def __hash__(self):
        return hash(self.original_name)
    
    def __eq__(self, other):
        return isinstance(other, Student) and self.original_name == other.original_name

class StudentPool:
    """学生池（列表+集合+队列优化版）- 融合Set方案与冷却队列设计"""
    __slots__ = (
        '_students',           # List[Student]: 只读学生列表（索引即ID）
        '_name_to_idx',        # Dict[str, int]: 名字到索引映射
        '_female_indices',     # Set[int]: 女生索引集合（O(1)判断性别）
        '_available',          # List[int]: 可用学生索引列表（供random.choice）
        '_available_set',      # Set[int]: 可用索引集合（O(1)判断存在性）
        '_cooling',            # Deque[int]: 冷却队列（存最近抽取的索引）
        '_no_duplicate',       # int: 防重复次数（0表示不防重复）
        '_gender_cache',       # Optional[Gender]: 当前缓存的性别筛选条件
        '_gender_candidates',  # Optional[List[int]]: 性别筛选结果缓存
    )

    def __init__(self, all_students: List[Student], female_students: List[Student], no_duplicate: int = 0):
        if not all_students:
            raise ValueError("学生名单不能为空")
        
        total = len(all_students)
        
        # 1. 建立主索引（索引即ID，稳定不变）
        self._students = all_students
        self._name_to_idx = {s.original_name: i for i, s in enumerate(all_students)}
        
        # 2. 性别标记（使用集合实现O(1)判断）
        female_names = {s.original_name for s in female_students}
        self._female_indices = {idx for name, idx in self._name_to_idx.items() if name in female_names}
        
        # 3. 初始化可用池（全部可用）
        self._available = list(range(total))
        self._available_set = set(self._available)  # 镜像集合，加速存在性判断
        
        # 4. 初始化冷却队列（maxlen自动处理溢出）
        self._no_duplicate = max(0, min(no_duplicate, total - 1))  # 防重复不能超过总人数-1
        self._cooling: Deque[int] = deque(maxlen=self._no_duplicate) if self._no_duplicate > 0 else deque()
        
        # 5. 性别筛选缓存（避免重复计算）
        self._gender_cache: Optional[Gender] = None
        self._gender_candidates: Optional[List[int]] = None

    def pick(self, gender: Gender = Gender.UNKNOWN, remove: bool = True) -> str:
        """抽取学生（核心优化：缓存+O(1)维护）"""
        candidates = self._get_candidates(gender)
        
        if not candidates:
            raise IndexError(f"无可用的{gender.value}学生")
        
        # 随机选择（使用索引避免对象拷贝开销）
        idx = random.choice(candidates)
        student = self._students[idx]
        
        if remove:
            # 从可用池移除（O(1)交换删除）
            self._remove_available_fast(idx)
            
            # 冷却队列处理（如果启用防重复）
            if self._no_duplicate > 0:
                # 队列满时，最老的自动移回可用池（deque的FIFO特性）
                if len(self._cooling) >= self._no_duplicate:
                    oldest_idx = self._cooling.popleft()  # O(1)
                    self._add_available_fast(oldest_idx)
                
                self._cooling.append(idx)
            
            # 数据变更，缓存失效
            self._invalidate_cache()
        
        return student.display_name

    def _get_candidates(self, gender: Gender) -> List[int]:
        """获取候选索引（带智能缓存）"""
        if gender == self._gender_cache and self._gender_candidates is not None:
            return self._gender_candidates
        
        if gender == Gender.UNKNOWN:
            indices = self._available
        elif gender == Gender.FEMALE:
            # 利用集合交集快速筛选（保持_available顺序）
            indices = [i for i in self._available if i in self._female_indices]
        else:  # MALE
            indices = [i for i in self._available if i not in self._female_indices]
        
        self._gender_cache = gender
        self._gender_candidates = indices
        return indices

    def _remove_available_fast(self, idx: int):
        """O(1)时间从可用池移除（交换删除法）"""
        if idx not in self._available_set:
            return
        
        self._available_set.remove(idx)
        
        # 交换删除：将待删元素与最后一个交换，然后pop（避免中间删除的O(n)移动）
        # 注意：这会改变_available的顺序，但random.choice不关心顺序
        pos = self._available.index(idx)
        last_pos = len(self._available) - 1
        if pos != last_pos:
            self._available[pos] = self._available[last_pos]
        self._available.pop()

    def _add_available_fast(self, idx: int):
        """O(1)时间添加回可用池"""
        if idx in self._available_set:
            return
        self._available.append(idx)
        self._available_set.add(idx)

    def _invalidate_cache(self):
        """清空性别筛选缓存（池子变化时调用）"""
        self._gender_cache = None
        self._gender_candidates = None

    def reset(self, gender: Gender = Gender.UNKNOWN):
        """重置名单（支持分性别重置）"""
        if gender == Gender.UNKNOWN:
            # 全量重置
            self._available = list(range(len(self._students)))
            self._available_set = set(self._available)
            self._cooling.clear()
        elif gender == Gender.FEMALE:
            # 仅重置女生：将不在可用池且不在冷却中的女生加回
            to_add = [i for i in self._female_indices 
                     if i not in self._available_set and i not in self._cooling]
            for i in to_add:
                self._add_available_fast(i)
        else:  # MALE
            all_indices = set(range(len(self._students)))
            male_indices = all_indices - self._female_indices
            to_add = [i for i in male_indices 
                     if i not in self._available_set and i not in self._cooling]
            for i in to_add:
                self._add_available_fast(i)
        
        self._invalidate_cache()

    ### ===== 数据导出/恢复接口（与原程序完全兼容） =====

    def get_available_names(self) -> Set[str]:
        """获取可用学生名字的集合（用于配置保存）"""
        return {self._students[i].original_name for i in self._available}

    def get_picked_names(self) -> Set[str]:
        """获取已抽取学生名字的集合"""
        all_names = {s.original_name for s in self._students}
        available_names = self.get_available_names()
        # 已抽取 = 全部 - 可用（包括冷却中的，因为冷却中确实不可抽）
        return all_names - available_names

    def restore_available_names(self, names: Set[str]):
        """从历史配置恢复可用状态"""
        # 清空重建
        self._available.clear()
        self._available_set.clear()
        self._cooling.clear()
        
        for name in names:
            idx = self._name_to_idx.get(name)
            if idx is not None:
                self._add_available_fast(idx)
        
        self._invalidate_cache()

    ### ===== 统计与属性接口 =====

    def get_stats(self, gender: Gender = Gender.UNKNOWN) -> tuple[int, int, int]:
        """统计 (总数, 可用数, 已抽数)"""
        if gender == Gender.UNKNOWN:
            total = len(self._students)
            available = len(self._available)
            picked = total - available
        elif gender == Gender.FEMALE:
            total = len(self._female_indices)
            available = len([i for i in self._available if i in self._female_indices])
            picked = total - available
        else:  # MALE
            male_indices = set(range(len(self._students))) - self._female_indices
            total = len(male_indices)
            available = len([i for i in self._available if i in male_indices])
            picked = total - available
        
        return total, available, picked

    @property
    def no_duplicate(self) -> int:
        """防重复次数（0表示关闭防重复）"""
        return self._no_duplicate

    @no_duplicate.setter
    def no_duplicate(self, value: int):
        """动态调整防重复次数（自动处理队列溢出）"""
        new_val = max(0, value)
        if new_val == self._no_duplicate:
            return
        
        old_cooling = list(self._cooling)
        
        if new_val > self._no_duplicate:
            # 扩容：直接重建deque，保留现有数据
            self._cooling = deque(old_cooling, maxlen=new_val)
        else:
            # 缩容：将多出的老元素移回可用池（先进先出，移出最老的）
            if new_val == 0:
                # 关闭防重复：全部移回
                for idx in old_cooling:
                    self._add_available_fast(idx)
                self._cooling = deque()
            else:
                # 保留最新的new_val个，其余移回
                excess = old_cooling[:-new_val]  # 老的部分
                keep = old_cooling[-new_val:]    # 新的部分
                
                for idx in excess:
                    self._add_available_fast(idx)
                
                self._cooling = deque(keep, maxlen=new_val)
        
        self._no_duplicate = new_val
        self._invalidate_cache()

    ### ===== 辅助方法（可选） =====

    def get_student_by_name(self, name: str) -> Optional[Student]:
        """通过名字获取学生对象（兼容原接口）"""
        idx = self._name_to_idx.get(name)
        return self._students[idx] if idx is not None else None
    
    def get_all_students(self) -> List[Student]:
        """获取所有学生列表（兼容原接口）"""
        return self._students
    
    def get_female_students(self) -> List[Student]:
        """获取女生列表（兼容原接口）"""
        return [self._students[i] for i in self._female_indices]