"""逻辑时钟与因果序内核：Lamport 时钟、向量时钟、事件与因果历史。

计数、节点标识与事件先后全部由调用方注入的整数和字符串决定：内核不读
真实时钟、不取随机数、不做 I/O、不打印，同样的输入序列永远得到同样的结果。
"""

EQUAL = "equal"
BEFORE = "before"
AFTER = "after"
CONCURRENT = "concurrent"


class ClockError(ValueError):
    """计数、步长、节点标识或输入形状不合法时抛出。"""


def _is_int(value):
    """是否为真整数（布尔值不算）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_counter(value, label):
    """把 value 校验为非负整数并返回。"""
    if not _is_int(value):
        raise ClockError("%s 必须是整数" % label)
    if value < 0:
        raise ClockError("%s 不能为负" % label)
    return int(value)


def _check_node(node):
    """把 node 校验为非空节点标识并返回。"""
    node = "" if node is None else str(node)
    if not node:
        raise ClockError("节点标识不能为空")
    return node


def _check_stable(stable):
    """把稳定边界校验成节点到计数的普通映射。"""
    if hasattr(stable, "to_dict"):
        stable = stable.to_dict()
    if not isinstance(stable, dict):
        raise ClockError("稳定边界必须是节点到计数的映射")
    return stable


def compare_vectors(left, right):
    """按节点标识逐个分量比较两个映射的先后与并发。

    只有两侧在每个分量上都不落后、且至少一个分量领先，才算严格先后。
    """
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ClockError("比较的两侧都必须是节点到计数的映射")
    ahead = False
    behind = False
    for node in sorted(set(left) | set(right)):
        mine = int(left.get(node, 0))
        theirs = int(right.get(node, 0))
        if mine > theirs:
            ahead = True
        elif mine < theirs:
            behind = True
    if ahead and behind:
        return CONCURRENT
    if ahead:
        return AFTER
    if behind:
        return BEFORE
    return EQUAL


class LamportClock:
    """单个节点的逻辑时间戳：只前进，合并取较大值。"""

    __slots__ = ("node", "_value")

    def __init__(self, node="", value=0):
        self.node = str(node)
        self._value = _check_counter(value, "初始计数")

    @property
    def value(self):
        """当前逻辑时间戳。"""
        return self._value

    def copy(self):
        """一份独立的副本。"""
        return LamportClock(self.node, self._value)

    def tick(self, step=1):
        """向前推进 step 格并返回新的时间戳。"""
        step = _check_counter(step, "步长")
        if step <= 0:
            raise ClockError("逻辑时钟只能向前推进")
        self._value += step
        return self._value

    def observe(self, remote):
        """把收到的远端时间戳折进来并推进一格。"""
        remote = _check_counter(remote, "收到的计数")
        self._value = max(self._value, int(remote)) + 1
        return self._value

    def merge(self, other):
        """把另一个时钟折进来，不额外推进。"""
        if not isinstance(other, LamportClock):
            raise ClockError("只能与另一个 Lamport 时钟合并")
        self._value = max(self._value, other.value)
        return self

    def is_earlier_than(self, other):
        """本时间戳是否严格早于另一个时间戳。"""
        if not isinstance(other, LamportClock):
            raise ClockError("只能与另一个 Lamport 时钟比较先后")
        return self._value < other.value

    def __repr__(self):
        return "LamportClock(%r, value=%r)" % (self.node, self._value)


class VectorClock:
    """向量时钟：记录从每个节点见过的最高计数。"""

    __slots__ = ("_entries",)

    def __init__(self, entries=None):
        if entries is not None and not isinstance(entries, dict):
            raise ClockError("向量时钟的初始值必须是节点到计数的映射")
        self._entries = {}
        for node, counter in (entries or {}).items():
            self._entries[_check_node(node)] = _check_counter(counter, "计数")

    def copy(self):
        """一份独立的副本。"""
        return VectorClock(self._entries)

    def to_dict(self):
        """按稳定节点次序导出的普通映射。"""
        return {node: self._entries[node] for node in self.nodes()}

    def nodes(self):
        """出现过的节点标识，按稳定次序排列。"""
        return tuple(sorted(self._entries))

    def get(self, node):
        """某个节点的计数，没记录过就是零。"""
        return self._entries.get(str(node), 0)

    def bump(self, node):
        """把某个节点的计数推进一格并返回新值。"""
        node = _check_node(node)
        self._entries[node] = self.get(node) + 1
        return self._entries[node]

    def observe(self, node, counter):
        """折入一个远端分量；变大了才返回真。"""
        node = _check_node(node)
        counter = _check_counter(counter, "计数")
        if counter <= self.get(node):
            return False
        self._entries[node] = counter
        return True

    def merge(self, other):
        """把另一个向量时钟逐分量折进来。"""
        if not isinstance(other, VectorClock):
            raise ClockError("只能与另一个向量时钟合并")
        for node, counter in other.to_dict().items():
            self.observe(node, counter)
        return self

    def relation(self, other):
        """把本时钟相对另一个时钟分类。"""
        if not isinstance(other, VectorClock):
            raise ClockError("只能与另一个向量时钟比较")
        return compare_vectors(self._entries, other.to_dict())

    def dominates(self, other):
        """本时钟是否严格压过另一个时钟。"""
        return self.relation(other) == AFTER

    def concurrent_with(self, other):
        """两个时钟是否互为并发。"""
        return self.relation(other) == CONCURRENT

    def __repr__(self):
        return "VectorClock(%r)" % (self.to_dict(),)


class Event:
    """一个事件：所属节点、节点内计数、逻辑时间戳与当时的向量时钟。"""

    __slots__ = ("node", "counter", "lamport", "vector", "label")

    def __init__(self, node, counter, lamport, vector=None, label=""):
        self.node = _check_node(node)
        self.counter = _check_counter(counter, "事件计数")
        if self.counter <= 0:
            raise ClockError("事件计数从 1 起")
        self.lamport = _check_counter(lamport, "逻辑时间戳")
        if vector is not None and not isinstance(vector, dict):
            raise ClockError("事件的向量必须是节点到计数的映射")
        self.vector = {}
        for key, value in (vector or {}).items():
            self.vector[_check_node(key)] = _check_counter(value, "向量分量")
        self.label = str(label)

    def __lt__(self, other):
        """事件之间的全序：先比逻辑时间戳。"""
        if not isinstance(other, Event):
            raise ClockError("只能在同一类事件之间排序")
        if self.lamport != other.lamport:
            return self.lamport < other.lamport
        if self.node != other.node:
            return self.node < other.node
        return self.counter < other.counter

    def causally_before(self, other):
        """本事件是否因果先于另一个事件。"""
        if not isinstance(other, Event):
            raise ClockError("只能比较同一类事件")
        return compare_vectors(self.vector, other.vector) == BEFORE

    def __repr__(self):
        return "Event(%r, counter=%r, lamport=%r, label=%r)" % (
            self.node, self.counter, self.lamport, self.label)


def order_events(events):
    """把事件排成全序：逻辑时间在前，节点标识打破平局。"""
    ordered = list(events or ())
    for event in ordered:
        if not isinstance(event, Event):
            raise ClockError("排序的每一项都必须是事件")
    return tuple(sorted(ordered))


class History:
    """一个节点保留的因果历史：按记录顺序保存，可安全裁剪。"""

    __slots__ = ("_events",)

    def __init__(self, events=None):
        self._events = []
        for event in events or ():
            self.record(event)

    def record(self, event):
        """记录一个事件并返回它。"""
        if not isinstance(event, Event):
            raise ClockError("历史里只能记录事件")
        self._events.append(event)
        return event

    def events(self):
        """目前保留的事件，按记录顺序。"""
        return tuple(self._events)

    def covered(self, event, stable):
        """稳定边界是否已经覆盖这个事件的因果历史。

        stable 是每个节点都已经交付到的计数；只有事件向量的每个分量都
        不超过 stable 的对应计数时，这个事件才可以被安全忘记。
        """
        if not isinstance(event, Event):
            raise ClockError("只能判断事件是否被覆盖")
        stable = _check_stable(stable)
        for node, counter in event.vector.items():
            if int(counter) > int(stable.get(node, 0)):
                return False
        return True

    def trim(self, stable):
        """丢掉已被稳定边界完全覆盖的事件，返回丢掉的条数。"""
        stable = _check_stable(stable)
        kept = []
        pruned = 0
        for event in self._events:
            if self.covered(event, stable):
                pruned += 1
            else:
                kept.append(event)
        self._events = kept
        return pruned

    def __len__(self):
        return len(self._events)

    def __repr__(self):
        return "History(%r)" % (self.events(),)


class Node:
    """一个参与者：自己的 Lamport 时钟、向量时钟与因果历史。"""

    __slots__ = ("node_id", "clock", "vector", "history")

    def __init__(self, node_id):
        self.node_id = _check_node(node_id)
        self.clock = LamportClock(self.node_id)
        self.vector = VectorClock()
        self.history = History()

    @property
    def lamport(self):
        """当前的逻辑时间戳。"""
        return self.clock.value

    def local_event(self, label=""):
        """记录一个本地事件并返回它。"""
        lamport = self.clock.tick()
        counter = self.vector.bump(self.node_id)
        event = Event(self.node_id, counter, lamport, self.vector.to_dict(), label)
        self.history.record(event)
        return event

    def receive(self, event):
        """折入一个远端事件；接收本身也算一个本地事件。"""
        if not isinstance(event, Event):
            raise ClockError("只能接收事件对象")
        lamport = self.clock.observe(event.lamport)
        self.vector.observe(event.node, event.counter)
        counter = self.vector.bump(self.node_id)
        receipt = Event(self.node_id, counter, lamport, self.vector.to_dict(),
                        "recv:" + event.label)
        self.history.record(receipt)
        return receipt

    def merge(self, other):
        """状态式同步：折入另一个节点的时钟与历史。"""
        if not isinstance(other, Node):
            raise ClockError("只能与另一个节点合并")
        self.clock.merge(other.clock)
        self.vector.merge(other.vector)
        for event in other.history.events():
            self.history.record(event)
        return self

    def events(self):
        """本节点保留的事件，按记录顺序。"""
        return self.history.events()

    def snapshot(self):
        """可比较的状态摘要。"""
        return {
            "node": self.node_id,
            "lamport": self.lamport,
            "vector": self.vector.to_dict(),
            "labels": tuple(event.label for event in self.history.events()),
        }

    def __repr__(self):
        return "Node(%r, lamport=%r)" % (self.node_id, self.lamport)
