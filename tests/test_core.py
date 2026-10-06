"""逻辑时钟与因果序内核的行为测试。

期望值全部写成结果本身：时间戳、分类结果、事件顺序与裁剪计数。
在项目根目录执行：

    python3 -m unittest discover -s tests -v
"""

import unittest

from clock.core import (
    AFTER,
    BEFORE,
    CONCURRENT,
    EQUAL,
    ClockError,
    Event,
    History,
    LamportClock,
    Node,
    VectorClock,
    order_events,
)


class KernelCase(unittest.TestCase):
    """共用小工具：把不该出现的异常也转成断言失败。"""

    def value(self, label, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - 内核抛错本身就说明行为不对
            self.fail("%s 抛出了 %s: %s" % (label, type(error).__name__, error))

    def refuses(self, error_type, label, function, *args, **kwargs):
        try:
            function(*args, **kwargs)
        except error_type:
            return
        except Exception as error:  # noqa: BLE001 - 报错类型不对同样算行为不对
            self.fail("%s 抛出了 %s: %s，期望 %s"
                      % (label, type(error).__name__, error, error_type.__name__))
        self.fail("%s 没有报错，期望 %s" % (label, error_type.__name__))


class StampTests(KernelCase):
    """Lamport 时间戳的推进与先后。"""

    def test_01_stamps_only_move_forward(self):
        clock = LamportClock("a", value=4)
        self.assertEqual(clock.tick(), 5)
        self.assertEqual(clock.observe(9), 10)
        self.assertEqual(clock.observe(2), 11)
        self.assertEqual(clock.value, 11)

        node = Node("n")
        remote = Node("m")
        old = remote.local_event("old")
        self.assertEqual(old.lamport, 1)
        stamps = [node.local_event("t%d" % index).lamport for index in range(4)]
        self.assertEqual(stamps, [1, 2, 3, 4])
        receipt = node.receive(old)
        self.assertEqual(receipt.lamport, 5)
        later = node.local_event("after")
        self.assertEqual(later.lamport, 6)
        sequence = stamps + [receipt.lamport, later.lamport]
        self.assertEqual(sorted(sequence), sequence)
        self.assertEqual(len(set(sequence)), len(sequence))
        self.assertFalse(node.clock.is_earlier_than(node.clock.copy()))

    def test_02_equal_stamps_are_not_ordered(self):
        first = LamportClock("a", value=3)
        second = LamportClock("b", value=3)
        self.assertFalse(first.is_earlier_than(second))
        self.assertFalse(second.is_earlier_than(first))
        self.assertFalse(first.is_earlier_than(first.copy()))
        self.assertTrue(LamportClock("a", 2).is_earlier_than(first))
        self.assertTrue(first.is_earlier_than(LamportClock("b", 4)))
        self.assertEqual(LamportClock("a", 3).merge(LamportClock("b", 8)).value, 8)
        self.assertEqual(LamportClock("a", 9).merge(LamportClock("b", 8)).value, 9)


class VectorClockTests(KernelCase):
    """向量时钟的合并、比较、压过判定与节点次序。"""

    def test_03_merge_takes_pointwise_maximum(self):
        local = VectorClock({"a": 2})
        remote = VectorClock({"a": 2, "b": 1})
        self.value("合并", local.merge, remote)
        self.assertEqual(local.to_dict(), {"a": 2, "b": 1})
        self.value("再次合并", local.merge, remote)
        self.assertEqual(local.to_dict(), {"a": 2, "b": 1})
        self.assertEqual(local.relation(remote), EQUAL)
        self.assertEqual(remote.relation(local), EQUAL)
        self.assertEqual(VectorClock({"a": 2}).relation(remote), BEFORE)
        self.assertEqual(remote.relation(VectorClock({"a": 2})), AFTER)
        merged = self.value("链式合并",
                            VectorClock({"a": 1, "b": 5}).merge,
                            VectorClock({"a": 4, "c": 2}))
        self.assertEqual(merged.to_dict(), {"a": 4, "b": 5, "c": 2})

        left = Node("a")
        right = Node("b")
        first = left.local_event("x")
        right.receive(first)
        left.merge(right)
        self.assertEqual(left.vector.to_dict(), {"a": 1, "b": 1})
        self.assertEqual(left.lamport, 2)
        self.assertEqual(len(left.events()), 2)

    def test_04_causal_order_is_transitive(self):
        first = VectorClock({"a": 1})
        middle = VectorClock({"a": 1, "b": 1})
        last = VectorClock({"a": 2, "b": 1, "c": 3})
        self.assertEqual(first.relation(middle), BEFORE)
        self.assertEqual(middle.relation(last), BEFORE)
        self.assertEqual(first.relation(last), BEFORE)
        self.assertEqual(last.relation(first), AFTER)
        self.assertEqual(first.relation(last.copy()), BEFORE)
        self.assertEqual(first.relation(first.copy()), EQUAL)
        self.assertFalse(first.dominates(middle))
        self.assertTrue(last.dominates(middle))
        self.assertFalse(middle.dominates(last))

        c1 = Event("c", 1, 1, {"c": 1}, "c1")
        a1 = Event("a", 1, 3, {"c": 1, "a": 1}, "a1")
        b2 = Event("b", 2, 4, {"c": 1, "a": 1, "b": 2}, "b2")
        self.assertTrue(c1.causally_before(a1))
        self.assertTrue(a1.causally_before(b2))
        self.assertTrue(c1.causally_before(b2))
        self.assertFalse(b2.causally_before(c1))
        self.assertFalse(c1.causally_before(c1))

    def test_05_concurrency_is_symmetric(self):
        left = VectorClock({"a": 3, "b": 1})
        right = VectorClock({"a": 1, "b": 3})
        self.assertEqual(left.relation(right), CONCURRENT)
        self.assertEqual(right.relation(left), CONCURRENT)
        self.assertTrue(left.concurrent_with(right))
        self.assertTrue(right.concurrent_with(left))
        self.assertFalse(left.dominates(right))
        self.assertFalse(right.dominates(left))
        self.assertEqual(VectorClock({"a": 2}).relation(VectorClock({"a": 2, "b": 1})),
                         BEFORE)
        self.assertEqual(VectorClock({"a": 2, "b": 1}).relation(VectorClock({"a": 2})),
                         AFTER)
        self.assertFalse(VectorClock({"a": 2}).concurrent_with(VectorClock({"a": 2, "b": 1})))

    def test_06_dominance_requires_strictly_later_clock(self):
        base = VectorClock({"a": 2, "b": 1})
        self.assertTrue(VectorClock({"a": 3, "b": 1}).dominates(base))
        self.assertTrue(VectorClock({"a": 2, "b": 2}).dominates(base))
        self.assertTrue(VectorClock({"a": 2, "b": 1, "c": 1}).dominates(base))
        self.assertFalse(base.dominates(base.copy()))
        self.assertFalse(VectorClock().dominates(base))
        self.assertFalse(base.dominates(VectorClock({"a": 1, "b": 5})))
        self.assertFalse(base.dominates(VectorClock({"a": 3})))

    def test_07_node_ids_have_a_stable_order(self):
        clock = VectorClock()
        for node in ("c", "aa", "b", "node-10", "node-9"):
            clock.bump(node)
        expected = ("aa", "b", "c", "node-10", "node-9")
        self.assertEqual(clock.nodes(), expected)
        self.assertEqual(tuple(clock.to_dict()), expected)
        other = VectorClock()
        for node in ("node-9", "node-10", "c", "aa", "b"):
            other.bump(node)
        self.assertEqual(other.nodes(), clock.nodes())
        self.assertEqual(tuple(other.to_dict()), tuple(clock.to_dict()))
        self.assertEqual(VectorClock({"b": 1, "a": 2}).nodes(), ("a", "b"))


class EventOrderTests(KernelCase):
    """事件全序。"""

    def test_08_events_have_a_total_order(self):
        c1 = Event("c", 1, 1, {"c": 1}, "c1")
        a1 = Event("a", 1, 3, {"c": 1, "a": 1}, "a1")
        b1 = Event("b", 1, 3, {"c": 1, "b": 1}, "b1")
        b2 = Event("b", 2, 4, {"c": 1, "a": 1, "b": 2}, "b2")
        self.assertTrue(c1 < a1)
        self.assertTrue(a1 < b1)
        self.assertTrue(b1 < b2)
        self.assertFalse(b1 < a1)
        self.assertFalse(a1 < a1)
        events = [b2, b1, a1, c1]
        ordered = self.value("排序", order_events, events)
        self.assertEqual([event.label for event in ordered], ["c1", "a1", "b1", "b2"])
        self.assertEqual(order_events(list(reversed(events))), ordered)
        self.assertEqual(order_events([b1, a1]), (a1, b1))
        self.assertEqual(order_events([a1, b1]), (a1, b1))
        self.assertEqual(len(order_events(events)), len(events))
        self.assertTrue(c1.causally_before(b2))


class HistoryTests(KernelCase):
    """因果历史的记录与稳定裁剪。"""

    def test_09_history_is_trimmed_only_when_covered(self):
        history = History()
        already = Event("c", 1, 1, {"c": 1}, "already")
        ahead = Event("a", 2, 5, {"a": 2, "c": 4}, "ahead")
        history.record(already)
        history.record(ahead)
        self.assertEqual(len(history), 2)
        self.assertEqual([event.label for event in history.events()], ["already", "ahead"])
        stable = {"a": 5, "c": 1}
        self.assertTrue(history.covered(already, stable))
        self.assertFalse(history.covered(ahead, stable))
        self.assertEqual(self.value("裁剪", history.trim, stable), 1)
        self.assertEqual([event.label for event in history.events()], ["ahead"])
        self.assertEqual(history.trim({"a": 5, "c": 4}), 1)
        self.assertEqual(history.events(), ())
        self.assertEqual(history.trim({"a": 5, "c": 4}), 0)
        fresh = History([already])
        self.assertEqual(fresh.trim(VectorClock({"c": 1})), 1)
        self.assertEqual(len(fresh), 0)


class IntakeTests(KernelCase):
    """输入卫生：明显不合法的参数必须报 ClockError。"""

    def test_10_invalid_inputs_are_refused(self):
        self.refuses(ClockError, "零步长", LamportClock().tick, 0)
        self.refuses(ClockError, "负数步长", LamportClock().tick, -2)
        self.refuses(ClockError, "负初值", LamportClock, "a", -1)
        self.refuses(ClockError, "非整数初值", LamportClock, "a", "3")
        self.refuses(ClockError, "非映射初值", VectorClock, [("a", 1)])
        self.refuses(ClockError, "负数分量", VectorClock, {"a": -1})
        self.refuses(ClockError, "空节点推进", VectorClock().bump, "")
        self.refuses(ClockError, "负计数折入", VectorClock().observe, "a", -1)
        self.assertFalse(VectorClock().observe("a", 0))
        self.refuses(ClockError, "零事件计数", Event, "a", 0, 1)
        self.refuses(ClockError, "空节点事件", Event, "", 1, 1)
        self.refuses(ClockError, "非事件记录", History().record, 3)
        self.refuses(ClockError, "非映射边界", History().trim, 5)
        self.refuses(ClockError, "非事件排序", order_events, [1])
        self.refuses(ClockError, "跨类比较", LamportClock("a", 1).is_earlier_than, 5)
        self.assertEqual(History().trim({"a": 1}), 0)
        self.assertEqual(order_events([]), ())
        self.assertEqual(LamportClock("a", 4).tick(3), 7)
        self.assertEqual(LamportClock("a", 2).copy().value, 2)
        self.assertEqual(VectorClock({"a": 1}).copy().to_dict(), {"a": 1})
        self.assertEqual(Node("n").snapshot()["node"], "n")
        self.refuses(ClockError, "空节点对象", Node, "")


if __name__ == "__main__":
    unittest.main()
