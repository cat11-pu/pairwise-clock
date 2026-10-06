# clock

一个纯标准库、可确定复现的逻辑时钟与因果序内核：Lamport 时钟的推进与合并、
向量时钟的逐分量合并、并发与因果判定、事件全序、因果历史裁剪，以及节点标识的稳定次序。
内核不读真实时钟、不取随机数、不做 I/O，也不使用线程与网络，同样的输入序列永远得到同样的结果。

## 目录

- `clock/core.py`：内核实现（`LamportClock`、`VectorClock`、`Event`、`History`、`Node`、`order_events`）
- `tests/test_core.py`：行为测试

## 语义约定

- 计数与节点标识都由调用方注入：计数是非负整数，节点标识是非空字符串。
- `LamportClock` 只前进不后退：`tick` 每次推进给定的步长；`observe` 折入远端时间戳后
  停在严格大于本地与远端两者的位置；`merge` 只取两者中的较大值，不额外推进。
  `is_earlier_than` 是严格先后：时间戳相等的一对互不早于对方。
- `VectorClock` 记录从每个节点见过的最高计数：`merge` 逐分量取大，同一份状态合并两次结果不变；
  `get` 对没记录过的节点返回 0；`relation` 返回 `equal`、`before`、`after` 或 `concurrent` 之一，
  两侧出现过的节点都要参与比较，并发关系对称；`dominates` 只在严格领先时为真。
- `Event` 带着所属节点、节点内计数、逻辑时间戳与当时的向量：`order_events` 给出全序，
  先按逻辑时间戳，再按节点标识打破平局；`causally_before` 按向量判断因果先后，
  因果序传递、无环，事件不先于自己。
- `History` 保留事件直到稳定边界覆盖：`stable` 是每个节点都已交付到的计数，
  只有事件向量的每个分量都不超过 `stable` 的对应计数时，`covered` 才为真，`trim` 才会丢掉它。
- `VectorClock.nodes` 与 `to_dict` 都按节点标识的字典序给出稳定次序，与插入顺序无关。

## 怎么跑测试

在项目根目录执行：

    python3 -m unittest discover -s tests -v

Windows 上把 `python3` 换成你的解释器路径，例如：

    C:/Users/<你>/AppData/Local/Programs/Python/Python313/python.exe -m unittest discover -s tests -v

只依赖 Python 3 标准库，不需要装任何包，也不需要联网。
