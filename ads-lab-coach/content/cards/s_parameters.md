# S 参数

- S11：端口 2 匹配时，端口 1 的反射系数。dB 越低，匹配越好。常用门限 < -10 dB。
- S21：端口 2 匹配时，从端口 1 到端口 2 的传输。无源网络中 S21 不会大于 0 dB。
- 无源网络能量约束：|S11|² + |S21|² ≤ 1。
- 回波损耗 RL = -20·log10|S11|，与 S11（dB）数值相同、符号相反。

来源：Pozar《Microwave Engineering》第 4 章 Microwave Network Analysis（4.3 节散射矩阵，页码待核对）。
